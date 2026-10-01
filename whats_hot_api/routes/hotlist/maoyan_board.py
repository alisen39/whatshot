"""猫眼电影榜单（maoyan-board）：www.maoyan.com/board/<id> 服务端渲染榜单，单路由 type 区分。

移植自 board_api/maoyan_board（2026-09-30 已验证，verify/ 下有自验、页面 vs 输出核对与推翻性验证）：
- 数据源是 PC 榜单页 HTML（dl.board-wrapper 里每个 dd 一部影片），没有 JSON 接口；
  每榜 1 个请求。北美票房榜 /board/2 的 update-time 停在 2018-07-16，停更不迁
- 条数口径：只取页面第 1 页 10 条（项目统一口径"条数取原站页面的一页"）；
  榜单全长最受期待榜 50 名、TOP100 榜 100 名，分页参数 ?offset=10、20…（每页 10 条），
  需要全榜时由调用方翻页；分页器页数写进 message
- 国内票房榜的票房、最受期待榜的想看数用 stonefont 动态字体加密且字体文件会换，不破解，
  hot 留空；评分（仅口碑榜、TOP100 有）、片名、主演、上映时间是明文

反爬口径（verify/probe.log）：
- User-Agent 必须是浏览器 UA（python-httpx 缺省 UA 返回 403）
- 服务端第一跳 302 回原地址并种 uuid cookie，不保存 cookie 会 302 死循环；
  共享 httpx 客户端自动保存 cookie 并跟随跳转，首次请求即完成该握手
- 频繁请求可能跳 verify.maoyan.com 验证页（美团滑块）：页面里找不到 board-wrapper 就报错，
  不重试、不绕过
"""

from __future__ import annotations

import html
import re
from datetime import datetime

from bs4 import BeautifulSoup
from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.get_time import CHINA_TZ, get_time
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "maoyan-board"

_BASE = "https://www.maoyan.com"

# 子榜 -> (榜单页 ID, 中文名)。榜单 ID 是 /board/<id> 的路径，取自页面顶部导航；
# 声明序第一个（praise）是默认榜。
_BOARDS: dict[str, tuple[int, str]] = {
    "praise": (7, "热映口碑榜"),
    "expected": (6, "最受期待榜"),
    "box-office": (1, "国内票房榜"),
    "top100": (4, "TOP100榜"),
}

type_map: dict[str, str] = {key: label for key, (_, label) in _BOARDS.items()}

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "猫眼电影",
    "description": "猫眼电影榜单：热映口碑榜、最受期待榜、国内票房榜、TOP100榜",
    "link": "https://www.maoyan.com/board",
    "params": {
        "type": {
            "name": "榜单",
            "type": type_map,
        },
    },
}

_HEADERS = {
    # probe.log：python-httpx 缺省 UA 被 403，必须带浏览器 UA；没有为避开验证改 UA
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/145.0.0.0 Safari/537.36"
    ),
}

_PAGE_SIZE = 10  # 每页 10 部，分页参数 offset 以 10 递增（只取第 1 页）


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    type_param = request.query_params.get("type", "praise")
    if type_param not in _BOARDS:
        raise ValueError(f"Unknown board '{type_param}' for route '{ROUTE_NAME}'")
    board_id, label = _BOARDS[type_param]
    url = f"{_BASE}/board/{board_id}"
    result = await get(url=url, headers=_HEADERS, no_cache=no_cache, response_type="text")
    page = str(result.data)
    items, notes = _parse_board(page)
    if not items:
        # 验证页（verify.maoyan.com 美团滑块）或页面改版都解析不到 board-wrapper
        raise RuntimeError(f"maoyan-board {label} ({url}) has no board-wrapper rows (verify page or markup changed)")
    return RouterData(
        **ROUTE_META,
        type=label,
        total=len(items),
        fromCache=result.from_cache,
        updateTime=result.update_time,
        data=items,
        message="；".join(notes) or None,
    )


def _text(fragment: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", fragment))).strip()


def _release_timestamp(release_text: str) -> int | None:
    """'上映时间：2026-08-28' / '上映时间：2010-02-13(德国)' -> 当天北京时间 0 点（毫秒）；
    只有年份（如"上映时间：2026"）时留空。"""
    match = re.search(r"(\d{4})-(\d{2})-(\d{2})", release_text)
    if not match:
        return None
    seconds = int(
        datetime(
            int(match.group(1)), int(match.group(2)), int(match.group(3)), tzinfo=CHINA_TZ
        ).timestamp()
    )
    # 1970 年以前的上映日期（负数时间戳）留空
    return get_time(seconds) if seconds > 0 else None


def _parse_board(page: str) -> tuple[list[ListItem], list[str]]:
    """解析榜单页，返回 (条目, message 备注)。名次不连续时写进备注，不静默。"""
    soup = BeautifulSoup(page, "lxml")
    wrapper = soup.select_one("dl.board-wrapper")
    if wrapper is None:
        return [], []
    items: list[ListItem] = []
    seen: set[str] = set()
    ranks: list[int] = []
    for dd in wrapper.select("dd"):
        rank_tag = dd.select_one("i.board-index")
        name_tag = dd.select_one("p.name a")
        if rank_tag is None or name_tag is None:
            continue
        # 名次先记下（含被去重跳过的行），用于核对页面名次是否连续
        ranks.append(int(rank_tag.get_text(strip=True) or 0))
        mid_match = re.search(r"/films/(\d+)", name_tag.get("href") or "")
        title = _text(name_tag.get_text())
        if not mid_match or not title or mid_match.group(1) in seen:
            continue
        mid = mid_match.group(1)
        seen.add(mid)
        img = dd.select_one("img.board-img")
        star = dd.select_one("p.star")
        release = dd.select_one("p.releasetime")
        score = dd.select_one("p.score")
        integer = score.select_one("i.integer") if score else None
        fraction = score.select_one("i.fraction") if score else None
        release_text = _text(release.get_text()) if release else ""
        parts = [
            f"评分 {_text(integer.get_text())}{_text(fraction.get_text())}" if integer and fraction else None,
            _text(star.get_text()) if star else None,
            release_text or None,
        ]
        cover = html.unescape(img.get("data-src") or "").strip() if img else ""
        items.append(
            ListItem(
                id=mid,
                title=title,
                url=f"{_BASE}/films/{mid}",
                # m.maoyan.com/movie/<id> 302 到 asgard 页（evidence/08_mobile_movie_1297）
                mobileUrl=f"https://m.maoyan.com/asgard/movie/{mid}",
                cover=cover or None,
                desc=" · ".join(part for part in parts if part) or None,
                timestamp=_release_timestamp(release_text),
            )
        )
    notes: list[str] = []
    update = soup.select_one("p.update-time")
    if update:
        notes.append(f"榜单日期 {_text(update.get_text())}")
    pager = soup.select_one("ul.list-pager")
    offsets = sorted({int(m) for m in re.findall(r'href="\?offset=(\d+)"', str(pager))}) if pager else []
    if offsets:
        # 分页器最后一页 offset；需要全榜时调用方按 ?offset=10、20… 翻页
        notes.append(f"只取第 1 页；页面分页器共 {max(offsets) // _PAGE_SIZE + 1} 页（?offset={_PAGE_SIZE}…{max(offsets)}）")
    else:
        notes.append("只取第 1 页（页面没有分页器）")
    if ranks and ranks != list(range(1, len(ranks) + 1)):
        notes.append(f"页面名次不连续：{ranks}")
    return items, notes
