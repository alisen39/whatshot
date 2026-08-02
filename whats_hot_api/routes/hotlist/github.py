from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone

from bs4 import BeautifulSoup
from starlette.requests import Request

from whats_hot_api.config import config
from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.cache import CacheData, cache
from whats_hot_api.utils.feed import parse_feed
from whats_hot_api.utils.http_client import get
from whats_hot_api.utils.logger import logger

ROUTE_NAME = "github"

TYPE_MAP = {
    "daily": "日榜",
    "weekly": "周榜",
    "monthly": "月榜",
    "blog": "GitHub Blog",
}

ROUTE_META: dict = {
    "name": "github",
    "title": "GitHub",
    "description": "GitHub trending repositories and official product updates.",
    "link": "https://github.com/",
    "params": {
        "type": {
            "name": "排行榜分区",
            "type": TYPE_MAP,
        },
    },
}

async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    type_param = request.query_params.get("type", "daily")
    type_ = type_param if type_param in TYPE_MAP else "daily"
    if type_ == "blog":
        list_data = await _get_blog_posts(no_cache)
        data = list_data["data"]
        link = "https://github.blog/"
    else:
        list_data = await _get_trending_repos(type_, no_cache)
        data = [
            ListItem(
                id=v["url"].removeprefix("https://github.com"),
                title=v["repo"],
                desc=v["description"] or None,
                author=v.get("owner"),
                hot=v["stars"] or None,
                url=v["url"],
                mobileUrl=v["url"],
            )
            for v in list_data["data"]
        ]
        link = f"https://github.com/trending?since={type_}"
    return RouterData(
        **{**ROUTE_META, "link": link},
        type=TYPE_MAP[type_],
        total=len(data),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=data,
    )


async def _get_blog_posts(no_cache: bool) -> dict:
    result = await get(
        url="https://github.blog/feed/",
        no_cache=no_cache,
        response_type="text",
        headers={
            "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml",
            "Referer": "https://github.blog/",
        },
    )
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": parse_feed(result.data),
    }


async def _get_trending_repos(type_: str, no_cache: bool = False, ttl: int | None = None) -> dict:
    url = f"https://github.com/trending?since={type_}"
    cache_ttl = config.HOTLIST_CACHE_TTL if ttl is None else ttl

    if not no_cache:
        cached = await cache.get(url)
        if cached:
            logger.info("💾 [CACHE] The request is cached")
            return {
                "from_cache": True,
                "update_time": cached.update_time,
                "data": cached.data or [],
            }

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Accept-Encoding": "gzip, deflate",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Cache-Control": "max-age=0",
    }

    max_retries = 3
    last_error: Exception | None = None

    for i in range(max_retries):
        try:
            result = await get(
                url=url,
                no_cache=True,
                response_type="text",
                headers=headers,
                cache_key=f"{url}:raw-html",
            )
            html = result.data

            soup = BeautifulSoup(html, "lxml")
            results = []

            for el in soup.select("article.Box-row"):
                repo_anchor = el.select_one("h2 a")
                if not repo_anchor:
                    continue

                full_name_text = repo_anchor.get_text().strip()
                full_name_text = re.sub(r"\r?\n", "", full_name_text)
                full_name_text = re.sub(r"\s+", " ", full_name_text)
                parts = [s.strip() for s in full_name_text.split("/")]
                owner = parts[0] if len(parts) > 0 else ""
                repo_name = parts[1] if len(parts) > 1 else ""

                href = repo_anchor.get("href", "")
                repo_url = f"https://github.com{href}"

                desc_el = el.select_one("p.col-9.color-fg-muted")
                description = desc_el.get_text().strip() if desc_el else ""

                lang_el = el.select_one('[itemprop="programmingLanguage"]')
                language = lang_el.get_text().strip() if lang_el else ""

                stars_el = el.select_one('a[href$="/stargazers"]')
                stars_text = stars_el.get_text().strip() if stars_el else ""

                forks_el = el.select_one('a[href$="/forks"]')
                forks_text = forks_el.get_text().strip() if forks_el else ""

                # Parse stars like "1,234" to int
                try:
                    stars_int = int(stars_text.replace(",", "").strip()) if stars_text else 0
                except ValueError:
                    stars_int = 0

                results.append({
                    "owner": owner,
                    "repo": repo_name,
                    "url": repo_url,
                    "description": description,
                    "language": language,
                    "stars": stars_int,
                    "forks": forks_text,
                })

            update_time = datetime.now(timezone.utc).isoformat()
            await cache.set(url, CacheData(update_time=update_time, data=results), cache_ttl)
            logger.info("✅ request was successful")
            return {"from_cache": False, "update_time": update_time, "data": results}

        except Exception as e:
            last_error = e
            logger.error(f"❌ [ERROR] attempt {i + 1} failed: {e}")
            if i < max_retries - 1:
                await asyncio.sleep(2**i)

    raise last_error or Exception("request failed")
