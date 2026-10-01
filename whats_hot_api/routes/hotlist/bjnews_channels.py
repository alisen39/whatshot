"""新京报栏目(www.bjnews.com.cn,公开、无签名、无 cookie,不需要任何请求头)。

board_api 单元 `tmp/board_api/bjnews_channels` 的 1:1 迁移,证据见该目录 README 与
`verify/header_check.txt`、`verify/timestamp_check.md`。10 个子榜:

- 7 个频道(时事/政事儿/北京/国际/娱乐/教育/科技):电脑版频道页服务端渲染的瀑布流
  第 1 页(`#waterfall-container .pin_demo`,20 条);教育前 4 条、科技第 1 条是置顶
  H5 专题(链接指向 m 站 h5special 页),照原站页面顺序保留
- 首页推荐 / 排行 / 热评:电脑版首页服务端渲染的三个区块,靠 HTML 注释定位
  (`<!-- 推荐s -->…<!-- 推荐e -->` 等);推荐是瀑布流(15 条),排行、热评是右栏
  `ul.list1`(各 10 条,排行带热度)
- 发布时间:列表页不显示,uuid 前 10 位是稿件创建时间(比发布时间早 0 分钟 ~ 4 天),
  不能用。7 个频道与首页推荐用手机版数据接口 `m.bjnews.com.cn/bwnew/index-tj`
  (与电脑版频道页第 1 页同序,`publish_time` 与详情页一致)按 uuid 对上;
  排行、热评没有对应接口;接口失败或串频道(偶尔返回别的频道的缓存,按 uuid 对不
  上、不会配错)时只是不补时间,条目照常输出,message 写明条数
- 链接照原站页面:`detail/{uuid}.html`(m 站接口的 `detail-{uuid}.html` 写法也能打开)
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag
from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "bjnews-channels"

WWW = "https://www.bjnews.com.cn/"
M_API = "https://m.bjnews.com.cn/bwnew/index-tj"

# 子榜键 -> (中文名, 取数方式, 频道路径或首页区块名, 手机版接口的 channel_id)。
# channel_id 只用来补发布时间,取自手机版频道页 #cur_channel_id;首页推荐对应手机版
# 首页推荐(channel_id 为空串);None 表示没有对应接口。声明序第一个是默认榜。
BOARDS: dict[str, tuple[str, str, str, str | None]] = {
    "home-recommend": ("首页推荐", "home", "推荐", ""),
    "ranking": ("排行", "home", "排行", None),
    "hot-comment": ("热评", "home", "热评", None),
    "news": ("时事", "channel", "news", "101"),
    "zhengshi": ("政事儿", "channel", "zhengshi", "10016"),
    "beijing": ("北京", "channel", "beijing", "4"),
    "guoji": ("国际", "channel", "guoji", "10008"),
    "entertainment": ("娱乐", "channel", "entertainment", "8"),
    "education": ("教育", "channel", "education", "12"),
    "technology": ("科技", "channel", "technology", "16"),
}

type_map: dict[str, str] = {key: board[0] for key, board in BOARDS.items()}

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "新京报",
    "description": (
        "新京报网:首页推荐、排行、热评,以及时事、政事儿、北京、国际、娱乐、教育、科技频道"
    ),
    "link": WWW,
    "params": {"type": {"name": "栏目", "type": type_map}},
}

_DEFAULT_TYPE = next(iter(type_map))
_BEIJING = timezone(timedelta(hours=8))
_UUID_RE = re.compile(r"(\d{16})")
# 首页 HTML 注释标出的区块边界
_HOME_BLOCKS = {
    "推荐": ("<!-- 推荐s -->", "<!-- 推荐e -->"),
    "排行": ("<!-- 排行s -->", "<!-- 排行e -->"),
    "热评": ("<!-- 热评s -->", "<!-- 热评e -->"),
}
_COUNT_RE = re.compile(r"([\d.]+)\s*(万|亿)?")
_COUNT_UNIT = {"万": 10_000, "亿": 100_000_000}


def _clean(node: Tag | None) -> str:
    """原站标题、导语开头偶尔带零宽空格(U+200B),\\s 不含它,单独去掉首尾的。"""
    if node is None:
        return ""
    text = re.sub(r"\s+", " ", node.get_text(" ", strip=True)).strip()
    return text.strip("\u200b\ufeff").strip()


def _count(text: str) -> int | None:
    """页面上的阅读量 / 排行热度:"5318"、"1.3万"、"21.1万";认不出的(如热评的"20小时前")为空。"""
    match = _COUNT_RE.fullmatch(text.strip())
    if not match:
        return None
    try:
        value = float(match.group(1))
    except ValueError:
        return None
    return round(value * _COUNT_UNIT.get(match.group(2) or "", 1))


def _cover(node: Tag | None) -> str | None:
    img = node.select_one("img") if node is not None else None
    src = str(img.get("src") or "").strip() if img is not None else ""
    return src if src.startswith(("http://", "https://")) else None


def _item_id(url: str) -> str:
    match = _UUID_RE.search(url)
    return match.group(1) if match else url


def _parse_pins(box: BeautifulSoup | Tag) -> list[ListItem]:
    """瀑布流卡片(频道页 #waterfall-container 与首页"推荐"):.pin_tit 标题(去掉
    "专题"角标)、第一个链接、封面图、.pin_tips a.noPadd 导语(去掉"[全文]")、
    .bom .see 阅读量。卡片下的"相关推荐"子链接不是列表条目,不拆。"""
    items: list[ListItem] = []
    seen: set[str] = set()
    for pin in box.select(".pin_demo"):
        anchor = pin.select_one("a[href]")
        tit = pin.select_one(".pin_tit")
        if not isinstance(anchor, Tag) or not isinstance(tit, Tag):
            continue
        for badge in tit.select(".zt_tit"):
            badge.decompose()
        url = urljoin(WWW, str(anchor.get("href") or "").strip())
        title = _clean(tit)
        if not title or url in seen:
            continue
        seen.add(url)
        desc_a = pin.select_one(".pin_tips a.noPadd")
        if isinstance(desc_a, Tag):
            for more in desc_a.select("i"):
                more.decompose()
        see = pin.select_one(".bom .see")
        items.append(
            ListItem(
                id=_item_id(url),
                title=title,
                url=url,
                mobileUrl=url,
                cover=_cover(pin.select_one(".imgBor, .index-overflow-zt, .index_xiaoSp")),
                desc=_clean(desc_a) if isinstance(desc_a, Tag) else None,
                hot=_count(_clean(see)) if isinstance(see, Tag) else None,
            )
        )
    return items


def _parse_side_list(box: BeautifulSoup) -> list[ListItem]:
    """首页右栏"排行 / 热评":ul.list1 li,a.link 标题(去掉 span.num 名次)、.img 封面;
    排行的 span.com 是热度,热评的 span.com 是相对时间(解析为空,不映射)。"""
    items: list[ListItem] = []
    seen: set[str] = set()
    for li in box.select("ul.list1 li"):
        anchor = li.select_one("a.link[href]")
        if not isinstance(anchor, Tag):
            continue
        for num in anchor.select(".num"):
            num.decompose()
        url = urljoin(WWW, str(anchor.get("href") or "").strip())
        title = _clean(anchor)
        if not title or url in seen:
            continue
        seen.add(url)
        com = li.select_one(".tips .com")
        items.append(
            ListItem(
                id=_item_id(url),
                title=title,
                url=url,
                mobileUrl=url,
                cover=_cover(li.select_one(".img")),
                hot=_count(_clean(com)) if isinstance(com, Tag) else None,
            )
        )
    return items


def _parse_home(html: str, block: str) -> list[ListItem]:
    start, end = _HOME_BLOCKS[block]
    i, j = html.find(start), html.find(end)
    if i < 0 or j < i:
        raise RuntimeError(f"bjnews home page has no '{block}' block (comment {start} missing)")
    soup = BeautifulSoup(html[i:j], "lxml")
    return _parse_pins(soup) if block == "推荐" else _parse_side_list(soup)


def _parse_channel(html: str) -> list[ListItem]:
    box = BeautifulSoup(html, "lxml").select_one("#waterfall-container")
    if not isinstance(box, Tag):
        raise RuntimeError("bjnews channel page has no #waterfall-container (page structure changed)")  # noqa: TRY004 - 上游结构漂移是路由级错误
    return _parse_pins(box)


def _extract_publish_times(payload: Any) -> dict[str, int]:
    """m 接口 JSON -> uuid -> 毫秒时间戳;publish_time 是北京时间的"%Y-%m-%d %H:%M:%S"。
    接口偶尔返回别的频道的缓存(串频道),按 uuid 对时间只会对不上、不会配错。"""
    rows = payload.get("data") if isinstance(payload, dict) else None
    times: dict[str, int] = {}
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        try:
            dt = datetime.strptime(str(row.get("publish_time") or ""), "%Y-%m-%d %H:%M:%S").replace(tzinfo=_BEIJING)
        except ValueError:
            continue
        seconds = int(dt.timestamp())
        if (ms := get_time(seconds)) is not None:
            times[str(row.get("uuid"))] = ms
    return times


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    board_type = request.query_params.get("type", _DEFAULT_TYPE)
    if board_type not in type_map:
        raise ValueError(f"Unknown board '{board_type}' for route '{ROUTE_NAME}'")
    _name, kind, arg, channel_id = BOARDS[board_type]
    url = WWW + arg if kind == "channel" else WWW

    result = await get(url=url, no_cache=no_cache, response_type="text")
    html = result.data if isinstance(result.data, str) else ""
    items = _parse_home(html, arg) if kind == "home" else _parse_channel(html)
    if not items:
        # 错误页 / 空解析不静默降级为空榜
        raise RuntimeError(f"bjnews board '{board_type}' parsed no items: {url}")

    message: str | None = None
    if channel_id is not None:
        times: dict[str, int] = {}
        try:
            api = await get(
                url=f"{M_API}?page=1&size=20&channel_id={channel_id}&wz_id=1",
                no_cache=no_cache,
                response_type="json",
            )
            times = _extract_publish_times(api.data)
        except Exception:  # noqa: BLE001 - 接口失败只是不补时间(证据口径)
            times = {}
        items = [item.model_copy(update={"timestamp": times[item.id]}) if item.id in times else item for item in items]
        missing = sum(1 for item in items if item.timestamp is None)
        if missing:
            message = f"{missing} 条没有对上手机版数据接口的发布时间,timestamp 留空"

    return RouterData(
        **ROUTE_META,
        type=type_map[board_type],
        total=len(items),
        fromCache=result.from_cache,
        updateTime=result.update_time,
        data=items,
        message=message,
    )
