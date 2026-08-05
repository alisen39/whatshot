from __future__ import annotations

import asyncio
import time
from typing import Any
from urllib.parse import quote

from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get
from whats_hot_api.utils.logger import logger

ROUTE_NAME = "openrouter"
SOURCE_LINK = "https://openrouter.ai/rankings"

TYPE_MAP: dict[str, str] = {
    "models-week": "LLM 榜 · 本周",
    "models-day": "LLM 榜 · 今日",
    "models-month": "LLM 榜 · 本月",
    "models-trending": "LLM 榜 · 趋势",
    "performance-throughput": "性能 · 吞吐量",
    "performance-latency": "性能 · 延迟",
    "benchmark-intelligence": "基准 · 智能",
    "benchmark-coding": "基准 · 编程",
    "benchmark-agentic": "基准 · Agent",
    "apps-day": "应用 · 今日",
    "apps-week": "应用 · 本周",
    "apps-month": "应用 · 本月",
}

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "OpenRouter",
    "description": "OpenRouter 公开模型、性能、基准测试与应用排行榜",
    "link": SOURCE_LINK,
    "params": {"type": {"name": "榜单分类", "type": TYPE_MAP}},
}

_API_BASE = "https://openrouter.ai/api/frontend/v1"
_HEADERS = {
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0 (compatible; DailyHot/1.0; +https://whatshot.top)",
}
_MAX_ITEMS = 100
_CATALOG_TTL_SECONDS = 24 * 60 * 60
_CATALOG_FAILURE_TTL_SECONDS = 5 * 60
_catalog_lock = asyncio.Lock()
_catalog_by_id: dict[str, dict[str, Any]] = {}
_catalog_loaded_at = 0.0
_catalog_ttl = 0


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    requested_type = request.query_params.get("type", "models-week")
    board_type = requested_type if requested_type in TYPE_MAP else "models-week"
    board = await _get_board(board_type, no_cache)
    return RouterData(
        **ROUTE_META,
        type=TYPE_MAP[board_type],
        total=len(board["data"]),
        fromCache=board["from_cache"],
        updateTime=board["update_time"],
        data=board["data"],
    )


async def _get_board(board_type: str, no_cache: bool) -> dict[str, Any]:
    if board_type.startswith("models-"):
        view = board_type.removeprefix("models-")
        result = await get(
            url=f"{_API_BASE}/rankings/models",
            params={"view": view},
            headers=_HEADERS,
            no_cache=no_cache,
        )
        catalog = await _load_catalog()
        data = _model_items(_data_list(result.data), catalog)
    elif board_type.startswith("performance-"):
        metric = board_type.removeprefix("performance-")
        result = await get(
            url=f"{_API_BASE}/rankings/performance",
            headers=_HEADERS,
            no_cache=no_cache,
        )
        data = _performance_items(_data_list(result.data), metric)
    elif board_type.startswith("benchmark-"):
        category = board_type.removeprefix("benchmark-")
        result = await get(
            url=f"{_API_BASE}/rankings/benchmarks",
            headers=_HEADERS,
            no_cache=no_cache,
        )
        payload = result.data if isinstance(result.data, dict) else {}
        data_node = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        aa_data = (
            data_node.get("aaData")
            if isinstance(data_node.get("aaData"), dict)
            else {}
        )
        data = _benchmark_items(
            aa_data.get(category) if isinstance(aa_data, dict) else None
        )
    else:
        period = board_type.removeprefix("apps-")
        result = await get(
            url=f"{_API_BASE}/rankings/apps",
            headers=_HEADERS,
            no_cache=no_cache,
        )
        payload = result.data if isinstance(result.data, dict) else {}
        data_node = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        data = _app_items(
            data_node.get(period) if isinstance(data_node, dict) else None
        )

    if not data:
        raise ValueError(f"OpenRouter {board_type} returned no valid ranking rows")
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": data[:_MAX_ITEMS],
    }


