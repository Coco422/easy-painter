from __future__ import annotations

import hashlib

from fastapi import Request


def extract_client_ip(request: Request) -> str:
    for header in ("cf-connecting-ip", "x-forwarded-for", "x-real-ip"):
        raw_value = request.headers.get(header)
        if not raw_value:
            continue
        if header == "x-forwarded-for":
            return raw_value.split(",")[0].strip()
        return raw_value.strip()
    client = request.client
    return client.host if client else "unknown"


def rate_limit_identity(ip_address: str) -> str:
    return hashlib.sha256(ip_address.encode("utf-8")).hexdigest()[:32]
