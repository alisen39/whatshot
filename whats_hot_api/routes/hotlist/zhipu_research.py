from __future__ import annotations

import html as html_lib
import re
from datetime import datetime, timedelta, timezone

from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.http_client import get

ROUTE_NAME = 'zhipu-research'
SOURCE_LINK = 'https://www.zhipuai.cn/zh/research'
API_URL = 'https://www.zhipuai.cn/api/articles'
# www.zhipuai.cn times out from overseas exits (seen 2026-10-19 from a US datacenter);
# the open platform's release notes are reachable everywhere and list every model launch.
RELEASES_URL = 'https://docs.bigmodel.cn/cn/update/new-releases.md'
_UPDATE = re.compile(r'<Update\s+label="(\d{4})-(\d{1,2})-(\d{1,2})"\s+description="([^"]+)"')
_CST = timezone(timedelta(hours=8))
ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": 'Zhipu AI Research',
    "description": 'Zhipu AI research and model updates.',
    "link": SOURCE_LINK,
}
# The site's own CMS list (Payload REST). Inactive posts are hidden on the site;
# createAt is the editorial publish time (2024 values are import dates, not used here).
_PARAMS = {"where[category][equals]": "blog", "where[active][equals]": "true", "sort": "-createAt", "limit": 30,
           "depth": 0, "select[title_zh]": "true", "select[title_en]": "true", "select[createAt]": "true",
           "select[resume_zh]": "true", "select[externalUrl_en]": "true"}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:  # noqa: ARG001
    list_data = await _get_list(no_cache)
    return RouterData(
        **ROUTE_META,
        type="Research",
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


async def _get_list(no_cache: bool) -> dict:
    try:
        result = await get(url=API_URL, params=_PARAMS, no_cache=no_cache)
        docs = result.data.get("docs") if isinstance(result.data, dict) else None
        items = parse_articles(docs or [])
    except Exception:  # noqa: BLE001 - any CMS failure falls back to the release notes
        items = []
    if not items:
        result = await get(url=RELEASES_URL, no_cache=no_cache, response_type="text")
        items = parse_release_notes(result.data)
    return {"from_cache": result.from_cache, "update_time": result.update_time, "data": items}


def parse_release_notes(markdown: str) -> list[ListItem]:
    """<Update label="2026-8-19" description="GLM-5.3 新一代旗舰模型上线"> blocks; dates are China dates."""
    items: dict[str, ListItem] = {}
    for year, month, day, description in _UPDATE.findall(markdown or ""):
        when = datetime(int(year), int(month), int(day), tzinfo=_CST)
        title = html_lib.unescape(description).strip()
        key = f"{when:%Y-%m-%d}:{title}"
        if not title or key in items:
            continue
        url = f"https://docs.bigmodel.cn/cn/update/new-releases#{year}-{month}-{day}"
        items[key] = ListItem(id=key, title=title, url=url, mobileUrl=url, timestamp=int(when.timestamp() * 1000))
    return sorted(items.values(), key=lambda i: (i.timestamp or 0, i.id), reverse=True)


def parse_articles(docs: list[dict]) -> list[ListItem]:
    items = []
    for doc in docs:
        title = next((t for t in (doc.get("title_zh"), doc.get("title_en")) if isinstance(t, str) and t.strip()), None)
        try:
            timestamp = int(datetime.fromisoformat(str(doc.get("createAt")).replace("Z", "+00:00")).timestamp() * 1000)
        except ValueError:
            continue
        if not title or doc.get("id") is None:
            continue
        url = f"https://www.zhipuai.cn/zh/research/{doc['id']}"
        resume = doc.get("resume_zh")
        items.append(ListItem(id=str(doc["id"]), title=title.strip(), url=url, mobileUrl=url, timestamp=timestamp,
                              desc=resume.strip() if isinstance(resume, str) and resume.strip() else None))
    return sorted(items, key=lambda i: (i.timestamp or 0, i.id), reverse=True)
