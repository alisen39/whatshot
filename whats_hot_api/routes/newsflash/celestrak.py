from __future__ import annotations

import re

from starlette.requests import Request

from whats_hot_api.config import config
from whats_hot_api.models import NewsFlashItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get
from whats_hot_api.utils.newsflash import metrics, text_or_none

ROUTE_NAME = "celestrak"
SOURCE_LINK = "https://celestrak.org/"

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "CelesTrak",
    "description": "CelesTrak 最近 30 天发射并进入 NORAD 编目的空间物体",
    "link": SOURCE_LINK,
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    list_data = await _get_list(no_cache)
    return RouterData(
        kind="newsflash",
        **ROUTE_META,
        type="近30日新增空间物体",
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


async def _get_list(no_cache: bool) -> dict:
    result = await get(
        url="https://celestrak.org/NORAD/elements/gp.php",
        no_cache=no_cache,
        ttl=config.NEWSFLASH_CACHE_TTL,
        response_type="json",
        params={"GROUP": "last-30-days", "FORMAT": "json"},
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36", "Accept": "application/json", "Referer": SOURCE_LINK},
    )

    records: list[tuple[tuple[int, int, str], NewsFlashItem]] = []
    for item in result.data or []:
        if not isinstance(item, dict):
            continue
        name = text_or_none(item.get("OBJECT_NAME"))
        object_id = text_or_none(item.get("OBJECT_ID"))
        norad_id = item.get("NORAD_CAT_ID")
        epoch = text_or_none(item.get("EPOCH"))
        sort_key = _launch_sort_key(object_id)
        if not name or not object_id or not isinstance(norad_id, int) or not epoch or sort_key is None:
            continue
        classification = _classification(item.get("CLASSIFICATION_TYPE"))
        detail_url = f"https://celestrak.org/satcat/table-satcat.php?CATNR={norad_id}"
        records.append((
            sort_key,
            NewsFlashItem(
                id=str(norad_id),
                title=name,
                content=_content(item, object_id, norad_id, classification),
                contentStatus="full",
                source="CelesTrak",
                tags=[classification, object_id.split("-", 1)[0]],
                metrics=metrics(
                    noradCatalogId=norad_id,
                    internationalDesignator=object_id,
                    classification=classification,
                    elementEpoch=epoch,
                    meanMotion=item.get("MEAN_MOTION"),
                    eccentricity=item.get("ECCENTRICITY"),
                    inclination=item.get("INCLINATION"),
                    rightAscension=item.get("RA_OF_ASC_NODE"),
                    argumentOfPericenter=item.get("ARG_OF_PERICENTER"),
                    revolutionAtEpoch=item.get("REV_AT_EPOCH"),
                ),
                timestamp=get_time(epoch),
                url=detail_url,
                mobileUrl=detail_url,
            ),
        ))
    records.sort(key=lambda pair: pair[0], reverse=True)
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": [item for _, item in records[:25]],
    }


def _launch_sort_key(object_id: str | None) -> tuple[int, int, str] | None:
    if not object_id:
        return None
    match = re.fullmatch(r"(\d{4})-(\d{3})([A-Z]+)", object_id.upper())
    if not match:
        return None
    return int(match.group(1)), int(match.group(2)), match.group(3)


def _classification(value: object) -> str:
    return {"U": "Unclassified", "C": "Classified", "S": "Secret"}.get(str(value or "").upper(), "Unknown")


def _content(item: dict, object_id: str, norad_id: int, classification: str) -> str:
    parts = [
        f"International designator: {object_id}",
        f"NORAD catalog ID: {norad_id}",
        f"Classification: {classification}",
        f"Element epoch: {item.get('EPOCH')}",
    ]
    for label, key, suffix in (
        ("Inclination", "INCLINATION", "°"),
        ("Eccentricity", "ECCENTRICITY", ""),
        ("Mean motion", "MEAN_MOTION", " rev/day"),
    ):
        value = item.get(key)
        if isinstance(value, (int, float)):
            parts.append(f"{label}: {value:g}{suffix}")
    return "\n".join(parts)
