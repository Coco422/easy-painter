"""Small ZPAY v1 adapter. No SDK dependency; never trust a callback alone.

Protocol reference: https://z-pay.cn/doc.html
The v1 protocol requires raw, unescaped MD5 canonicalization and GET query
credentials. Reject ambiguous delimiters; restrict TLS/redirects and redact keys.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import hashlib
import hmac
import json
import re
from urllib.parse import urlsplit

import httpx

from app.core.config import Settings


class ZpayError(RuntimeError):
    """Public error codes only: never include upstream URLs or response bodies."""


def money_to_fen(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, (str, int, Decimal)):
        raise ZpayError("invalid_amount")
    text = str(value)
    if not re.fullmatch(r"(?:0|[1-9][0-9]{0,7})(?:\.[0-9]{1,2})?", text):
        raise ZpayError("invalid_amount")
    fen = int(Decimal(text) * 100)
    if fen <= 0:
        raise ZpayError("invalid_amount")
    return fen


def format_fen(fen: int) -> str:
    return f"{fen // 100}.{fen % 100:02d}"


def sign_parameters(params: dict[str, str], key: str) -> str:
    parts = []
    for name in sorted(params):
        value = params[name]
        if not re.fullmatch(r"[a-zA-Z0-9_]+", name) or not isinstance(value, str):
            raise ZpayError("invalid_parameters")
        if name in {"sign", "sign_type"} or value == "":
            continue
        if len(value) > 1024 or "&" in value or any(ord(c) < 32 for c in value):
            raise ZpayError("ambiguous_parameters")
        parts.append(f"{name}={value}")
    return hashlib.md5(("&".join(parts) + key).encode("utf-8")).hexdigest()


def verify_notification(params: dict[str, str], key: str) -> None:
    if params.get("sign_type", "MD5") != "MD5" or not re.fullmatch(r"[0-9a-f]{32}", params.get("sign", "")):
        raise ZpayError("invalid_signature")
    if not hmac.compare_digest(sign_parameters(params, key), params["sign"]):
        raise ZpayError("invalid_signature")


def _base_url(value: str, *, local_development: bool = False) -> str:
    if any(ord(c) < 33 or ord(c) == 127 for c in value) or "\\" in value:
        raise ZpayError("invalid_configuration")
    parsed = urlsplit(value)
    try:
        valid_port = parsed.port in (None, 443) or (local_development and parsed.hostname in {"127.0.0.1", "localhost"})
    except ValueError:
        raise ZpayError("invalid_configuration") from None
    scheme_ok = parsed.scheme == "https" or (local_development and parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost"})
    if not scheme_ok or not parsed.hostname or not valid_port or parsed.username or parsed.password or parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        raise ZpayError("invalid_configuration")
    return value.rstrip("/")


@dataclass(frozen=True)
class ZpayConfig:
    gateway_url: str
    merchant_id: str
    key: str
    public_base_url: str

    @classmethod
    def from_settings(cls, settings: Settings) -> ZpayConfig:
        key = settings.zpay_key.get_secret_value()
        if not re.fullmatch(r"[A-Za-z0-9_-]{16,128}", key) or not re.fullmatch(r"[A-Za-z0-9]{1,64}", settings.zpay_merchant_id):
            raise ZpayError("not_configured")
        return cls(
            _base_url(settings.zpay_gateway_url), settings.zpay_merchant_id, key,
            _base_url(settings.zpay_public_base_url, local_development=settings.app_env != "production"),
        )

    def __repr__(self) -> str:
        return "ZpayConfig(key=[REDACTED])"


def configured(settings: Settings) -> bool:
    try:
        ZpayConfig.from_settings(settings)
        return True
    except (ZpayError, ValueError):
        return False


class ZpayGateway:
    def __init__(self, config: ZpayConfig):
        self.config = config

    def checkout(self, *, order_id: str, name: str, amount_fen: int, method: str) -> tuple[str, dict[str, str]]:
        params = {
            "pid": self.config.merchant_id, "type": method, "out_trade_no": order_id,
            "name": f"AI绘图额度 · {name}", "money": format_fen(amount_fen),
            "notify_url": self.config.public_base_url + "/api/v1/payments/zpay/notify",
            "return_url": self.config.public_base_url + "/recharge/return",
        }
        params["sign"] = sign_parameters(params, self.config.key)
        params["sign_type"] = "MD5"
        return self.config.gateway_url + "/submit.php", params

    def query_order(self, order_id: str) -> dict[str, object]:
        # ZPAY documents GET with a key for this endpoint. Never follow a redirect
        # carrying those credentials. The logging filter redacts the configured key.
        try:
            with httpx.Client(timeout=httpx.Timeout(3.5, connect=2.0), follow_redirects=False, trust_env=False) as client:
                with client.stream("GET", self.config.gateway_url + "/api.php", params={
                    "act": "order", "pid": self.config.merchant_id, "key": self.config.key, "out_trade_no": order_id,
                }) as response:
                    if response.status_code != 200:
                        raise ZpayError("query_failed")
                    body = bytearray()
                    for chunk in response.iter_bytes():
                        body.extend(chunk)
                        if len(body) > 65536:
                            raise ZpayError("invalid_response")
            data = json.loads(body, parse_float=Decimal)
        except (httpx.HTTPError, ValueError, UnicodeError):
            raise ZpayError("query_failed") from None
        if not isinstance(data, dict) or type(data.get("code")) not in (int, str) or str(data["code"]) != "1":
            raise ZpayError("query_failed")
        return data
