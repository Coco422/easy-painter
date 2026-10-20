from __future__ import annotations

from datetime import timedelta
from urllib.parse import parse_qsl

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from fastapi.responses import PlainTextResponse
from pydantic import Field
from sqlalchemy import func, select, update, or_
from sqlalchemy.orm import Session

from app.core.auth import require_admin, require_current_user
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.models.payment import RechargeOrder, RechargePackage
from app.models.user import User
from app.schemas.payment import CreateRechargeRequest, PaymentConfigInput, RechargeCheckoutResponse, RechargeOrderResponse, RechargePackageInput, RechargePackageResponse
from app.services import payments, payment_config
from app.services.zpay import ZpayError, configured, verify_notification


payment_router = APIRouter()
admin_payment_router = APIRouter(dependencies=[Depends(require_admin)])


class UpdatePackageRequest(RechargePackageInput):
    expected_revision: int = Field(ge=1, strict=True)


def package_response(package: RechargePackage) -> RechargePackageResponse:
    return RechargePackageResponse(**{key: getattr(package, key) for key in RechargePackageResponse.model_fields})


def _private(response: Response) -> None:
    response.headers["Cache-Control"] = "private, no-store"


@payment_router.get("/recharge/catalog")
def recharge_catalog(response: Response, settings: Settings = Depends(get_settings), db: Session = Depends(get_db)):
    _private(response)
    packages = db.scalars(select(RechargePackage).where(RechargePackage.is_enabled.is_(True)).order_by(RechargePackage.sort_order, RechargePackage.created_at)).all()
    try:
        runtime = payment_config.effective(settings, payment_config.latest(db))
        enabled = runtime.zpay_enabled and configured(runtime)
        methods = runtime.zpay_payment_methods
    except ZpayError:
        enabled, methods = False, []
    return {"enabled": enabled, "payment_methods": methods,
            "packages": [package_response(p) for p in packages]}


