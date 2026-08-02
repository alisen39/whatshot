from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from starlette.requests import Request

from whats_hot_api.config import config
from whats_hot_api.models import NewsFlashItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get
from whats_hot_api.utils.newsflash import compact_strings, metrics

ROUTE_NAME = "osv"

SOURCE_LINK = "https://osv.dev/list"
_SEVERITY_RE = re.compile(
    r"Severity\s*-\s*(?P<score>\d+(?:\.\d+)?)\s*\((?P<label>[^)]+)\)",
    re.IGNORECASE,
)
_DETAIL_PLACEHOLDER = "See record for full details"

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "OSV.dev",
    "description": "OSV.dev 最新开源软件漏洞与恶意软件包记录",
    "link": SOURCE_LINK,
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    list_data = await _get_list(no_cache)
    return RouterData(
        kind="newsflash",
        **ROUTE_META,
        type="最新漏洞",
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


async def _get_list(no_cache: bool) -> dict:
    result = await get(
        url=SOURCE_LINK,
        no_cache=no_cache,
        ttl=config.NEWSFLASH_CACHE_TTL,
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
    data = _parse_list(result.data or "")
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": data,
    }


def _parse_list(html: str) -> list[NewsFlashItem]:
    soup = BeautifulSoup(html, "lxml")
    data: list[NewsFlashItem] = []
    seen_ids: set[str] = set()
    for row in soup.select(".vuln-table-rows .vuln-table-row"):
        anchor = row.select_one('a[href^="/vulnerability/"]')
        if anchor is None:
            continue
        vulnerability_id = anchor.get_text(" ", strip=True)
        href = str(anchor.get("href") or "").strip()
        if not vulnerability_id or not href or vulnerability_id in seen_ids:
            continue

        packages = compact_strings([
            node.get_text(" ", strip=True) for node in row.select(".vuln-packages li")
        ])
        summary_node = row.select_one(".vuln-summary")
        summary = summary_node.get_text(" ", strip=True) if summary_node else ""
        has_summary = bool(summary and summary != _DETAIL_PLACEHOLDER)
        attributes = compact_strings([
            node.get_text(" ", strip=True) for node in row.select(".vuln-attributes .tag")
        ])
        score, severity = _severity(attributes)
        time_node = row.select_one("relative-time[datetime]")
        published = str(time_node.get("datetime") or "").strip() if time_node else ""
        detail_url = urljoin(SOURCE_LINK, href)

        package_text = "、".join(packages)
        content_parts = [summary] if has_summary else []
        if package_text:
            content_parts.append(f"Affected packages: {package_text}")
        if attributes:
            content_parts.append(f"Attributes: {'、'.join(attributes)}")
        content = "\n\n".join(content_parts) or vulnerability_id
        title_detail = summary if has_summary else (packages[0] if packages else "Vulnerability record")

        seen_ids.add(vulnerability_id)
        data.append(
            NewsFlashItem(
                id=vulnerability_id,
                title=f"{vulnerability_id} · {title_detail}",
                content=content,
                summary=summary if has_summary else None,
                contentStatus="summary",
                source="OSV.dev",
                isImportant=score is not None and score >= 9.0,
                tags=attributes,
                metrics=metrics(
                    published=published or None,
                    packages=packages or None,
                    severity=severity,
                    score=score,
                ),
                timestamp=get_time(published or None),
                url=detail_url,
                mobileUrl=detail_url,
            )
        )
        if len(data) == 20:
            break
    return data


def _severity(attributes: list[str]) -> tuple[float | None, str | None]:
    for attribute in attributes:
        match = _SEVERITY_RE.search(attribute)
        if not match:
            continue
        return float(match.group("score")), match.group("label").strip()
    return None, None
