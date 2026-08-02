"""Typed fetch inputs and outputs shared by every public adapter."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

from whats_hot_api.models import RouterData


class CachePolicy(StrEnum):
    PREFER = "prefer"
    REFRESH = "refresh"
    ONLY = "only"


@dataclass(frozen=True, slots=True)
class FetchRequest:
    site: str
    path_type: str
    params: dict[str, str] = field(default_factory=dict)
    limit: int | None = None
    cache_policy: CachePolicy = CachePolicy.PREFER


@dataclass(frozen=True, slots=True)
class SourceDescriptor:
    name: str
    title: str
    description: str | None
    link: str | None
    category: str
    category_label: str
    params: dict[str, Any] | None
    types: tuple[str, ...]
    default_type: str
    validate_type: bool
    data_path: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "title": self.title,
            "description": self.description,
            "link": self.link,
            "category": self.category,
            "categoryLabel": self.category_label,
            "params": self.params,
            "types": list(self.types),
            "defaultType": self.default_type,
            "validateType": self.validate_type,
            "dataPath": self.data_path,
        }


@dataclass(frozen=True, slots=True)
class FetchResult:
    request: FetchRequest
    data: RouterData
    observed_at: datetime

    @property
    def from_cache(self) -> bool:
        return self.data.fromCache
