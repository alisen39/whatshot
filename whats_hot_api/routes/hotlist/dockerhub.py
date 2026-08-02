from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "dockerhub"

SOURCE_LINK = "https://hub.docker.com/search?type=image"
_COUNT_RE = re.compile(r"([\d.]+)\s*([KMB])?\+?", re.IGNORECASE)

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "Docker Hub",
    "description": "Docker Hub 官方推荐的容器镜像",
    "link": SOURCE_LINK,
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    list_data = await _get_list(no_cache)
    return RouterData(
        **ROUTE_META,
        type="推荐镜像",
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


async def _get_list(no_cache: bool) -> dict:
    result = await get(
        url=SOURCE_LINK,
        no_cache=no_cache,
        response_type="text",
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 Chrome/126 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-US,en;q=0.9",
        },
    )
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": _parse_cards(result.data or ""),
    }


def _parse_cards(html: str) -> list[ListItem]:
    soup = BeautifulSoup(html, "lxml")
    data: list[ListItem] = []
    seen_ids: set[str] = set()
    for rank, card in enumerate(soup.select('[data-testid="product-card"]'), start=1):
        anchor = card.select_one('[data-testid="product-card-link"][href]')
        if anchor is None:
            continue
        href = str(anchor.get("href") or "").strip()
        title = anchor.get_text(" ", strip=True)
        image_id = _image_id(href)
        if not href or not title or not image_id or image_id in seen_ids:
            continue

        description_node = card.select_one("p.MuiTypography-body2")
        description = (
            description_node.get_text(" ", strip=True) if description_node else ""
        )
        badge_node = card.select_one('[data-testid="productBadge"]')
        publisher = badge_node.get_text(" ", strip=True) if badge_node else ""
        labels = [
            str(node.get("aria-label") or "").strip()
            for node in card.select("[aria-label]")
            if str(node.get("aria-label") or "").strip()
        ]
        updated = _label(labels, "Updated ")
        pulls_label = _label(labels, suffix=" pulls")
        stars_label = _label(labels, suffix=" stars")
        pulls = _count_from_label(pulls_label)
        cover_node = card.select_one("img[src]")
        cover = str(cover_node.get("src") or "").strip() if cover_node else ""
        item_url = urljoin(SOURCE_LINK, href)

        desc_parts = [f"排名：{rank}"]
        if description:
            desc_parts.append(description)
        if publisher:
            desc_parts.append(publisher)
        if pulls_label:
            desc_parts.append(pulls_label)
        if stars_label:
            desc_parts.append(stars_label)
        if updated:
            desc_parts.append(updated)

        seen_ids.add(image_id)
        data.append(
            ListItem(
                id=image_id,
                title=title,
                author=publisher or None,
                desc=" · ".join(desc_parts),
                hot=pulls,
                cover=cover or None,
                url=item_url,
                mobileUrl=item_url,
            )
        )
        if len(data) == 30:
            break
    return data


def _image_id(href: str) -> str:
    if href.startswith("/_/"):
        return f"library/{href.removeprefix('/_/').strip('/')}"
    if href.startswith("/r/"):
        return href.removeprefix("/r/").strip("/")
    prefix = "/hardened-images/catalog/"
    if href.startswith(prefix):
        return href.removeprefix(prefix).strip("/")
    return ""


def _label(
    labels: list[str],
    prefix: str | None = None,
    suffix: str | None = None,
) -> str:
    for label in labels:
        if prefix and label.startswith(prefix):
            return label
        if suffix and label.endswith(suffix):
            return label
    return ""


def _count_from_label(label: str) -> int | None:
    match = _COUNT_RE.search(label)
    if not match:
        return None
    number = float(match.group(1))
    multiplier = {
        "K": 1_000,
        "M": 1_000_000,
        "B": 1_000_000_000,
        "": 1,
    }[(match.group(2) or "").upper()]
    return round(number * multiplier)