async def _load_catalog() -> dict[str, dict[str, Any]]:
    global _catalog_by_id, _catalog_loaded_at, _catalog_ttl

    now = time.monotonic()
    if _catalog_loaded_at and now - _catalog_loaded_at < _catalog_ttl:
        return _catalog_by_id

    async with _catalog_lock:
        now = time.monotonic()
        if _catalog_loaded_at and now - _catalog_loaded_at < _catalog_ttl:
            return _catalog_by_id
        try:
            result = await get(
                url=f"{_API_BASE}/catalog/models",
                headers=_HEADERS,
                no_cache=False,
                ttl=_CATALOG_TTL_SECONDS,
                cache_key="openrouter:catalog:models",
            )
            rows = _data_list(result.data)
            index: dict[str, dict[str, Any]] = {}
            for row in rows:
                for key in ("permaslug", "slug"):
                    identifier = str(row.get(key) or "").strip()
                    if identifier:
                        index[identifier] = row
            _catalog_by_id = index
            _catalog_ttl = _CATALOG_TTL_SECONDS
        except Exception as exc:  # noqa: BLE001 - catalog is display-only
            logger.warning(f"⚠️ [OpenRouter] Model catalog unavailable: {exc}")
            _catalog_ttl = _CATALOG_FAILURE_TTL_SECONDS
        _catalog_loaded_at = now
        return _catalog_by_id


def _data_list(payload: object) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    data = payload.get("data")
    if not isinstance(data, list):
        return []
    return [row for row in data if isinstance(row, dict)]


def _model_items(
    rows: list[dict[str, Any]],
    catalog: dict[str, dict[str, Any]],
) -> list[ListItem]:
    items: list[ListItem] = []
    for row in rows:
        permaslug = str(row.get("model_permaslug") or "").strip()
        if not permaslug:
            continue
        metadata = catalog.get(permaslug, {})
        slug = str(metadata.get("slug") or permaslug).strip()
        name = str(metadata.get("name") or "").strip() or _humanize_slug(permaslug)
        author = str(
            metadata.get("author")
            or (permaslug.split("/", 1)[0] if "/" in permaslug else "")
        ).strip() or None
        variant = str(row.get("variant") or "").strip()
        item_id = str(row.get("variant_permaslug") or permaslug).strip()
        if variant and variant != "standard":
            item_id = f"{item_id}:{variant}"

        prompt_tokens = _integer(row.get("total_prompt_tokens")) or 0
        completion_tokens = _integer(row.get("total_completion_tokens")) or 0
        total_tokens = prompt_tokens + completion_tokens
        requests = _integer(row.get("count"))
        details = [f"{_format_metric(total_tokens)} tokens"]
        if requests is not None:
            details.append(f"{_format_metric(requests)} 次请求")
        change = _number(row.get("change"))
        if change is not None:
            details.append(f"较上期 {change:+.1f}%")
        tool_calls = _integer(row.get("total_tool_calls"))
        if tool_calls:
            details.append(f"{_format_metric(tool_calls)} 次工具调用")

        url = _model_url(slug)
        items.append(
            ListItem(
                id=item_id,
                title=name,
                author=author,
                desc=" · ".join(details),
                hot=total_tokens or requests,
                timestamp=get_time(row.get("date")),
                url=url,
                mobileUrl=url,
            )
        )
        if len(items) >= _MAX_ITEMS:
            break
    return items


def _performance_items(
    rows: list[dict[str, Any]],
    metric: str,
) -> list[ListItem]:
    field = "p50_latency" if metric == "latency" else "p50_throughput"
    ranked = sorted(
        (row for row in rows if (_number(row.get(field)) or 0) > 0),
        key=lambda row: _number(row.get(field)) or 0,
        reverse=metric != "latency",
    )
    items: list[ListItem] = []
    for row in ranked[:_MAX_ITEMS]:
        identifier = str(row.get("id") or row.get("slug") or "").strip()
        name = str(row.get("name") or "").strip() or _humanize_slug(identifier)
        if not identifier or not name:
            continue
        latency = _number(row.get("p50_latency"))
        throughput = _number(row.get("p50_throughput"))
        details: list[str] = []
        if throughput is not None:
            details.append(f"P50 吞吐 {_format_decimal(throughput)} tok/s")
        if latency is not None:
            details.append(f"P50 延迟 {_format_decimal(latency)} ms")
        provider_key = (
            "best_latency_provider"
            if metric == "latency"
            else "best_throughput_provider"
        )
        provider = str(row.get(provider_key) or "").strip()
        if provider:
            details.append(f"最佳服务商 {provider}")
        request_count = _integer(row.get("request_count"))
        if request_count is not None:
            details.append(f"{_format_metric(request_count)} 次请求")
        url = _model_url(identifier)
        items.append(
            ListItem(
                id=identifier,
                title=name,
                author=str(row.get("author") or "").strip() or None,
                desc=" · ".join(details),
                hot=throughput if metric == "throughput" else None,
                url=url,
                mobileUrl=url,
            )
        )
    return items


