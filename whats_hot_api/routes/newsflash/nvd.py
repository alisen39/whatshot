from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from starlette.requests import Request

from whats_hot_api.config import config
from whats_hot_api.models import NewsFlashItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get
from whats_hot_api.utils.newsflash import compact_strings, metrics, text_or_none

ROUTE_NAME = "nvd"
SOURCE_LINK = "https://nvd.nist.gov/vuln"
_API_URL = "https://services.nvd.nist.gov/rest/json/cves/2.0"
_PAGE_SIZE = 100

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "NVD",
    "description": "NIST 国家漏洞数据库最新发布的 CVE",
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
    window_end = datetime.now(timezone.utc)
    window_start = window_end - timedelta(days=14)
    common_params = {
        "pubStartDate": _nvd_datetime(window_start),
        "pubEndDate": _nvd_datetime(window_end),
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Accept": "application/json",
        "Referer": SOURCE_LINK,
    }
    window_key = window_end.replace(minute=0, second=0, microsecond=0).isoformat()
    count_result = await get(
        url=_API_URL,
        no_cache=no_cache,
        ttl=config.NEWSFLASH_CACHE_TTL,
        response_type="json",
        params={**common_params, "resultsPerPage": "1"},
        headers=headers,
        cache_key=f"nvd:latest:count:{window_key}",
    )
    total_results = _to_nonnegative_int((count_result.data or {}).get("totalResults"))
    if total_results == 0:
        return {
            "from_cache": count_result.from_cache,
            "update_time": count_result.update_time,
            "data": [],
        }

    start_index = max(0, total_results - _PAGE_SIZE)
    page_result = await get(
        url=_API_URL,
        no_cache=no_cache,
        ttl=config.NEWSFLASH_CACHE_TTL,
        response_type="json",
        params={
            **common_params,
            "resultsPerPage": str(_PAGE_SIZE),
            "startIndex": str(start_index),
        },
        headers=headers,
        cache_key=f"nvd:latest:page:{window_key}:{start_index}",
    )

    items = sorted(
        (page_result.data or {}).get("vulnerabilities") or [],
        key=lambda item: str((item.get("cve") or {}).get("published") or ""),
        reverse=True,
    )
    data: list[NewsFlashItem] = []
    for item in items:
        cve = item.get("cve") if isinstance(item.get("cve"), dict) else {}
        if cve.get("vulnStatus") == "Rejected":
            continue
        cve_id = text_or_none(cve.get("id"))
        description = _english_description(cve)
        if not cve_id or not description:
            continue
        severity, score = _severity(cve)
        severity_label = severity or "UNKNOWN"
        score_label = f" {score:g}" if score is not None else ""
        detail_url = f"https://nvd.nist.gov/vuln/detail/{cve_id}"
        data.append(
            NewsFlashItem(
                id=cve_id,
                title=f"{cve_id} · {severity_label}{score_label}",
                content=description,
                contentStatus="full",
                source="NVD",
                isImportant=score is not None and score >= 9.0,
                tags=compact_strings([
                    severity_label,
                    cve.get("vulnStatus"),
                    *_weaknesses(cve),
                ]),
                metrics=metrics(
                    severity=severity_label,
                    score=score,
                    status=text_or_none(cve.get("vulnStatus")),
                    published=text_or_none(cve.get("published")),
                    lastModified=text_or_none(cve.get("lastModified")),
                ),
                timestamp=get_time(cve.get("published")),
                url=detail_url,
                mobileUrl=detail_url,
            )
        )
        if len(data) == 20:
            break
    return {
        "from_cache": count_result.from_cache and page_result.from_cache,
        "update_time": page_result.update_time,
        "data": data,
    }


def _nvd_datetime(value: datetime) -> str:
    return value.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _to_nonnegative_int(value: object) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _english_description(cve: dict[str, Any]) -> str:
    for description in cve.get("descriptions") or []:
        if description.get("lang") == "en":
            return " ".join(str(description.get("value") or "").split())
    return ""


def _severity(cve: dict[str, Any]) -> tuple[str | None, float | None]:
    metric_groups = cve.get("metrics") or {}
    for key in ("cvssMetricV40", "cvssMetricV31", "cvssMetricV30", "cvssMetricV2"):
        entries = metric_groups.get(key) or []
        if not entries:
            continue
        entry = entries[0]
        cvss_data = entry.get("cvssData") or {}
        severity = text_or_none(cvss_data.get("baseSeverity") or entry.get("baseSeverity"))
        score_value = cvss_data.get("baseScore")
        try:
            score = float(score_value) if score_value is not None else None
        except (TypeError, ValueError):
            score = None
        return severity, score
    return None, None


def _weaknesses(cve: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for weakness in cve.get("weaknesses") or []:
        for description in weakness.get("description") or []:
            value = text_or_none(description.get("value"))
            if value and value not in values:
                values.append(value)
    return values
