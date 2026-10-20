from __future__ import annotations

import html as html_lib
import re
from datetime import UTC, datetime

from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.http_client import get

ROUTE_NAME = 'minimax-news'
SOURCE_LINK = 'https://platform.minimax.io/docs/release-notes/models'
MARKDOWN_URL = 'https://platform.minimax.io/docs/release-notes/models.md'
ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": 'MiniMax',
    "description": 'MiniMax model and product news.',
    "link": SOURCE_LINK,
}
# "#### Oct. 19, 2026" (some months only: "#### Apr. 2026") followed by <Card title href>description</Card>.
_HEADING = re.compile(r"^#{2,4}\s+([A-Z][a-z]{2,8})\.?\s+(?:(\d{1,2}),\s+)?(\d{4})\s*$", re.M)
_CARD = re.compile(r'<Card\s+title="([^"]+)"[^>]*?href="([^"]+)"[^>]*>(.*?)</Card>', re.S)


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:  # noqa: ARG001
    list_data = await _get_list(no_cache)
    return RouterData(
        **ROUTE_META,
        type="Release Notes",
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


async def _get_list(no_cache: bool) -> dict:
    # The API platform's model release notes, as the Mintlify markdown export.
    result = await get(url=MARKDOWN_URL, no_cache=no_cache, response_type="text")
    return {"from_cache": result.from_cache, "update_time": result.update_time, "data": parse_release_notes(result.data)}


def _month(name: str) -> int | None:
    for fmt in ("%b", "%B"):
        try:
            return datetime.strptime(name[:3] if fmt == "%b" else name, fmt).month
        except ValueError:
            continue
    return None


def parse_release_notes(markdown: str) -> list[ListItem]:
    headings = list(_HEADING.finditer(markdown or ""))
    items: dict[str, ListItem] = {}
    for index, heading in enumerate(headings):
        month = _month(heading.group(1))
        if month is None:
            continue
        day = int(heading.group(2) or 1)  # Month-only headings are dated to the 1st.
        when = datetime(int(heading.group(3)), month, day, tzinfo=UTC)
        end = headings[index + 1].start() if index + 1 < len(headings) else len(markdown)
        for title, href, body in _CARD.findall(markdown[heading.end():end]):
            url = href if href.startswith("https://") else f"https://platform.minimax.io{href}"
            key = f"{when:%Y%m%d}:{title}"
            if key in items:
                continue
            description = re.sub(r"\s+", " ", html_lib.unescape(re.sub(r"<[^>]+>", " ", body))).strip()
            items[key] = ListItem(id=key, title=html_lib.unescape(title).strip(), url=url, mobileUrl=url,
                                  desc=description or None, timestamp=int(when.timestamp() * 1000),
                                  hotLabel=None if heading.group(2) else "month")
    return sorted(items.values(), key=lambda i: (i.timestamp or 0, i.id), reverse=True)
