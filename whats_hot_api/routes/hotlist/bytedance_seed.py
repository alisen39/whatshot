from __future__ import annotations

from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.http_client import get

ROUTE_NAME = 'bytedance-seed'
SOURCE_LINK = 'https://seed.bytedance.com/zh/blog'
API_URL = 'https://seed.bytedance.com/api/get_article_list_v2'
ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": 'ByteDance Seed Research',
    "description": 'ByteDance Seed AI research and model updates.',
    "link": SOURCE_LINK,
}
PAGES = 2
# Pages are filtered after paging, so a short page does not mean the end (use has_more).
_EXCLUDED_AREAS = {"Recruitment"}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:  # noqa: ARG001
    list_data = await _get_list(no_cache)
    return RouterData(
        **ROUTE_META,
        type="Blog",
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


async def _get_list(no_cache: bool) -> dict:
    # The official blog's own list API (article_type=2 = blog posts).
    articles, token, results = [], 0, []
    for _ in range(PAGES):
        result = await get(url=API_URL, params={"article_type": 2, "count": 20, "order_desc": "true", "page_token": token},
                           no_cache=no_cache)
        results.append(result)
        data = result.data if isinstance(result.data, dict) else {}
        articles += data.get("sub_article_list") or []
        if not data.get("has_more") or data.get("next_page_token") in (None, token):
            break
        token = data["next_page_token"]
    return {"from_cache": all(r.from_cache for r in results), "update_time": results[0].update_time,
            "data": parse_articles(articles)}


def parse_articles(articles: list[dict]) -> list[ListItem]:
    items: dict[str, ListItem] = {}
    for article in articles:
        meta = article.get("ArticleMeta") or {}
        en, zh = article.get("ArticleSubContentEn") or {}, article.get("ArticleSubContentZh") or {}
        areas = {a.get("ResearchAreaName") for a in meta.get("ResearchArea") or [] if isinstance(a, dict)}
        key = (en.get("TitleKey") or "").strip()
        title = (zh.get("Title") if meta.get("StatusZh") == 2 else None) or en.get("Title") or zh.get("Title")
        published = meta.get("PublishDate")
        if not key or not title or areas & _EXCLUDED_AREAS or not isinstance(published, int) or key in items:
            continue
        url = f"https://seed.bytedance.com/zh/blog/{key}"
        abstract = ((zh.get("Abstract") if meta.get("StatusZh") == 2 else None) or en.get("Abstract") or "").strip()
        items[key] = ListItem(id=str(meta.get("ArticleID") or key), title=title.strip(), url=url, mobileUrl=url,
                              desc=abstract or None, timestamp=published, isPinned=bool(meta.get("IsPinned")) or None,
                              hotLabel=next(iter(sorted(a for a in areas if a)), None))
    return sorted(items.values(), key=lambda i: (i.timestamp or 0, i.id), reverse=True)
