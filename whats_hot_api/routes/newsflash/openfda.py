from __future__ import annotations

import hashlib
from urllib.parse import quote

from starlette.requests import Request

from whats_hot_api.config import config
from whats_hot_api.models import NewsFlashItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get
from whats_hot_api.utils.newsflash import compact_strings, metrics, text_or_none

ROUTE_NAME = "openfda"

SOURCE_LINK = "https://open.fda.gov/apis/food/enforcement/"
_API_URL = "https://api.fda.gov/food/enforcement.json"

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "openFDA",
    "description": "美国 FDA 最新食品召回执法报告",
    "link": SOURCE_LINK,
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    list_data = await _get_list(no_cache)
    return RouterData(
        kind="newsflash",
        **ROUTE_META,
        type="食品召回",
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


async def _get_list(no_cache: bool) -> dict:
    result = await get(
        url=_API_URL,
        no_cache=no_cache,
        ttl=config.NEWSFLASH_CACHE_TTL,
        response_type="json",
        params={
            "sort": "report_date:desc",
            "limit": "100",
        },
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Accept": "application/json",
            "Referer": SOURCE_LINK,
        },
    )

    rows = (result.data or {}).get("results") or []
    rows = sorted(
        rows,
        key=lambda item: (
            str(item.get("report_date") or ""),
            str(item.get("recall_number") or ""),
        ),
        reverse=True,
    )
    data: list[NewsFlashItem] = []
    seen: set[str] = set()
    for row in rows:
        firm = text_or_none(row.get("recalling_firm"))
        product = text_or_none(row.get("product_description"))
        reason = text_or_none(row.get("reason_for_recall"))
        report_date = text_or_none(row.get("report_date"))
        if not firm or not product or not reason or not report_date:
            continue

        item_id = _item_id(row)
        if item_id in seen:
            continue
        seen.add(item_id)

        recall_number = text_or_none(row.get("recall_number"))
        classification = text_or_none(row.get("classification"))
        detail_url = _detail_url(recall_number, row.get("event_id"))
        content_parts = [
            f"Product: {product}",
            f"Reason: {reason}",
        ]
        distribution = text_or_none(row.get("distribution_pattern"))
        quantity = text_or_none(row.get("product_quantity"))
        if distribution:
            content_parts.append(f"Distribution: {distribution}")
        if quantity:
            content_parts.append(f"Quantity: {quantity}")

        data.append(
            NewsFlashItem(
                id=item_id,
                title=f"{firm} · {_shorten(product, 120)}",
                content="\n\n".join(content_parts),
                summary=reason[:500],
                contentStatus="full",
                source="FDA",
                isImportant=classification == "Class I",
                tags=compact_strings([
                    classification,
                    row.get("status"),
                    row.get("country"),
                    row.get("state"),
                ]),
                metrics=metrics(
                    recallNumber=recall_number,
                    eventId=text_or_none(row.get("event_id")),
                    reportDate=report_date,
                    initiationDate=text_or_none(row.get("recall_initiation_date")),
                    terminationDate=text_or_none(row.get("termination_date")),
                    voluntaryMandated=text_or_none(row.get("voluntary_mandated")),
                ),
                timestamp=_report_timestamp(report_date),
                url=detail_url,
                mobileUrl=detail_url,
            )
        )

    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": data,
    }


def _item_id(row: dict) -> str:
    recall_number = text_or_none(row.get("recall_number"))
    if recall_number and recall_number.upper() != "N/A":
        return recall_number
    event_id = text_or_none(row.get("event_id")) or "unknown"
    product = text_or_none(row.get("product_description")) or ""
    digest = hashlib.sha1(product.encode("utf-8")).hexdigest()[:12]
    return f"event-{event_id}-{digest}"


def _detail_url(recall_number: str | None, event_id: object) -> str:
    if recall_number and recall_number.upper() != "N/A":
        search = f'recall_number:"{recall_number}"'
    else:
        search = f'event_id:"{text_or_none(event_id) or ""}"'
    return f"{_API_URL}?search={quote(search, safe='')}&limit=1"


def _report_timestamp(value: str) -> int | None:
    if len(value) == 8 and value.isdigit():
        value = f"{value[:4]}-{value[4:6]}-{value[6:]}"
    return get_time(value)


def _shorten(value: str, limit: int) -> str:
    normalized = " ".join(value.split())
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[:limit].rstrip()}…"
