from __future__ import annotations

from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "gov-cn-news"

# 中国政府网"要闻"列表页(www.gov.cn/yaowen/liebiao/)是空壳:条目由前端 ajax 取同目录的
# YAOWENLIEBIAO.json 渲染(页面脚本 getFYDataFn() 按 sPageSize=20 切片,文件顺序即页面顺序)。
# tophub 该节点解析静态 HTML,只拿到页脚"国务院部门网站"等链接,是坏节点——本路由解析
# 页面实际加载的 JSON(board_api 教训:解析照证据,不照 tophub 历史重合)。
type_map = {
    "hot": "要闻最新",
}

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "中国政府网",
    "description": "中国政府网要闻最新列表(列表页第 1 页)",
    "link": "https://www.gov.cn/yaowen/liebiao/",
    "params": {
        "type": {
            "name": "榜单",
            "type": type_map,
        },
    },
}

_LIST_URL = "https://www.gov.cn/yaowen/liebiao/YAOWENLIEBIAO.json"
_PAGE_SIZE = 20  # 列表页 sPageSize


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    board_type = request.query_params.get("type", "hot")
    if board_type not in type_map:
        raise ValueError(f"Unknown board '{board_type}' for route '{ROUTE_NAME}'")
    # 公开 JSON,无签名无 cookie;实测 curl 默认 UA/无 UA/httpx 默认头均 400 行,
    # 不需要带任何自定义头(header_matrix.jsonl)
    result = await get(url=_LIST_URL, no_cache=no_cache)
    rows = result.data
    if not isinstance(rows, list) or not rows:
        raise RuntimeError(
            f"gov.cn news feed returned no rows (got {type(rows).__name__})"
        )
    items = _items(rows[:_PAGE_SIZE])
    if not items:
        raise RuntimeError("gov.cn news feed produced no parsable items")
    return RouterData(
        **ROUTE_META,
        type=type_map[board_type],
        total=len(items),
        fromCache=result.from_cache,
        updateTime=result.update_time,
        data=items,
    )


def _items(rows: list) -> list[ListItem]:
    items: list[ListItem] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        title = " ".join(str(row.get("TITLE") or "").split())
        url = str(row.get("URL") or "").strip()
        if not title or not url.startswith(("http://", "https://")):
            continue
        # DOCRELPUBTIME 只有日期(YYYY-MM-DD):get_time 按北京时间当天 00:00 归一化为毫秒,
        # 精度到日,同日条目时间相同,顺序以文件顺序为准
        items.append(
            ListItem(
                id=url,  # URL 全文唯一,直接作稳定 id
                title=title,
                url=url,
                mobileUrl=url,
                desc=str(row.get("SUB_TITLE") or "").strip() or None,
                timestamp=get_time(row.get("DOCRELPUBTIME")),
            )
        )
    return items
