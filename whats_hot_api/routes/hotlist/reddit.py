from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote

from bs4 import BeautifulSoup
from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "reddit"
_MAX_ITEMS = 30

SUBREDDITS = {
    "programming": "programming",
    "webdev": "webdev",
    "rust": "rust",
    "golang": "golang",
    "startups": "startups",
    "saas": "SaaS",
    "entrepreneur": "Entrepreneur",
    "machinelearning": "MachineLearning",
    "localllama": "LocalLLaMA",
    "reinforcementlearning": "reinforcementlearning",
    "sideproject": "SideProject",
    "indiehackers": "indiehackers",
    "microsaas": "microsaas",
    "robotics": "robotics",
    "hardware": "hardware",
    "gadgets": "gadgets",
    "embedded": "embedded",
    "raspberrypi": "raspberry_pi",
    "neuralink": "Neuralink",
    "bci": "BCI",
    "neuroscience": "neuroscience",
    "neuroengineering": "neuroengineering",
    "cogsci": "cogsci",
}
TYPE_MAP = {board: f"r/{subreddit}" for board, subreddit in SUBREDDITS.items()}

ROUTE_META: dict[str, Any] = {
    "name": ROUTE_NAME,
    "title": "Reddit",
    "description": "Curated programming, startup, AI, hardware and science communities.",
    "link": "https://www.reddit.com/",
    "params": {"type": {"name": "社区", "type": TYPE_MAP}},
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    requested_type = request.query_params.get("type", "programming")
    board_type = requested_type if requested_type in SUBREDDITS else "programming"
    list_data = await _get_list(board_type, no_cache)
    subreddit = SUBREDDITS[board_type]
    return RouterData(
        **{**ROUTE_META, "link": f"https://www.reddit.com/r/{quote(subreddit)}/"},
        type=TYPE_MAP[board_type],
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


async def _get_list(board_type: str, no_cache: bool) -> dict[str, Any]:
    subreddit = SUBREDDITS[board_type]
    url = f"https://www.reddit.com/r/{quote(subreddit)}/hot.json?limit=50&raw_json=1"
    result = await get(
        url=url,
        no_cache=no_cache,
        response_type="json",
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Accept": "application/json",
        },
    )
    children = ((result.data or {}).get("data") or {}).get("children") or []
    items: list[ListItem] = []
    for child in children:
        post = child.get("data") if isinstance(child, dict) else None
        if not isinstance(post, dict) or post.get("stickied"):
            continue
        title = _text(post.get("title"))
        permalink = _text(post.get("permalink"))
        discussion_url = f"https://www.reddit.com{permalink}" if permalink else ""
        value = post.get("url") if not post.get("is_self") else discussion_url
        target_url = value if _valid_url(value) else discussion_url
        if not title or not _valid_url(target_url):
            continue
        items.append(
            ListItem(
                id=f"reddit-{subreddit}-{post.get('id') or len(items)}",
                title=title,
                desc=_clean_html(post.get("selftext")),
                hot=post.get("score"),
                cover=_reddit_image(post),
                timestamp=get_time(post.get("created_utc")),
                url=target_url,
                mobileUrl=discussion_url or target_url,
            )
        )
        if len(items) >= _MAX_ITEMS:
            break
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": items,
    }


def _reddit_image(post: dict[str, Any]) -> str | None:
    for value in (
        post.get("thumbnail"),
        post.get("url_overridden_by_dest"),
        ((post.get("preview") or {}).get("images") or [{}])[0]
        .get("source", {})
        .get("url"),
    ):
        if _valid_url(value):
            return str(value).replace("&amp;", "&")
    return None


def _clean_html(value: Any) -> str | None:
    text = _text(BeautifulSoup(str(value or ""), "lxml").get_text(" ", strip=True))
    return text[:500] or None


def _text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _valid_url(value: Any) -> bool:
    return isinstance(value, str) and value.startswith(("https://", "http://"))
