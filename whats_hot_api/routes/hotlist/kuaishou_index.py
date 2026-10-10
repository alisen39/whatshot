from __future__ import annotations

from urllib.parse import quote

from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.http_client import get, post

ROUTE_NAME = "kuaishou-index"

# 快手指数"快手榜单"页(index.e.kuaishou.com)背后的接口;whatshot 的 kuaishou 路由
# 取的是 www.kuaishou.com 首页热榜,同一时刻只有部分重合,是另一个来源。
_BOARDS: dict[str, tuple[str, str, object]] = {
    # board: (标签, endpoint, 参数)
    "hot": ("热榜", "hot-rank", 1),
    "entertainment": ("文娱榜", "hot-rank", 2),
    "society": ("社会榜", "hot-rank", 3),
    "useful": ("有用榜", "hot-rank", 5),
    "challenge": ("挑战榜", "hot-rank", -1),
    "search-rising": ("搜索飙升榜", "search-rank", 100),
    "drama-must": ("短剧必看榜", "tube-rank", "mustRank"),
}

type_map: dict[str, str] = {key: label for key, (label, _, _) in _BOARDS.items()}

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "快手指数",
    "description": "快手指数的快手榜单：热榜分类、搜索飙升榜、短剧榜。",
    "link": "https://index.e.kuaishou.com/rank",
    "params": {
        "type": {
            "name": "榜单",
            "type": type_map,
        },
    },
}

_API = "https://index.e.kuaishou.com/rest/index/list/"
_HEADERS = {
    "Referer": "https://index.e.kuaishou.com/rank",
    "Origin": "https://index.e.kuaishou.com",
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    type_param = request.query_params.get("type", "hot")
    if type_param not in _BOARDS:
        raise ValueError(f"Unknown board '{type_param}' for route '{ROUTE_NAME}'")
    label, endpoint, arg = _BOARDS[type_param]
    list_data = await _get_list(label, endpoint, arg, no_cache)
    return RouterData(
        **ROUTE_META,
        type=label,
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


async def _get_list(label: str, endpoint: str, arg: object, no_cache: bool) -> dict:
    url = f"{_API}{endpoint}"
    if endpoint == "hot-rank":
        # rankType 只能放 JSON 体里;放 URL 参数返回 -101,写错返回 100001"参数不合法"
        result = await post(url=url, body={"rankType": arg}, headers=_HEADERS, no_cache=no_cache)
    else:
        result = await get(url=url, headers=_HEADERS, no_cache=no_cache)
    payload = result.data if isinstance(result.data, dict) else {}
    if str(payload.get("code")) != "200":
        raise RuntimeError(
            f"Kuaishou index {endpoint} returned code={payload.get('code')} message={payload.get('message')}"
        )
    data = payload.get("data")
    if endpoint == "tube-rank":
        rows = data.get(str(arg)) if isinstance(data, dict) else None
        if not isinstance(rows, list):
            raise RuntimeError(f"Kuaishou index tube-rank response has no '{arg}' list (feed changed)")
        items = _tube_items(rows)
    else:
        if not isinstance(data, list):
            raise RuntimeError(f"Kuaishou index {endpoint} response data is not a list (feed changed)")
        items = _keyword_items(data, int(arg))  # type: ignore[arg-type]
    if not items:
        raise RuntimeError(f"Kuaishou index {label} returned no items")
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": items,
    }


def _https(url: str | None) -> str | None:
    return url.replace("http://", "https://", 1) if url else None


def _keyword_items(rows: list[dict], rank_type: int) -> list[ListItem]:
    items = []
    for position, row in enumerate(rows, start=1):
        keyword = (row.get("keyword") or "").strip()
        if not keyword:
            continue
        # 快手指数的热点详情页。rankType 必须是该词所在榜的值:写成 1 时,不在主榜的词
        # 显示"暂无该热点详情"(推翻性验证发现,有用榜的词 rankType=1 返回空、=5 有数据)
        url = f"https://index.e.kuaishou.com/rank/hotDetail?keyword={quote(keyword)}&rankType={rank_type}"
        items.append(
            ListItem(
                id=keyword,
                title=keyword,
                url=url,
                mobileUrl=url,
                hot=row.get("hotValue"),
                hotLabel="热度",
                sourceRank=_positive_int(row.get("rank")) or position,
                cover=_https(row.get("poster")),
            )
        )
    return items


def _tube_items(rows: list[dict]) -> list[ListItem]:
    items = []
    for position, row in enumerate(rows, start=1):
        url = row.get("url") or ""
        if not url.startswith("http"):
            raise RuntimeError(f"Kuaishou drama item missing video link: {row.get('tubeName')!r}")
        items.append(
            ListItem(
                id=url.split("/short-video/")[-1].split("?")[0] or row.get("tubeName", ""),
                title=row.get("tubeName") or "",
                url=url,
                mobileUrl=url,
                hot=row.get("popularityValue"),
                hotLabel="热度",
                badges=[{"text": row["channelName"]}] if str(row.get("channelName") or "").strip() else [],
                sourceRank=position,
                cover=_https(row.get("poster")),
                desc=row.get("channelName") or None,
                timestamp=row.get("onlineTime"),
            )
        )
    return items


def _positive_int(value: object) -> int | None:
    try:
        number = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None
