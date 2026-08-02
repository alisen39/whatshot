from __future__ import annotations

from starlette.requests import Request

from whats_hot_api.config import config
from whats_hot_api.models import NewsFlashItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get
from whats_hot_api.utils.newsflash import compact_strings, metrics, text_or_none

ROUTE_NAME = "cisa-kev"

SOURCE_LINK = "https://www.cisa.gov/known-exploited-vulnerabilities-catalog"

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "CISA KEV",
    "description": "CISA 已知被利用漏洞目录最新条目",
    "link": SOURCE_LINK,
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    list_data = await _get_list(no_cache)
    return RouterData(
        kind="newsflash",
        **ROUTE_META,
        type="已知被利用漏洞",
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


async def _get_list(no_cache: bool) -> dict:
    url = "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json"
    result = await get(
        url=url,
        no_cache=no_cache,
        ttl=config.NEWSFLASH_CACHE_TTL,
        response_type="json",
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Accept": "application/json",
            "Referer": SOURCE_LINK,
        },
    )

    payload = result.data or {}
    items = sorted(
        payload.get("vulnerabilities") or [],
        key=lambda item: (
            str(item.get("dateAdded") or ""),
            str(item.get("cveID") or ""),
        ),
        reverse=True,
    )[:20]

    data: list[NewsFlashItem] = []
    for item in items:
        cve_id = text_or_none(item.get("cveID"))
        title = text_or_none(item.get("vulnerabilityName"))
        short_description = text_or_none(item.get("shortDescription"))
        required_action = text_or_none(item.get("requiredAction"))
        if not cve_id or not title:
            continue

        content_parts = [part for part in (short_description, required_action) if part]
        detail_url = f"https://nvd.nist.gov/vuln/detail/{cve_id}"
        tags = compact_strings([
            item.get("vendorProject"),
            item.get("product"),
            *(item.get("cwes") or []),
        ])
        ransomware_use = text_or_none(item.get("knownRansomwareCampaignUse"))
        data.append(
            NewsFlashItem(
                id=cve_id,
                title=f"{cve_id} · {title}",
                content="\n\n".join(content_parts) or title,
                summary=short_description,
                contentStatus="full",
                source="CISA",
                isImportant=ransomware_use == "Known",
                tags=tags,
                metrics=metrics(
                    dateAdded=text_or_none(item.get("dateAdded")),
                    dueDate=text_or_none(item.get("dueDate")),
                    ransomwareUse=ransomware_use,
                ),
                timestamp=get_time(item.get("dateAdded")),
                url=detail_url,
                mobileUrl=detail_url,
            )
        )
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": data,
    }