def _benchmark_items(rows: object) -> list[ListItem]:
    source_rows = (
        [row for row in rows if isinstance(row, dict)]
        if isinstance(rows, list)
        else []
    )
    ranked = sorted(
        (row for row in source_rows if _number(row.get("score")) is not None),
        key=lambda row: _number(row.get("score")) or 0,
        reverse=True,
    )
    items: list[ListItem] = []
    for row in ranked[:_MAX_ITEMS]:
        identifier = str(
            row.get("uid")
            or row.get("permaslug")
            or row.get("openrouter_slug")
            or ""
        ).strip()
        name = str(row.get("aa_name") or "").strip() or _humanize_slug(identifier)
        if not identifier or not name:
            continue
        model_slug = str(
            row.get("openrouter_slug")
            or row.get("heuristic_openrouter_slug")
            or row.get("permaslug")
            or identifier
        ).strip()
        score = _number(row.get("score"))
        url = _model_url(model_slug)
        items.append(
            ListItem(
                id=identifier,
                title=name,
                author=(
                    model_slug.split("/", 1)[0] if "/" in model_slug else None
                ),
                desc=f"Artificial Analysis 得分：{_format_decimal(score)}",
                hot=score,
                url=url,
                mobileUrl=url,
            )
        )
    return items


def _app_items(rows: object) -> list[ListItem]:
    source_rows = (
        [row for row in rows if isinstance(row, dict)]
        if isinstance(rows, list)
        else []
    )
    ranked = sorted(
        source_rows,
        key=lambda row: _integer(row.get("rank")) or 10**9,
    )
    items: list[ListItem] = []
    for row in ranked[:_MAX_ITEMS]:
        app = row.get("app") if isinstance(row.get("app"), dict) else {}
        app_id = str(row.get("app_id") or app.get("id") or "").strip()
        title = str(app.get("title") or "").strip()
        if not app_id or not title:
            continue
        tokens = _integer(row.get("total_tokens"))
        requests = _integer(row.get("total_requests"))
        details: list[str] = []
        if tokens is not None:
            details.append(f"{_format_metric(tokens)} tokens")
        if requests is not None:
            details.append(f"{_format_metric(requests)} 次请求")
        categories = app.get("categories")
        if isinstance(categories, list):
            labels = [str(value).strip() for value in categories if str(value).strip()]
            if labels:
                details.append(", ".join(labels[:4]))
        url = str(
            app.get("origin_url")
            or app.get("main_url")
            or app.get("source_code_url")
            or SOURCE_LINK
        ).strip()
        items.append(
            ListItem(
                id=app_id,
                title=title,
                desc=" · ".join(details) or str(app.get("description") or "").strip(),
                hot=tokens or requests,
                url=url,
                mobileUrl=url,
            )
        )
    return items


def _model_url(identifier: str) -> str:
    normalized = identifier.strip().strip("/")
    return (
        f"https://openrouter.ai/{quote(normalized, safe='/:')}"
        if normalized
        else SOURCE_LINK
    )


def _humanize_slug(identifier: str) -> str:
    leaf = identifier.rsplit("/", 1)[-1]
    return leaf.replace("-", " ").replace("_", " ").strip().title()


def _number(value: object) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _integer(value: object) -> int | None:
    number = _number(value)
    return int(round(number)) if number is not None else None


def _format_decimal(value: object) -> str:
    number = _number(value)
    if number is None:
        return "暂无"
    return f"{number:,.2f}".rstrip("0").rstrip(".")


def _format_metric(value: object) -> str:
    number = _number(value)
    if number is None:
        return "0"
    absolute = abs(number)
    if absolute >= 1_000_000_000_000:
        return f"{number / 1_000_000_000_000:.2f}万亿"
    if absolute >= 100_000_000:
        return f"{number / 100_000_000:.2f}亿"
    if absolute >= 10_000:
        return f"{number / 10_000:.1f}万"
    return f"{number:,.0f}"
