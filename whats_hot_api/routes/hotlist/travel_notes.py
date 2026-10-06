"""旅行游记：马蜂窝热门游记（type=站点-栏目）。

迁移自 board_api travel_notes 单元（1 个已完成榜），每次运行 1 个请求：
- 马蜂窝「热门游记」：www.mafengwo.cn 首页游记区块的第一个页签。首页本身对程序请求返回
  202 + ``/C2WF946J0/probe.js``（JS 挑战，board_api 按约定不执行挑战脚本）；游记区块是首页异步
  加载的 pagelet，接口 ``pagelet.mafengwo.cn/note/pagelet/recommendNoteApi?params=<JSON>`` 不经过
  挑战，返回 ``{data: {html: 列表片段}}``。页签与参数的对应取自首页 HTML（Web Archive 2024-06-21
  存档，现在的首页被挑战页挡住看不到）：「热门游记」``data-type="0"``（缺省页签），「最新发表」
  ``data-type="7"``。必需请求头：``Referer`` 为马蜂窝站内地址（不带或换成别的站点都返回 403 空响应）；
  UA 非必需。一页 10 条（片段底部分页"共 9 页 / 100 条"），取第 1 页；前几条是编辑置顶的，照页面顺序输出
- 片段里没有发表时间，timestamp 留空；``hot`` 取片段右下有明确标注的「顶」数（``.tn-ding em``），
  旁边无标注的"数字/数字"（疑似浏览/回复）不取

携程攻略「推荐游记」停更（模块 9 条都是 2020~2021 年的游记，最新一条 2021-03-05 发表，超 12 个月
无更新），不迁（board_api README"不做的榜"）。
"""

from __future__ import annotations

import json
import re
from typing import Any

from bs4 import BeautifulSoup, Tag
from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "travel-notes"

_TYPE_MAP: dict[str, str] = {
    "mafengwo-hot": "马蜂窝 · 热门游记",
}

_DEFAULT_TYPE = "mafengwo-hot"

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "旅行游记",
    "description": "马蜂窝首页「热门游记」（携程攻略「推荐游记」已停更，不提供）。",
    "link": "https://www.mafengwo.cn/",
    "params": {"type": {"name": "站点-栏目", "type": _TYPE_MAP}},
}

_MFW = "https://www.mafengwo.cn"
_MFW_PAGELET = "https://pagelet.mafengwo.cn/note/pagelet/recommendNoteApi"
# type：首页游记页签（0 热门游记、7 最新发表）；objid：目的地筛选（0 = 不筛选）；page：页码；
# ajax=1、retina=1：翻页时页面发的值，retina=1 时图片直接给 src（不带时是懒加载的 data-src），
# 列表与只带 type 时逐条相同（board_api 实测 objid/page/ajax/retina 都非必需，照页面带上）
_MFW_PARAMS: dict[str, dict[str, int]] = {
    "mafengwo-hot": {"type": 0, "objid": 0, "page": 1, "ajax": 1, "retina": 1},
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    board = request.query_params.get("type", _DEFAULT_TYPE)
    if board not in _TYPE_MAP:
        raise ValueError(f"Unknown board '{board}' for route '{ROUTE_NAME}'")
    result = await get(
        url=_MFW_PAGELET,
        params={"params": json.dumps(_MFW_PARAMS[board], separators=(",", ":"))},
        headers={
            # Referer 必需且要是马蜂窝站内地址：不带、或换成 https://example.com/ 都返回 403 空响应
            "Referer": f"{_MFW}/",
            "Accept": "application/json, text/javascript, */*; q=0.01",
        },
        no_cache=no_cache,
        response_type="text",
        cache_key=f"{ROUTE_NAME}:{board}",
    )
    items = _mafengwo_items(result.data)
    return RouterData(
        **ROUTE_META,
        type=_TYPE_MAP[board],
        total=len(items),
        fromCache=result.from_cache,
        updateTime=result.update_time,
        data=items,
    )


def _text(node: Tag | None) -> str:
    return re.sub(r"\s+", " ", node.get_text(" ", strip=True)).strip() if node else ""


def _int(value: str) -> int | None:
    match = re.search(r"\d+", value or "")
    return int(match.group()) if match else None


def _mafengwo_items(payload: Any) -> list[ListItem]:
    text = payload if isinstance(payload, str) else str(payload)
    if "probe.js" in text[:2000]:
        # pagelet 也开始返回与首页相同的 JS 挑战页（202 + probe.js）：按约定不执行挑战脚本
        raise RuntimeError("mafengwo pagelet returned the probe.js JS challenge page, not executing the challenge script")
    try:
        envelope: dict[str, Any] = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"mafengwo pagelet did not return JSON (content changed): {text[:120]!r}") from exc
    data = envelope.get("data") if isinstance(envelope, dict) else None
    fragment = data.get("html") if isinstance(data, dict) else None
    if not isinstance(fragment, str) or not fragment:
        raise RuntimeError("mafengwo pagelet response has no data.html fragment (envelope changed)")
    soup = BeautifulSoup(fragment, "lxml")
    items: list[ListItem] = []
    seen: set[str] = set()
    for div in soup.select("div.tn-item"):
        # 标题在 dt 里指向 /i/<id>.html 的链接（前面可能还有"APP"角标链接，不算）
        a = div.select_one('dt a[href^="/i/"]')
        match = re.search(r"/i/(\d+)\.html", str(a.get("href") or "")) if a is not None else None
        title = _text(a) if a is not None else ""  # 过长的标题原站就截成"..."，照页面
        if match is None or not title or match.group(1) in seen:
            continue
        note_id = match.group(1)
        seen.add(note_id)
        img = div.select_one(".tn-image img")
        cover = str((img.get("src") or img.get("data-rt-src") or "") if img else "").strip()
        url = f"{_MFW}/i/{note_id}.html"
        items.append(
            ListItem(
                id=note_id,
                title=title,
                url=url,
                mobileUrl=url,
                cover=cover if cover.startswith("http") else None,
                author=_text(div.select_one(".tn-user a")) or None,
                desc=_text(div.select_one("dd")) or None,
                hot=_int(_text(div.select_one(".tn-ding em"))),  # 「顶」数；片段里没有发表时间
            )
        )
    if not items:
        raise RuntimeError("travel-notes board returned no items (fragment changed)")
    return items
