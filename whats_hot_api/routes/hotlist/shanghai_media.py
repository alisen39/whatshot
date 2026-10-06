"""上海媒体(上观新闻 / 解放日报,公开静态 JSON,无签名、无 cookie)。

board_api 单元 `tmp/board_api/shanghai_media` 的 1:1 迁移,证据见该目录 README 与
`verify/header_check.txt`、`verify/selfcheck.md`。解放日报(jfdaily.com)与上观新闻
(shobserver.com)是同一套站点(两个域名首页都 302 到 /staticsg/home),文汇报
(whb.cn)旧栏目页停更近 3 年,6 个栏目榜按下线不做(board_api README"不做的榜")。
3 个子榜:

- 上观·最新:首页"更多新闻" `morenewslist.json`,页面会去掉已在"编辑推荐"里的条目
  (index.js 的 isInRecommendList),所以先取 `recommandnewslist.json` 再过滤(2 个请求)
- 上观·编辑推荐:首页"编辑推荐" `recommandnewslist.json`,链接按 newstype 走
  openDetailByNewsType(新闻用 id,专题/直播等用 relatecontentid)
- 解放·今日文章排行:`newsrank.json` 的 `data["24"]`(24 小时页签,第一个)。现行页面把
  显示开关关了(getHotNewsShowSetting="0"、initNewsRank 调用被注释),但数据文件仍在更新,
  按 board_api 证据口径"地址仍在、仍更新、内容与榜名一致"保留;取 jfdaily.com 域名下的
  同一文件(与 shobserver 的逐字相同)

请求头口径(header_check 实测):curl 缺省 UA、不带 UA、不带 Referer 都 200;页面给文件
加的 ?ver=<毫秒> 只是防缓存,不带也 200,因此不带任何自定义头。
`hot` 不映射:静态数据里的评论数 replay 页面注明不可用(前端另行动态取)。
"""

from __future__ import annotations

import re
from typing import Any

from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import RequestResult, get

ROUTE_NAME = "shanghai-media"

_SHOBSERVER = "https://www.shobserver.com"
_JFDAILY = "https://www.jfdaily.com"
_DATA_BASE = "/staticsg/data/"
_DETAIL_BASE = "/staticsg/res/html/web/"
# config.js 的 IMG_BASE_URL + 页面脚本的 "news/690_390/" 前缀拼接
_IMG_BASE = "https://images.shobserver.cn/news/690_390/"
_HOME_SID = 11  # config.js PAGE_CODE.HOME
_RANK_HOUR = "24"  # right.html 第一个页签 data-hour="24"
# openDetailByNewsType:newstype -> (详情页, 是否用 relatecontentid 作为稿件号)
_DETAIL_BY_TYPE: dict[str, tuple[str, bool]] = {
    "0": ("newsDetail.html", False),
    "5": ("newsDetail.html", False),
    "6": ("newsDetail.html", False),
    "1": ("specialDetail.html", True),
    "2": ("graphicDetail.html", True),
    "3": ("livingDetail.html", True),
    "7": ("timeline.html", True),
}

# 声明序第一个是默认榜(上观·最新,与 board_api DEFAULT_TYPE 一致)。
type_map: dict[str, str] = {
    "shobserver-latest": "上观新闻·最新",
    "shobserver-recommend": "上观新闻·编辑推荐",
    "jfdaily-rank-24h": "解放日报·今日文章排行（24小时）",
}

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "上海媒体（上观新闻 / 解放日报）",
    "description": (
        "上观新闻首页的编辑推荐与更多新闻（最新），以及解放日报（jfdaily.com 同站）"
        "的 24 小时热门文章排行"
    ),
    "link": _SHOBSERVER + "/staticsg/home",
    "params": {
        "type": {
            "name": "栏目",
            "type": type_map,
        },
    },
}

_RECOMMEND_URL = f"{_SHOBSERVER}{_DATA_BASE}web/home/recommandnewslist.json"
_MORENEWS_URL = f"{_SHOBSERVER}{_DATA_BASE}web/home/morenewslist.json"
_RANK_URL = f"{_JFDAILY}{_DATA_BASE}web/common/newsrank.json"


def _clean(value: Any) -> str:
    """去标签并收敛空白(静态 JSON 个别摘要里带零散换行)。"""
    text = re.sub(r"<[^>]+>", "", str(value or ""))
    return re.sub(r"\s+", " ", text).strip()


