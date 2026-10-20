"""Admin-managed ZPAY configuration. Ciphertext only in DB; master key only in env."""
from __future__ import annotations

import json

from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models.payment import PaymentConfiguration
from app.schemas.payment import PaymentConfigInput
from app.services.zpay import ZpayConfig, ZpayError, configured


def cipher(settings: Settings) -> Fernet:
    try:
        return Fernet(settings.payment_config_encryption_key.get_secret_value().encode("ascii"))
    except (ValueError, UnicodeError):
        raise ZpayError("encryption_unavailable") from None


def latest(db: Session) -> PaymentConfiguration | None:
    return db.scalar(select(PaymentConfiguration).order_by(PaymentConfiguration.revision.desc()).limit(1))


def effective(settings: Settings, row: PaymentConfiguration | None) -> Settings:
    if row is None:
        return settings
    try:
        payload = json.loads(cipher(settings).decrypt(row.key_ciphertext.encode("ascii")))
        if (payload["revision"], payload["merchant_id"], payload["gateway_url"]) != (row.revision, row.merchant_id, row.gateway_url):
            raise ZpayError("configuration_unreadable")
        key = payload["key"]
        if not isinstance(key, str):
            raise ZpayError("configuration_unreadable")
    except (InvalidToken, ValueError, UnicodeError, KeyError, TypeError):
        raise ZpayError("configuration_unreadable") from None
    return settings.model_copy(update={
        "zpay_enabled": row.enabled, "zpay_gateway_url": row.gateway_url,
        "zpay_merchant_id": row.merchant_id, "zpay_key": SecretStr(key),
        "zpay_public_base_url": row.public_base_url, "zpay_payment_methods": row.payment_methods,
    })


def for_order(db: Session, settings: Settings, revision: int | None) -> Settings:
    if revision is None:
        return settings  # Orders created before dashboard configuration used env credentials.
    row = db.get(PaymentConfiguration, revision)
    if row is None:
        raise ZpayError("configuration_unreadable")
    return effective(settings, row)


def admin_view(db: Session, settings: Settings) -> dict:
    row = latest(db)
    encryption_ready = True
    try:
        cipher(settings)
    except ZpayError:
        encryption_ready = False
    configuration_error = False
    try:
        ready = configured(effective(settings, row))
    except ZpayError:
        ready = False
        configuration_error = True
    return {
        "revision": row.revision if row else 0,
        "enabled": row.enabled if row else settings.zpay_enabled,
        "gateway_url": row.gateway_url if row else settings.zpay_gateway_url or "https://zpayz.cn",
        "merchant_id": row.merchant_id if row else settings.zpay_merchant_id,
        "public_base_url": row.public_base_url if row else settings.zpay_public_base_url,
        "payment_methods": row.payment_methods if row else settings.zpay_payment_methods,
        "key_configured": bool(row.key_ciphertext) if row else bool(settings.zpay_key.get_secret_value()),
        "configured": ready, "encryption_ready": encryption_ready,
        "configuration_error": configuration_error,
    }


def save(db: Session, settings: Settings, body: PaymentConfigInput) -> None:
    try:
        encryption = cipher(settings)
    except ZpayError:
        raise HTTPException(503, "支付配置加密尚未就绪，请联系运维配置服务器加密主密钥。") from None
    row = latest(db)
    revision = row.revision if row else 0
    if body.expected_revision != revision:
        raise HTTPException(409, "支付配置已被修改，请刷新后重试。")
    key = body.merchant_key.get_secret_value()
    try:
        previous = None
        if not key:
            previous = effective(settings, row)
            if (body.merchant_id, body.gateway_url.rstrip("/")) != (previous.zpay_merchant_id, previous.zpay_gateway_url.rstrip("/")):
                raise HTTPException(422, "更换商户或网关时请重新填写对应商户密钥。")
            key = previous.zpay_key.get_secret_value()
        candidate = settings.model_copy(update={
            "zpay_key": SecretStr(key), "zpay_merchant_id": body.merchant_id,
            "zpay_gateway_url": body.gateway_url, "zpay_public_base_url": body.public_base_url,
        })
        valid = ZpayConfig.from_settings(candidate)
    except (ZpayError, ValueError):
        raise HTTPException(422, "请填写有效的商户 ID、商户密钥及 HTTPS 根地址；已保存密钥无法读取时请重新填写。") from None
    next_revision = revision + 1
    payload = json.dumps({"revision": next_revision, "merchant_id": valid.merchant_id,
                          "gateway_url": valid.gateway_url, "key": key}).encode("utf-8")
    db.add(PaymentConfiguration(
        revision=next_revision, enabled=body.enabled, gateway_url=valid.gateway_url,
        merchant_id=valid.merchant_id, key_ciphertext=encryption.encrypt(payload).decode("ascii"),
        public_base_url=valid.public_base_url, payment_methods=body.payment_methods,
    ))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "支付配置已被修改，请刷新后重试。") from None
