from __future__ import annotations

from typing import Any

from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "kickstarter-tech"
_URL = "https://www.kickstarter.com/discover/advanced?format=json&category_id=16&sort=popularity&state=live"
ROUTE_META: dict[str, Any] = {
    "name": ROUTE_NAME,
    "title": "Kickstarter · Technology",
    "description": "Technology crowdfunding projects on Kickstarter.",
    "link": "https://www.kickstarter.com/discover/categories/technology",
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:  # noqa: ARG001
    result = await get(
        _URL,
        no_cache=no_cache,
        response_type="json",
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Referer": ROUTE_META["link"],
        },
    )
    data = _build_items((result.data or {}).get("projects") or [])
    return RouterData(
        **ROUTE_META,
        type="Technology",
        total=len(data),
        fromCache=result.from_cache,
        updateTime=result.update_time,
        data=data,
    )


def _build_items(projects: Any) -> list[ListItem]:
    items: list[ListItem] = []
    for project in projects if isinstance(projects, list) else []:
        if not isinstance(project, dict):
            continue
        title = str(project.get("name") or "").strip()
        url = ((project.get("urls") or {}).get("web") or {}).get("project")
        if not title or not isinstance(url, str) or not url.startswith(("https://", "http://")):
            continue
        photo = project.get("photo") if isinstance(project.get("photo"), dict) else {}
        percent = project.get("percent_funded")
        items.append(ListItem(
            id=f"kickstarter-{project.get('id') or len(items)}",
            title=title,
            desc=str(project.get("blurb") or "").strip() or None,
            hot=percent,
            cover=photo.get("med") or photo.get("full") or photo.get("small"),
            timestamp=get_time(project.get("launched_at")),
            url=url,
            mobileUrl=url,
        ))
        if len(items) >= 30:
            break
    return items
