from __future__ import annotations

from datetime import datetime, timedelta, timezone

from starlette.requests import Request

from whats_hot_api.config import config
from whats_hot_api.models import NewsFlashItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import post
from whats_hot_api.utils.newsflash import metrics, text_or_none

ROUTE_NAME = "usaspending"
SOURCE_LINK = "https://www.usaspending.gov/search"
KEYWORDS = ["defense", "military", "missile", "ammunition", "aircraft", "naval"]

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "USAspending",
    "description": "美国联邦政府近 14 天国防相关合同交易，按单笔交易金额排序",
    "link": SOURCE_LINK,
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    list_data = await _get_list(no_cache)
    return RouterData(
        kind="newsflash",
        **ROUTE_META,
        type="国防相关合同交易",
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


async def _get_list(no_cache: bool) -> dict:
    start_date, end_date = _date_range()
    body = {
        "filters": {
            "keywords": KEYWORDS,
            "time_period": [{"start_date": start_date, "end_date": end_date}],
            "award_type_codes": ["A", "B", "C", "D"],
        },
        "fields": [
            "Award ID",
            "Recipient Name",
            "Action Date",
            "Transaction Amount",
            "Transaction Description",
            "Awarding Agency",
            "Awarding Sub Agency",
            "Award Type",
            "Mod",
            "generated_internal_id",
        ],
        "limit": 20,
        "page": 1,
        "sort": "Transaction Amount",
        "order": "desc",
    }
    result = await post(
        url="https://api.usaspending.gov/api/v2/search/spending_by_transaction/",
        body=body,
        no_cache=no_cache,
        ttl=config.NEWSFLASH_CACHE_TTL,
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36", "Accept": "application/json"},
        cache_key=f"usaspending:defense-transactions:{start_date}:{end_date}",
    )

    data: list[NewsFlashItem] = []
    for item in (result.data or {}).get("results") or []:
        award_id = text_or_none(item.get("Award ID"))
        recipient = text_or_none(item.get("Recipient Name"))
        action_date = text_or_none(item.get("Action Date"))
        generated_id = text_or_none(item.get("generated_internal_id"))
        amount = item.get("Transaction Amount")
        if not award_id or not recipient or not action_date or not generated_id or not isinstance(amount, (int, float)):
            continue
        modification = text_or_none(item.get("Mod")) or "base"
        description = text_or_none(item.get("Transaction Description")) or "No transaction description provided."
        content, status = _bounded_content(description)
        detail_url = f"https://www.usaspending.gov/award/{generated_id}/"
        data.append(
            NewsFlashItem(
                id=f"{generated_id}:{modification}:{action_date}:{amount:g}",
                title=f"{recipient} · {_format_amount(amount)}",
                content=content,
                summary=description[:300] if len(description) > 300 else None,
                contentStatus=status,
                source=text_or_none(item.get("Awarding Agency")) or "USAspending",
                isImportant=amount >= 100_000_000,
                tags=_labels(item.get("Award Type"), item.get("Awarding Sub Agency")),
                metrics=metrics(
                    transactionAmount=amount,
                    actionDate=action_date,
                    awardId=award_id,
                    modification=modification,
                    awardingAgency=text_or_none(item.get("Awarding Agency")),
                    awardingSubAgency=text_or_none(item.get("Awarding Sub Agency")),
                ),
                timestamp=get_time(action_date),
                url=detail_url,
                mobileUrl=detail_url,
            )
        )
    return {"from_cache": result.from_cache, "update_time": result.update_time, "data": data}


def _date_range() -> tuple[str, str]:
    end_date = datetime.now(timezone.utc).date()
    return (end_date - timedelta(days=14)).isoformat(), end_date.isoformat()


def _format_amount(value: float) -> str:
    absolute = abs(value)
    if absolute >= 1_000_000_000:
        return f"${value / 1_000_000_000:.2f}B"
    if absolute >= 1_000_000:
        return f"${value / 1_000_000:.2f}M"
    if absolute >= 1_000:
        return f"${value / 1_000:.2f}K"
    return f"${value:,.2f}"


def _bounded_content(value: str, limit: int = 1200) -> tuple[str, str]:
    normalized = " ".join(value.split())
    if len(normalized) <= limit:
        return normalized, "full"
    return f"{normalized[:limit].rstrip()}…", "truncated"


def _labels(*values: object) -> list[str]:
    result: list[str] = []
    for value in values:
        label = text_or_none(value)
        if label and label not in result:
            result.append(label)
    return result
