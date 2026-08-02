from __future__ import annotations

from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "lichess"

type_map: dict[str, str] = {
    "bullet": "子弹棋",
    "blitz": "超快棋",
    "rapid": "快棋",
    "classical": "慢棋",
    "ultraBullet": "极速子弹棋",
    "chess960": "Chess960",
    "crazyhouse": "Crazyhouse",
    "antichess": "Antichess",
    "atomic": "Atomic",
    "horde": "Horde",
    "kingOfTheHill": "King of the Hill",
    "racingKings": "Racing Kings",
    "threeCheck": "Three-check",
}

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "Lichess",
    "description": "Lichess 各棋制全球棋手排行榜",
    "params": {
        "type": {
            "name": "棋制",
            "type": type_map,
        },
    },
    "link": "https://lichess.org/player",
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    type_param = request.query_params.get("type", "bullet")
    selected_type = type_param if type_param in type_map else "bullet"
    list_data = await _get_list(selected_type, no_cache)
    return RouterData(
        **ROUTE_META,
        type=type_map[selected_type],
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


async def _get_list(perf: str, no_cache: bool) -> dict:
    result = await get(
        url=f"https://lichess.org/api/player/top/100/{perf}",
        no_cache=no_cache,
        headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"},
    )
    data: list[ListItem] = []
    for user in (result.data or {}).get("users", []):
        username = str(user.get("username") or "").strip()
        user_id = str(user.get("id") or username).strip()
        perf_data = (user.get("perfs") or {}).get(perf) or {}
        rating = perf_data.get("rating")
        if not username or not user_id or rating is None:
            continue
        title = str(user.get("title") or "").strip()
        progress = perf_data.get("progress")
        desc_parts = []
        if title:
            desc_parts.append(f"头衔：{title}")
        if progress is not None:
            desc_parts.append(f"近期变化：{progress:+d}")
        if user.get("patron") is True:
            desc_parts.append("Lichess Patron")
        url = f"https://lichess.org/@/{username}/perf/{perf}"
        data.append(
            ListItem(
                id=user_id,
                title=username,
                desc=" · ".join(desc_parts) or None,
                hot=rating,
                url=url,
                mobileUrl=url,
            )
        )
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": data,
    }
