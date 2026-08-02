from __future__ import annotations

from enum import StrEnum


class Category(StrEnum):
    HOTLIST = "hotlist"
    NEWSFLASH = "newsflash"
    GOLD = "gold"


CATEGORY_LABELS: dict[str, str] = {
    Category.HOTLIST: "热搜",
    Category.NEWSFLASH: "快讯",
    Category.GOLD: "黄金",
}
