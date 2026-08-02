from __future__ import annotations

from urllib.parse import quote

from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "homebrew"
type_map = {
    "formula-30d": "Formula 30 天", "formula-90d": "Formula 90 天",
    "formula-365d": "Formula 365 天", "cask-30d": "Cask 30 天",
    "cask-90d": "Cask 90 天", "cask-365d": "Cask 365 天",
}
ROUTE_META = {
    "name": ROUTE_NAME, "title": "Homebrew",
    "description": "Homebrew 官方安装量排行榜",
    "params": {"type": {"name": "包类型与时间范围", "type": type_map}},
    "link": "https://formulae.brew.sh/analytics/",
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    requested = request.query_params.get("type", "formula-30d")
    selected = requested if requested in type_map else "formula-30d"
    result = await _get_list(selected, no_cache)
    return RouterData(
        **ROUTE_META, type=type_map[selected], total=len(result["data"]),
        fromCache=result["from_cache"], updateTime=result["update_time"],
        data=result["data"],
    )


async def _get_list(board_type: str, no_cache: bool) -> dict:
    package_type, window = board_type.split("-", 1)
    analytics_type = "cask-install" if package_type == "cask" else "install"
    url = f"https://formulae.brew.sh/api/analytics/{analytics_type}/{window}.json"
    result = await get(
        url=url, no_cache=no_cache, response_type="json",
        headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"},
    )
    data = []
    for row in ((result.data or {}).get("items") or [])[:50]:
        token = str(row.get(package_type) or "").strip()
        if not token:
            continue
        item_url = f"https://formulae.brew.sh/{package_type}/{quote(token, safe='@+-._')}"
        percent = row.get("percent")
        data.append(ListItem(
            id=f"{package_type}:{token}", title=token,
            desc=f"占比：{percent}%" if percent is not None else None,
            hot=_install_count(row.get("count")), url=item_url, mobileUrl=item_url,
        ))
    return {"from_cache": result.from_cache, "update_time": result.update_time, "data": data}


def _install_count(value: object) -> int | None:
    try:
        return int(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None
