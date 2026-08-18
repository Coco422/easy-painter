from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel


ItemT = TypeVar("ItemT")


class PageResponse(BaseModel, Generic[ItemT]):
    items: list[ItemT]
    total: int
    page: int
    page_size: int
