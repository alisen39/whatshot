"""汽车媒体榜(auto-media):汽车之家、汽车之家论坛、懂车帝、易车。

数据源与口径照 board_api 证据 tmp/board_api/auto_media(2026-09-30 冷启动留档,
纯 HTTP 直连,不需要登录、cookie、签名;curl 缺省 UA 也 200,统一带浏览器 UA;
tophub 9 个榜里懂车帝"文章排行榜""视频排行榜"原站已下线,不做):
- 汽车之家 文章 / 视频排行榜(首页"文章排行榜 三日内最火文章排行""视频排行榜"的完整榜单
  /cars/hotrank/3、/2):页面是 Next.js 客户端渲染,页面脚本调
  content.api.autohome.com.cn/pc/rank/v2/list?count=30&ranktype=3|2,count=30 必需(不带只回 15 条);
  hot 取 subTitle(页面在 ranktype 2、3 显示的"指数",如"494.9万"),不取页面不显示的 hotScore。
- 汽车之家论坛 首页侧栏"论坛热帖榜"(服务端渲染 10 条,.rank-group 区块按榜名定位);
  论坛精选日报 /jingxuan 与美人生活秀 /jingxuan/292 的列表 ul.content > li(第 1 页 40 条),
  顶部 5 张轮播(ul.js-show-bd,各分类共用的推荐位)不输出。
- 懂车帝 实时热搜榜:PC 搜索结果页侧栏"热搜榜"(_cus_fixed_pc_hot_search)的接口
  /motor/pc/common/rank/hot_search,10 条;搜索框 launcher 接口里的 rank_board 页面脚本不读、
  词条停在 2023 年,不用;搜索结果页本身对本机请求出验证码,不绕,只请求接口(接口不需要验证)。
- 易车 资讯排行榜:news.bitauto.com / news.yiche.com 返回腾讯 TCaptcha 验证页,不绕;
  改取 www.yiche.com 首页右栏"资讯排行榜"(li[point-crgn=zixunpaihangbang],10 条,链接同为
  news.yiche.com 文章,与 tophub 同形)。是否与 news 站"最火文章排行"是同一份榜没法直接比对
  (news 站有验证码),按 board_api 口径以 www 首页这份为准。
这些列表都不给发布时间,timestamp 一律为空。
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote, urljoin

from bs4 import BeautifulSoup, Tag
from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "auto-media"

# 子榜键 -> (中文名, 页面地址);声明序第一个是默认榜
_BOARDS: dict[str, tuple[str, str]] = {
    "autohome-article": ("汽车之家 · 文章排行榜（三日热门文章）", "https://www.autohome.com.cn/cars/hotrank/3"),
    "autohome-video": ("汽车之家 · 视频排行榜（三日热门视频）", "https://www.autohome.com.cn/cars/hotrank/2"),
    "autohome-club-hot": ("汽车之家论坛 · 论坛热帖榜", "https://club.autohome.com.cn/"),
    "autohome-club-jingxuan": ("汽车之家论坛 · 论坛精选日报", "https://club.autohome.com.cn/jingxuan"),
    "autohome-club-meiren": ("汽车之家论坛 · 美人生活秀", "https://club.autohome.com.cn/jingxuan/292"),
    "dongchedi-hot-search": ("懂车帝 · 实时热搜榜", "https://www.dongchedi.com/"),
    "yiche-news-rank": ("易车 · 资讯排行榜（最火文章排行）", "https://www.yiche.com/"),
}

type_map: dict[str, str] = {key: label for key, (label, _) in _BOARDS.items()}

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "汽车媒体榜",
    "description": "汽车之家文章 / 视频排行榜与论坛热帖、精选日报、美人生活秀；懂车帝热搜榜；易车资讯排行榜。",
    "link": "https://www.autohome.com.cn/",
    "params": {
        "type": {
            "name": "榜单",
            "type": type_map,
        },
    },
}

DEFAULT_TYPE = "autohome-article"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"
    ),
}

_AUTOHOME_RANK_API = "https://content.api.autohome.com.cn/pc/rank/v2/list"
# 页面脚本:hotrank 页 types [{type:3,文章排行榜},{type:2,视频排行榜}],[2,3] 走 ContentApi
_AUTOHOME_RANKTYPE = {"autohome-article": "3", "autohome-video": "2"}
_AUTOHOME_COUNT = 30  # 页面脚本 params:{count:30};不带只回 15 条
_DONGCHEDI_HOT_SEARCH = "https://www.dongchedi.com/motor/pc/common/rank/hot_search"

# 论坛帖子链接里的帖子 id:/bbs/thread/<hash>/<tid>-1.html
_THREAD_ID = re.compile(r"/bbs/thread/[0-9a-f]+/(\d+)-")


def _text(node: Tag | None) -> str:
    return " ".join(node.get_text(" ").split()) if node else ""


def _abs(url: str, base: str) -> str:
    return urljoin(base, url.strip()) if url else ""


def parse_wan(value: Any) -> int | None:
    """页面显示的指数:"494.9万" → 4949000,"8823" → 8823;解析不了留空。"""
    match = re.fullmatch(r"\s*([\d.]+)\s*(万|亿)?\s*", str(value or ""))
    if not match:
        return None
    unit = {"万": 10_000, "亿": 100_000_000}.get(match.group(2) or "", 1)
    return round(float(match.group(1)) * unit)


def _thread_id(url: str) -> str | None:
    match = _THREAD_ID.search(url)
    return match.group(1) if match else None


def autohome_rank(payload: Any) -> list[ListItem]:
    if not isinstance(payload, dict):
        raise RuntimeError(  # noqa: TRY004 - upstream shape problem, not a caller bug
        f"autohome rank response is not an object: {str(payload)[:200]}"
    )
    returncode = payload.get("returncode")
    if returncode is not None and str(returncode) != "0":  # 业务错误壳
        raise RuntimeError(f"autohome rank returned returncode={returncode} message={payload.get('message')}")
    rows = payload.get("result")
    if not isinstance(rows, list):
        raise RuntimeError(  # noqa: TRY004 - upstream shape problem, not a caller bug
        "autohome rank response has no result list (feed changed)"
    )
    items: list[ListItem] = []
    for row in rows:
        if not isinstance(row, dict) or not row.get("title") or not row.get("url"):
            continue
        url = str(row["url"]).strip()
        rank = row.get("rank")
        items.append(
            ListItem(
                id=str(row.get("bizId") or "") or url,
                title=str(row["title"]).strip(),
                url=url,
                mobileUrl=url,
                # 页面在 [2,3] 两个榜显示 subTitle("指数"),不显示 hotScore
                hot=parse_wan(row.get("subTitle")),
                # 接口自带的 rank 字段即展示位置
                sourceRank=rank if isinstance(rank, int) and not isinstance(rank, bool) and rank > 0 else None,
            )
        )
    return items


def club_hot(html: str, base: str) -> list[ListItem]:
    """论坛首页侧栏:多个 .rank-group 区块里按榜名取"论坛热帖榜"(tophub 榜名口径)。"""
    soup = BeautifulSoup(html, "lxml")
    group = next(
        (g for g in soup.select(".rank-group") if _text(g.select_one(".rank-group-name")) == "论坛热帖榜"),
        None,
    )
    if group is None:
        raise RuntimeError("autohome club home has no '论坛热帖榜' block (page changed)")
    items: list[ListItem] = []
    for li in group.select("ul.rank-list > li"):
        link = li.select_one(".name a[href]")
        if link is None:
            continue
        url = _abs(str(link.get("href")), base)
        items.append(
            ListItem(
                id=_thread_id(url) or url,
                title=_text(link) or str(link.get("title") or "").strip(),
                url=url,
                mobileUrl=url,
                hot=parse_wan(_text(li.select_one(".result"))),
            )
        )
    return items


def club_jingxuan(html: str, base: str) -> list[ListItem]:
    """论坛精选日报 / 美人生活秀:ul.content > li(不含顶部轮播 ul.js-show-bd)。"""
    soup = BeautifulSoup(html, "lxml")
    items: list[ListItem] = []
    for li in soup.select("ul.content > li"):
        link = li.select_one(".pic_txt p a[href]") or li.select_one("a[href*='/bbs/thread/']")
        if link is None:
            continue
        url = _abs(str(link.get("href")), base)
        img = li.select_one(".pic-box img")
        cover = str(img.get("data-original") or img.get("src") or "").strip() if img else ""
        items.append(
            ListItem(
                id=str(li.get("tid") or "") or _thread_id(url) or url,
                title=_text(link) or str(link.get("title") or "").strip(),
                url=url,
                mobileUrl=url,
                cover=_abs(cover, base) or None,
                author=_text(li.select_one("dt.user span")) or None,
                desc=_text(li.select_one(".model-num")) or None,  # 标签,如"新能源""SUV"
            )
        )
    return items


def dongchedi_hot_search(payload: Any) -> list[ListItem]:
    data = payload.get("data") if isinstance(payload, dict) else None
    tops = data.get("tops") if isinstance(data, dict) else None
    if not isinstance(tops, list):
        raise RuntimeError(  # noqa: TRY004 - upstream shape problem, not a caller bug
        f"dongchedi hot_search returned no data.tops: {str(payload)[:200]}"
    )
    items: list[ListItem] = []
    for top in tops:
        title = str((top or {}).get("title") or "").strip()
        if not title:
            continue
        # 接口只给词条;页面点击词条进搜索页,与 tophub 同形(搜索页对部分访问者出验证码)
        url = f"https://www.dongchedi.com/search?keyword={quote(title)}"
        items.append(
            ListItem(
                id=title,
                title=title,
                url=url,
                mobileUrl=url,
                hot=top.get("score"),
                desc=str(top.get("description") or "").strip() or None,
            )
        )
    return items


def yiche_rank(html: str, base: str) -> list[ListItem]:
    """易车 www 首页右栏"资讯排行榜":埋点属性 li[point-crgn=zixunpaihangbang] 定位。"""
    soup = BeautifulSoup(html, "lxml")
    items: list[ListItem] = []
    for li in soup.select('li[point-crgn="zixunpaihangbang"]'):
        link = li.select_one("a[href]")
        if link is None:
            continue
        url = _abs(str(link.get("href")), base)
        items.append(
            ListItem(
                id=str(li.get("point-cid") or "") or url,
                title=_text(li.select_one(".h-zx-title")) or _text(link),
                url=url,
                mobileUrl=url,
            )
        )
    return items


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    board = request.query_params.get("type", DEFAULT_TYPE)
    if board not in _BOARDS:
        raise ValueError(f"Unknown board '{board}' for route '{ROUTE_NAME}'")
    label, page = _BOARDS[board]
    if board in _AUTOHOME_RANKTYPE:
        result = await get(
            url=_AUTOHOME_RANK_API,
            params={"count": str(_AUTOHOME_COUNT), "ranktype": _AUTOHOME_RANKTYPE[board]},
            headers=_HEADERS,
            no_cache=no_cache,
            response_type="json",
        )
        items = autohome_rank(result.data)
    elif board == "dongchedi-hot-search":
        result = await get(
            url=_DONGCHEDI_HOT_SEARCH,
            headers=_HEADERS,
            no_cache=no_cache,
            response_type="json",
        )
        items = dongchedi_hot_search(result.data)
    else:
        result = await get(url=page, headers=_HEADERS, no_cache=no_cache, response_type="text")
        if board == "autohome-club-hot":
            items = club_hot(result.data, page)
        elif board == "yiche-news-rank":
            items = yiche_rank(result.data, page)
        else:
            items = club_jingxuan(result.data, page)
    unique: dict[str, ListItem] = {}
    for item in items:  # 按 id 去重,保留第一次出现(页面顺序)
        unique.setdefault(item.id, item)
    data = list(unique.values())
    if not data:
        raise RuntimeError(f"auto-media {board} parsed no items from {page}")
    return RouterData(
        **ROUTE_META,
        type=label,
        total=len(data),
        fromCache=result.from_cache,
        updateTime=result.update_time,
        data=data,
    )
