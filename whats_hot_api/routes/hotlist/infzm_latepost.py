"""南方周末(www.infzm.com,公开接口,无签名无 cookie)。

board_api 单元 `tmp/board_api/infzm_latepost` 的 1:1 迁移,证据见该目录 README、
`analysis_report.md`、`verify/header_matrix.md` 与 `verify/date_infer_check.md`。原 14 个子榜,
晚点 LatePost 5 个已因上游不可达下线,现存南方周末 9 个:

- 南方周末 9 个:8 个频道/推荐列表走 `GET /contents?term_id=<id>&page=1&format=json`
  (PC 列表页自己的"加载更多"接口,第 1 页与页面服务端渲染逐条相同);今日推荐取 term_id=998
  (PC 首页"推荐"区块、导航"推荐"都是它;term_id=1 是 App 频道,PC 站没有入口)。
  频道 2/3/4/5/7/8 是 App 频道,PC 导航没有入口但 `/contents?term_id=<id>` 每天更新,
  频道名与榜名一致(DEV_PLAN_78 口径)。热门文章走 `GET /hot_contents?format=json`
  (首页右栏 HotContents 组件),按名次

时间口径:`publish_time` 是北京时间到秒。`hot` 留空:接口的分享数 / 评论数不是榜单热度,
页面也不显示为热度。
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any

from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "infzm-latepost"

INFZM = "https://www.infzm.com"

# 子榜键声明序第一个(infzm-recommend)是默认榜。
INFZM_TERMS: dict[str, int] = {
    "infzm-recommend": 998,
    "infzm-news": 2,
    "infzm-opinion": 3,
    "infzm-culture": 4,
    "infzm-life": 5,
    "infzm-people": 7,
    "infzm-photo": 8,
    "infzm-video": 225,
}
INFZM_HOT = "infzm-hot"

type_map: dict[str, str] = {
    "infzm-recommend": "南方周末 · 今日推荐",
    "infzm-news": "南方周末 · 新闻",
    "infzm-opinion": "南方周末 · 观点",
    "infzm-culture": "南方周末 · 文化",
    "infzm-life": "南方周末 · 生活",
    "infzm-people": "南方周末 · 人物",
    "infzm-photo": "南方周末 · 影像",
    "infzm-video": "南方周末 · 视频",
    INFZM_HOT: "南方周末 · 热门文章",
}

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "南方周末",
    "description": "南方周末各频道列表与热门文章",
    "link": "https://www.infzm.com/",
    "params": {"type": {"name": "栏目", "type": type_map}},
}

_JSON_HEADERS = {"Accept": "application/json, text/plain, */*"}

_BEIJING = timezone(timedelta(hours=8))
# 作者字段偶有零宽空格开头(如外部来稿),连同其他不可见字符一起去掉。
_INVISIBLE_RE = re.compile(r"[\u200b-\u200d\u2060\ufeff]")


def _clean(value: Any) -> str:
    """去标签、去不可见字符、收敛空白(board_api _clean 同口径)。"""
    text = _INVISIBLE_RE.sub("", re.sub(r"<[^>]+>", "", str(value or "")))
    return re.sub(r"\s+", " ", text).strip()


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    type_param = request.query_params.get("type", next(iter(type_map)))
    if type_param not in type_map:
        raise ValueError(f"Unknown board '{type_param}' for route '{ROUTE_NAME}'")
    board = await _get_infzm(type_param, no_cache)
    return RouterData(
        **ROUTE_META,
        type=type_map[type_param],
        total=len(board["data"]),
        fromCache=board["from_cache"],
        updateTime=board["update_time"],
        data=board["data"],
        message=board.get("message"),
    )


# ---------------------------------------------------------------- 南方周末


async def _get_infzm(board: str, no_cache: bool) -> dict:
    if board == INFZM_HOT:
        url = f"{INFZM}/hot_contents"
        params: dict[str, str] = {"format": "json"}
        key, message = "hot_contents", "热门文章"
    else:
        term_id = INFZM_TERMS[board]
        url = f"{INFZM}/contents"
        params = {"term_id": str(term_id), "page": "1", "format": "json"}
        key, message = "contents", f"term_id={term_id}"
    result = await get(
        url=url,
        params=params,
        headers=_JSON_HEADERS,
        no_cache=no_cache,
        response_type="json",
        cache_key=f"{ROUTE_NAME}:{board}",
    )
    payload = result.data if isinstance(result.data, dict) else {}
    if payload.get("code") != 200 or not isinstance(payload.get("data"), dict):
        raise RuntimeError(
            f"infzm {board} returned code={payload.get('code')} (business error shell)"
        )
    rows = payload["data"].get(key)
    if not isinstance(rows, list):
        raise RuntimeError(f"infzm {board} response has no '{key}' list (feed changed)")  # noqa: TRY004 - 上游结构漂移是路由级错误
    data = [item for item in (_infzm_item(row) for row in rows if isinstance(row, dict)) if item]
    if not data:
        raise RuntimeError(f"infzm {board} parsed no items")
    term = payload["data"].get("current_term")
    if isinstance(term, dict) and _clean(term.get("title")):
        message = f"{_clean(term['title'])}（{message}）"
    return {"from_cache": result.from_cache, "update_time": result.update_time, "data": data, "message": message}


def _infzm_item(row: dict[str, Any]) -> ListItem | None:
    content_id = row.get("id")
    title = _clean(row.get("subject") or row.get("short_subject"))
    if not content_id or not title:
        return None
    # 页面链接带的 ?source=133&source_1=<term> 是统计参数,文章页用不带参数的形式(tophub 同)。
    url = f"{INFZM}/contents/{content_id}"
    covers = row.get("covers")
    cover = covers[0].get("file_path") if isinstance(covers, list) and covers and isinstance(covers[0], dict) else None
    return ListItem(
        id=content_id,
        title=title,
        url=url,
        mobileUrl=url,
        cover=cover or None,
        author=_clean(row.get("author")) or None,
        desc=_clean(row.get("introtext") or row.get("list_desc")) or None,
        timestamp=get_time(_beijing_seconds(row.get("publish_time"), "%Y-%m-%d %H:%M:%S")),
    )


def _beijing_seconds(value: Any, pattern: str) -> float | None:
    """"YYYY-MM-DD HH:MM:SS"(北京时间,到秒)→ Unix 秒;解析不了返回 None(get_time 会丢弃)。"""
    try:
        moment = datetime.strptime(str(value or "").strip(), pattern).replace(tzinfo=_BEIJING)
    except ValueError:
        return None
    return moment.timestamp()