async def _fetch_static_rows(
    url: str, board: str, no_cache: bool
) -> tuple[RequestResult, list[dict[str, Any]]]:
    """三个静态 JSON 共用的壳:data 必须是列表,否则视为错误页/改版,报错不降级。"""
    result = await get(url=url, no_cache=no_cache, response_type="json")
    payload = result.data
    # 壳结构错(错误页 / 改版)直接报错,不降级为空榜
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise RuntimeError(  # noqa: TRY004 - 上游结构漂移是路由级错误,不是调用方类型错
            f"Shanghai media '{board}' payload has no data list: {str(payload)[:200]}"
        )
    data = payload["data"]
    return result, [row for row in data if isinstance(row, dict)]


def _item(row: dict[str, Any], url: str | None) -> ListItem | None:
    """公共字段映射;没有稿件号、标题或链接的行按页面行为跳过。"""
    item_id = str(row.get("id") or "").strip()
    title = _clean(row.get("title"))
    if not item_id or not title or not url:
        return None
    pic = str(row.get("picurl") or "").strip()
    return ListItem(
        id=item_id,
        title=title,
        url=url,
        mobileUrl=url,
        cover=f"{_IMG_BASE}{pic}" if pic else None,
        author=_clean(row.get("subsectionname")) or None,
        desc=_clean(row.get("summary")) or None,
        # publishtime 是毫秒,get_time 原样保留毫秒
        timestamp=get_time(row.get("publishtime")),
    )


def _recommend_url(row: dict[str, Any]) -> str | None:
    page, use_related = _DETAIL_BY_TYPE.get(str(row.get("newstype") or "0"), (None, False))
    if page is None:
        return None
    target = row.get("relatecontentid") if use_related else row.get("id")
    target = str(target or "").strip()
    if not target or target == "0":
        return None
    return f"{_SHOBSERVER}{_DETAIL_BASE}{page}?id={target}&sid={_HOME_SID}"


async def _fetch_recommend(no_cache: bool) -> tuple[RequestResult, list[ListItem]]:
    result, rows = await _fetch_static_rows(_RECOMMEND_URL, "shobserver-recommend", no_cache)
    items = [
        item
        for row in rows
        if (item := _item(row, _recommend_url(row)))
    ]
    return result, items


async def _fetch_latest(no_cache: bool) -> tuple[RequestResult, list[ListItem]]:
    # 页面口径:先取"编辑推荐",再取"更多新闻"并去掉重叠条目(index.js isInRecommendList)
    _, rec_rows = await _fetch_static_rows(_RECOMMEND_URL, "shobserver-latest", no_cache)
    recommend_ids = {str(row.get("id")) for row in rec_rows}
    result, rows = await _fetch_static_rows(_MORENEWS_URL, "shobserver-latest", no_cache)
    items: list[ListItem] = []
    for row in rows:
        if str(row.get("id")) in recommend_ids:
            continue
        url = f"{_SHOBSERVER}{_DETAIL_BASE}newsDetail.html?id={row.get('id')}&sid={_HOME_SID}"
        if item := _item(row, url):
            items.append(item)
    return result, items


async def _fetch_rank(no_cache: bool) -> tuple[RequestResult, list[ListItem]]:
    result = await get(url=_RANK_URL, no_cache=no_cache, response_type="json")
    payload = result.data
    data = payload.get("data") if isinstance(payload, dict) else None
    rows = data.get(_RANK_HOUR) if isinstance(data, dict) else None
    if not isinstance(payload, dict) or not isinstance(rows, list):
        raise RuntimeError(  # noqa: TRY004 - 上游结构漂移是路由级错误,不是调用方类型错
            f"Shanghai media 'jfdaily-rank-24h' payload has no {_RANK_HOUR}-hour list: "
            f"{str(payload)[:200]}"
        )
    items = [
        item
        for row in rows
        if isinstance(row, dict)
        and (
            item := _item(
                row,
                f"{_JFDAILY}{_DETAIL_BASE}newsDetail.html?id={row.get('id')}",
            )
        )
    ]
    return result, items


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    selected = request.query_params.get("type", next(iter(type_map)))
    if selected not in type_map:
        raise ValueError(f"Unknown board '{selected}' for route '{ROUTE_NAME}'")

    if selected == "shobserver-latest":
        result, data = await _fetch_latest(no_cache)
    elif selected == "shobserver-recommend":
        result, data = await _fetch_recommend(no_cache)
    else:
        result, data = await _fetch_rank(no_cache)

    if not data:
        # 错误页 / 空解析不静默降级为空榜
        raise RuntimeError(f"Shanghai media board '{selected}' parsed no items")
    return RouterData(
        **ROUTE_META,
        type=type_map[selected],
        total=len(data),
        fromCache=result.from_cache,
        updateTime=result.update_time,
        data=data,
    )
