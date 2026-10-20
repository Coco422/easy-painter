from __future__ import annotations

from datetime import datetime, timedelta, timezone
import re
import secrets
import time
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import func, select, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models.credit_transaction import CreditTransaction, CreditTransactionType
from app.models.payment import RechargeOrder, RechargePackage
from app.models.user import User
from app.schemas.payment import CreateRechargeRequest, RechargeOrderResponse
from app.services.credit_provenance import add_credit_lot, ensure_credit_provenance
from app.services.zpay import ZpayConfig, ZpayError, ZpayGateway, money_to_fen
from app.services import payment_config


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def aware(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def order_response(order: RechargeOrder) -> RechargeOrderResponse:
    return RechargeOrderResponse(
        id=order.id, package_name=order.package_name, amount_fen=order.amount_fen,
        paid_credits=order.paid_credits, gift_credits=order.gift_credits, payment_method=order.payment_method,
        status=order.status, expired=order.status != "paid" and aware(order.expires_at) <= utcnow(),
        created_at=aware(order.created_at), expires_at=aware(order.expires_at), paid_at=aware(order.paid_at) if order.paid_at else None,
    )


def get_gateway(settings: Settings) -> ZpayGateway:
    try:
        return ZpayGateway(ZpayConfig.from_settings(settings))
    except (ZpayError, ValueError):
        raise HTTPException(503, "充值服务尚未配置，请稍后再试。") from None


def gateway_for_order(db: Session, settings: Settings, order: RechargeOrder) -> ZpayGateway:
    return get_gateway(payment_config.for_order(db, settings, order.config_revision))


def create_order(db: Session, *, user_id: str, body: CreateRechargeRequest, intent: str, settings: Settings) -> RechargeOrder:
    if not re.fullmatch(r"[A-Za-z0-9_-]{8,128}", intent):
        raise HTTPException(422, "请提供有效的充值请求标识。")
    # Serialize creation per account, also bounding abandoned intents.
    user = db.scalar(select(User).where(User.id == user_id).with_for_update().execution_options(populate_existing=True))
    if not user:
        raise HTTPException(401, "请重新登录。")
    existing = db.scalar(select(RechargeOrder).where(RechargeOrder.user_id == user_id, RechargeOrder.idempotency_key == intent))
    if existing:
        if existing.package_id != body.package_id or existing.package_revision != body.package_revision or existing.payment_method != body.payment_method:
            raise HTTPException(409, "该请求已用于另一笔充值，请刷新后重试。")
        return existing
    config = payment_config.latest(db)
    try:
        runtime = payment_config.effective(settings, config)
    except ZpayError:
        raise HTTPException(503, "支付配置暂时不可用，请联系管理员。") from None
    if not runtime.zpay_enabled:
        raise HTTPException(503, "在线充值尚未开放。")
    if body.payment_method not in runtime.zpay_payment_methods:
        raise HTTPException(422, "该支付方式尚未开放，请重新选择。")
    gateway = get_gateway(runtime)
    package = db.scalar(select(RechargePackage).where(RechargePackage.id == body.package_id).with_for_update())
    if not package or not package.is_enabled:
        raise HTTPException(409, "该充值套餐已下架，请重新选择。")
    if package.revision != body.package_revision:
        raise HTTPException(409, "充值套餐已更新，请刷新后确认价格。")
    recent = db.scalar(select(func.count()).select_from(RechargeOrder).where(
        RechargeOrder.user_id == user_id, RechargeOrder.created_at >= utcnow() - timedelta(hours=1))) or 0
    if recent >= 20:
        raise HTTPException(429, "充值订单创建过于频繁，请稍后再试。")
    created = utcnow()
    order = RechargeOrder(
        id=f"{int(time.time()):010d}{secrets.randbelow(10**20):020d}", user_id=user_id,
        package_id=package.id, package_revision=package.revision, package_name=package.name,
        amount_fen=package.price_fen, paid_credits=package.paid_credits, gift_credits=package.gift_credits,
        payment_method=body.payment_method, gateway_url=gateway.config.gateway_url,
        merchant_id=gateway.config.merchant_id, idempotency_key=intent,
        config_revision=config.revision if config else None,
        created_at=created, expires_at=created + timedelta(minutes=max(1, min(settings.zpay_order_ttl_minutes, 1440))),
    )
    db.add(order)
    db.commit()
    db.refresh(order)
    return order


def reconcile_recharge_orders(*, session_factory, settings: Settings, limit: int = 10) -> dict[str, int]:
    """Worker-only bounded lookback. Disabling new checkout does not lose payments."""
    counts = {"checked": 0, "paid": 0, "failed": 0}
    with session_factory() as db:
        ids = db.scalars(select(RechargeOrder.id).where(
            RechargeOrder.status == "pending", RechargeOrder.created_at >= utcnow() - timedelta(days=30),
            or_(RechargeOrder.last_checked_at.is_(None), RechargeOrder.last_checked_at < utcnow() - timedelta(minutes=5)),
        ).order_by(RechargeOrder.last_checked_at.asc().nulls_first(), RechargeOrder.created_at)
          .limit(max(1, min(limit, 20)))).all()
    for order_id in ids:
        with session_factory() as db:
            try:
                pending = db.get(RechargeOrder, order_id)
                if pending is None:
                    continue
                gateway = gateway_for_order(db, settings, pending)
                order = confirm_payment(db, order_id=order_id, gateway=gateway)
                counts["checked"] += 1
                counts["paid"] += int(order.status == "paid")
            except (ZpayError, HTTPException) as exc:
                db.rollback()
                order = db.scalar(select(RechargeOrder).where(RechargeOrder.id == order_id).with_for_update())
                if order and order.status != "paid":
                    order.last_checked_at = utcnow()
                    order.last_check_error = str(exc) if isinstance(exc, ZpayError) else "not_configured"
                    db.commit()
                counts["failed"] += 1
    return counts


def check_order_config(order: RechargeOrder, gateway: ZpayGateway) -> None:
    if order.gateway_url != gateway.config.gateway_url or order.merchant_id != gateway.config.merchant_id:
        raise ZpayError("merchant_configuration_changed")


def check_identity(order: RechargeOrder, data: dict[str, object], *, notification: bool = False) -> str:
    if type(data.get("pid")) not in (str, int) or str(data["pid"]) != order.merchant_id:
        raise ZpayError("merchant_mismatch")
    if data.get("out_trade_no") != order.id or data.get("type") != order.payment_method or money_to_fen(data.get("money")) != order.amount_fen:
        raise ZpayError("order_mismatch")
    trade_no = data.get("trade_no")
    if not isinstance(trade_no, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", trade_no):
        raise ZpayError("invalid_trade_number")
    if notification and data.get("trade_status") != "TRADE_SUCCESS":
        raise ZpayError("payment_not_successful")
    if order.provider_trade_no and order.provider_trade_no != trade_no:
        raise ZpayError("trade_number_mismatch")
    return trade_no


def confirm_payment(db: Session, *, order_id: str, gateway: ZpayGateway,
                    notification: dict[str, str] | None = None) -> RechargeOrder:
    order = db.get(RechargeOrder, order_id)
    if order is None:
        raise ZpayError("order_not_found")
    check_order_config(order, gateway)
    notify_trade = check_identity(order, notification, notification=True) if notification is not None else None
    if order.status == "paid":
        return order
    verified = gateway.query_order(order.id)
    trade_no = check_identity(order, verified)
    if notify_trade and notify_trade != trade_no:
        raise ZpayError("trade_number_mismatch")
    paid = type(verified.get("status")) in (str, int) and str(verified["status"]) == "1"
    # User -> order is the global payment locking order. Network I/O is above it.
    user = db.scalar(select(User).where(User.id == order.user_id).with_for_update().execution_options(populate_existing=True))
    order = db.scalar(select(RechargeOrder).where(RechargeOrder.id == order_id).with_for_update().execution_options(populate_existing=True))
    if not user or not order:
        raise ZpayError("order_not_found")
    check_order_config(order, gateway)
    check_identity(order, verified)
    if order.status == "paid":
        return order
    order.last_checked_at = utcnow()
    order.last_check_error = None
    if not paid:
        db.commit()
        return order
    ensure_credit_provenance(db, user_id=user.id, balance=user.credits)
    transaction_id = str(uuid4())
    user.credits += order.paid_credits + order.gift_credits
    db.add(CreditTransaction(
        id=transaction_id, user_id=user.id, amount=order.paid_credits + order.gift_credits,
        balance_after=user.credits, reason=f"recharge:{order.id}", transaction_type=CreditTransactionType.RECHARGE,
        idempotency_key=f"recharge:{order.id}", details={
            "order_id": order.id, "amount_fen": order.amount_fen, "currency": "CNY",
            "paid_credits": order.paid_credits, "gift_credits": order.gift_credits,
            "provider": "zpay", "provider_trade_no": trade_no,
        },
    ))
    add_credit_lot(db, user_id=user.id, amount=order.paid_credits, source_type="paid", source_id=f"recharge-paid:{order.id}",
                   amount_fen=order.amount_fen, recharge_order_id=order.id)
    add_credit_lot(db, user_id=user.id, amount=order.gift_credits, source_type="gift", source_id=f"recharge-gift:{order.id}",
                   recharge_order_id=order.id)
    order.status = "paid"
    order.provider_trade_no = trade_no
    order.paid_at = utcnow()
    order.credit_transaction_id = transaction_id
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise ZpayError("payment_integrity_conflict") from None
    db.refresh(order)
    return order
