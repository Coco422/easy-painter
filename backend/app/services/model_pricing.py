from __future__ import annotations

from collections.abc import Mapping
import re
from typing import Any


def normalize_credit_cost_by_size(value: Any) -> dict[str, int]:
    """Return a safe size-to-price map while keeping legacy scalar prices valid."""
    if not isinstance(value, Mapping):
        return {}
    result: dict[str, int] = {}
    for raw_size, raw_cost in value.items():
        size = str(raw_size).strip().lower()
        if not size:
            continue
        try:
            cost = int(raw_cost)
        except (TypeError, ValueError):
            continue
        if cost >= 1:
            result[size] = cost
    return result


def normalize_credit_cost(value: Any, default: int = 2) -> int:
    try:
        cost = int(value)
    except (TypeError, ValueError):
        cost = default
    return max(0, cost)


def size_pricing_tier(size: str) -> str:
    normalized_size = str(size or "auto").strip().lower()
    if normalized_size == "auto":
        return "1k"
    match = re.fullmatch(r"(\d+)x(\d+)", normalized_size)
    if not match:
        return "1k"
    long_edge = max(int(match.group(1)), int(match.group(2)))
    if long_edge <= 1792:
        return "1k"
    if long_edge <= 2560:
        return "2k"
    return "4k"


def base_credit_cost_for_size(model: Mapping[str, Any], size: str) -> int:
    fallback = normalize_credit_cost(model.get("credit_cost", 2))
    mapping = normalize_credit_cost_by_size(model.get("credit_cost_by_size"))
    normalized_size = str(size or "auto").strip().lower()
    if normalized_size in mapping:
        return mapping[normalized_size]
    tier = size_pricing_tier(normalized_size)
    return mapping.get(tier, mapping.get("auto", fallback))


def effective_credit_cost_map(
    model: Mapping[str, Any],
    multiplier_bps: int,
    calculate_effective_credit_cost,
) -> dict[str, int]:
    mapping = normalize_credit_cost_by_size(model.get("credit_cost_by_size"))
    return {
        size: calculate_effective_credit_cost(cost, multiplier_bps)
        for size, cost in mapping.items()
    }