@payment_router.post("/recharge/orders", response_model=RechargeCheckoutResponse)
def create_recharge(body: CreateRechargeRequest, response: Response, idempotency_key: str = Header(alias="Idempotency-Key"),
                    user: User = Depends(require_current_user), db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    _private(response)
    order = payments.create_order(db, user_id=user.id, body=body, intent=idempotency_key, settings=settings)
    return _checkout_response(order, settings, db)


def _checkout_response(order: RechargeOrder, settings: Settings, db: Session) -> RechargeCheckoutResponse:
    if order.status == "paid" or payments.aware(order.expires_at) <= payments.utcnow():
        return RechargeCheckoutResponse(order=payments.order_response(order))
    current = payment_config.latest(db)
    if not (current.enabled if current else settings.zpay_enabled):
        raise HTTPException(503, "在线充值尚未开放。")
    try:
        gateway = payments.gateway_for_order(db, settings, order)
        payments.check_order_config(order, gateway)
        action, fields = gateway.checkout(order_id=order.id, name=order.package_name, amount_fen=order.amount_fen, method=order.payment_method)
    except ZpayError:
        raise HTTPException(503, "支付配置发生变化，请联系管理员。") from None
    return RechargeCheckoutResponse(order=payments.order_response(order), action=action, fields=fields)


@payment_router.post("/recharge/orders/{order_id}/checkout", response_model=RechargeCheckoutResponse)
def resume_recharge_order(order_id: str, response: Response, user: User = Depends(require_current_user),
                          db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    _private(response)
    order = db.scalar(select(RechargeOrder).where(RechargeOrder.id == order_id, RechargeOrder.user_id == user.id))
    if not order:
        raise HTTPException(404, "充值订单不存在。")
    return _checkout_response(order, settings, db)


@payment_router.get("/recharge/orders")
def list_recharge_orders(response: Response, page: int = Query(1, ge=1), user: User = Depends(require_current_user), db: Session = Depends(get_db)):
    _private(response)
    query = select(RechargeOrder).where(RechargeOrder.user_id == user.id)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    orders = db.scalars(query.order_by(RechargeOrder.created_at.desc()).offset((page-1)*20).limit(20)).all()
    return {"items": [payments.order_response(o) for o in orders], "total": total, "page": page, "page_size": 20}


@payment_router.get("/recharge/orders/{order_id}", response_model=RechargeOrderResponse)
def get_recharge_order(order_id: str, response: Response, user: User = Depends(require_current_user), db: Session = Depends(get_db)):
    _private(response)
    order = db.scalar(select(RechargeOrder).where(RechargeOrder.id == order_id, RechargeOrder.user_id == user.id))
    if not order:
        raise HTTPException(404, "充值订单不存在。")
    return payments.order_response(order)


def _refresh(db: Session, order: RechargeOrder, settings: Settings) -> RechargeOrderResponse:
    if order.status == "paid":
        return payments.order_response(order)
    # Reserve a short query slot atomically, including failed upstream calls.
    now = payments.utcnow()
    claimed = db.scalar(update(RechargeOrder).where(RechargeOrder.id == order.id, RechargeOrder.status == "pending",
        or_(RechargeOrder.last_checked_at.is_(None), RechargeOrder.last_checked_at <= now - timedelta(seconds=5)))
        .values(last_checked_at=now).returning(RechargeOrder.id).execution_options(synchronize_session=False))
    db.commit()
    if claimed is None:
        raise HTTPException(429, "刚刚已查询，请稍后再试。", headers={"Retry-After": "5"})
    try:
        result = payments.confirm_payment(db, order_id=order.id, gateway=payments.gateway_for_order(db, settings, order))
    except ZpayError as exc:
        db.rollback()
        failed = db.scalar(select(RechargeOrder).where(RechargeOrder.id == order.id).with_for_update().execution_options(populate_existing=True))
        if failed and failed.status != "paid":
            failed.last_check_error = str(exc)
            db.commit()
        raise HTTPException(503, "支付结果暂时无法确认，请稍后刷新；请勿重复付款。") from None
    return payments.order_response(result)


@payment_router.post("/recharge/orders/{order_id}/refresh", response_model=RechargeOrderResponse)
def refresh_recharge_order(order_id: str, response: Response, user: User = Depends(require_current_user),
                           db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    _private(response)
    order = db.scalar(select(RechargeOrder).where(RechargeOrder.id == order_id, RechargeOrder.user_id == user.id))
    if not order:
        raise HTTPException(404, "充值订单不存在。")
    return _refresh(db, order, settings)


@payment_router.api_route("/payments/zpay/notify", methods=["GET", "POST"], response_class=PlainTextResponse)
async def zpay_notification(request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    try:
        # Parse once, retain duplicates for rejection and bound unauthenticated input.
        raw = request.scope.get("query_string", b"")
        if len(raw) > 16384:
            raise ZpayError("invalid_parameters")
        if request.method == "POST":
            if request.headers.get("content-type", "").split(";")[0] != "application/x-www-form-urlencoded":
                raise ZpayError("invalid_parameters")
            body = bytearray()
            async for chunk in request.stream():
                body.extend(chunk)
                if len(raw) + len(body) > 16384:
                    raise ZpayError("invalid_parameters")
            raw += b"&" + body
        if len(raw) > 16384:
            raise ZpayError("invalid_parameters")
        pairs = parse_qsl(raw.decode("utf-8"), keep_blank_values=True, max_num_fields=32, encoding="utf-8", errors="strict")
        params = dict(pairs)
        if len(params) != len(pairs):
            raise ZpayError("duplicate_parameters")
        order_id = params.get("out_trade_no", "")
        # Synchronous DB/network work runs in the worker thread, not the event loop.
        from starlette.concurrency import run_in_threadpool
        def confirm():
            pending = db.get(RechargeOrder, order_id)
            if pending is None:
                raise ZpayError("order_not_found")
            gateway = payments.gateway_for_order(db, settings, pending)
            verify_notification(params, gateway.config.key)
            return payments.confirm_payment(db, order_id=order_id, gateway=gateway, notification=params)
        order = await run_in_threadpool(confirm)
        if order.status != "paid":
            raise ZpayError("payment_not_confirmed")
    except (ZpayError, ValueError, HTTPException):
        db.rollback()
        return PlainTextResponse("fail", status_code=400, headers={"Cache-Control": "no-store"})
    return PlainTextResponse("success", headers={"Cache-Control": "no-store"})


@admin_payment_router.get("/admin/recharge/config")
def admin_recharge_config(response: Response, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    _private(response)
    return {**payment_config.admin_view(db, settings),
            "packages": [package_response(p) for p in db.scalars(select(RechargePackage).order_by(RechargePackage.sort_order, RechargePackage.created_at)).all()]}


@admin_payment_router.put("/admin/recharge/config")
def admin_save_recharge_config(body: PaymentConfigInput, response: Response, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    _private(response)
    payment_config.save(db, settings, body)
    return admin_recharge_config(response, db, settings)


@admin_payment_router.post("/admin/recharge/packages", response_model=RechargePackageResponse)
def admin_create_package(body: RechargePackageInput, db: Session = Depends(get_db)):
    package = RechargePackage(**body.model_dump())
    db.add(package)
    db.commit()
    db.refresh(package)
    return package_response(package)


@admin_payment_router.put("/admin/recharge/packages/{package_id}", response_model=RechargePackageResponse)
def admin_update_package(package_id: str, body: UpdatePackageRequest, db: Session = Depends(get_db)):
    package = db.scalar(select(RechargePackage).where(RechargePackage.id == package_id).with_for_update().execution_options(populate_existing=True))
    if not package:
        raise HTTPException(404, "充值套餐不存在。")
    if package.revision != body.expected_revision:
        raise HTTPException(409, "套餐已被修改，请刷新后重试。")
    for key, value in body.model_dump(exclude={"expected_revision"}).items():
        setattr(package, key, value)
    package.revision += 1
    package.updated_at = payments.utcnow()
    db.commit()
    return package_response(package)


@admin_payment_router.get("/admin/recharge/orders")
def admin_recharge_orders(response: Response, page: int = Query(1, ge=1), db: Session = Depends(get_db)):
    _private(response)
    total = db.scalar(select(func.count()).select_from(RechargeOrder)) or 0
    rows = db.execute(select(RechargeOrder, User.username).join(User, User.id == RechargeOrder.user_id)
        .order_by(RechargeOrder.created_at.desc()).offset((page-1)*20).limit(20)).all()
    return {"items": [{**payments.order_response(o).model_dump(), "user_id": o.user_id, "username": username,
                        "provider_trade_no": o.provider_trade_no, "last_check_error": o.last_check_error} for o, username in rows],
            "total": total, "page": page, "page_size": 20}


@admin_payment_router.post("/admin/recharge/orders/{order_id}/refresh", response_model=RechargeOrderResponse)
def admin_refresh_recharge(order_id: str, response: Response, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    _private(response)
    order = db.get(RechargeOrder, order_id)
    if not order:
        raise HTTPException(404, "充值订单不存在。")
    return _refresh(db, order, settings)
