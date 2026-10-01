"""腾讯视频频道榜（qqvideo-rank）：热搜分频道搜索词榜，单路由 type 区分。

移植自 board_api/tencent_video_rank（2026-09-28 已验证，verify/ 下有自验、页签核对与推翻性验证）：
- 数据源是腾讯视频"全网影视排行榜"的热搜分频道页 v.qq.com/biu/ranks/?t=hotsearch&channel=<频道 ID>，
  服务端渲染 HTML，每页 50 条、没有翻页；每榜 1 个请求
- 与 whatshot qqvideo-tv-hotsearch（pbaccess getCard，只有电视剧频道）是不同来源；
  电视剧（channel=2）不在本单元，科技原创榜（channel=24）列表停在 2024 年底，不做
- 热搜（channel=0）与新版接口 HotRankHttp 的"热搜"页签逐位相同，为 7 个榜同一种取法统一取页面
  （verify/page_check.md 第 2 节）

反爬口径（verify/header_matrix.jsonl）：
- UA / Referer / cookie 都不是必需：curl、python-httpx、不带 UA 共 6 组头全部 200、内容逐字相同；
  统一还是带浏览器 UA，防上游日后按 UA 过滤
- 未观察到限流；页面走 CDN 缓存（x-cache-lookup: Cache Hit），输出最多比实时晚几分钟

条目只有搜索词和相对热度条（.bar_inner 宽度百分比，第 1 名 100%，不是热度数值），
没有日期、封面，所以 id / title / url / mobileUrl 有值，其余为空。
"""

from __future__ import annotations

from urllib.parse import urljoin

from bs4 import BeautifulSoup
from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "qqvideo-rank"

_PAGE = "https://v.qq.com/biu/ranks/"

# 子榜 -> (频道 ID, 页面页签名)。频道 ID 取自热搜榜页各频道块"更多"链接的 channel 参数；
# 声明序第一个（hotsearch）是默认榜。顺序照 tophub 榜单目录。
_BOARDS: dict[str, tuple[int, str]] = {
    "hotsearch": (0, "热搜"),
    "movie": (1, "电影"),
    "variety": (10, "综艺"),
    "cartoon": (3, "动漫"),
    "child": (106, "少儿"),
    "doco": (9, "纪录片"),
    "game": (6, "游戏"),
}

type_map: dict[str, str] = {key: label for key, (_, label) in _BOARDS.items()}

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "腾讯视频",
    "description": (
        "腾讯视频全网影视排行榜的热搜分频道榜（搜索词）："
        "热搜、电影、综艺、动漫、少儿、纪录片、游戏"
    ),
    "link": "https://v.qq.com/biu/ranks/?t=hotsearch",
    "params": {
        "type": {
            "name": "频道",
            "type": type_map,
        },
    },
}

# header_matrix.jsonl：6 组请求头（含不带 UA、python-httpx UA）返回内容逐字相同，UA 非必需
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/145.0.0.0 Safari/537.36"
    ),
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    type_param = request.query_params.get("type", "hotsearch")
    if type_param not in _BOARDS:
        raise ValueError(f"Unknown board '{type_param}' for route '{ROUTE_NAME}'")
    channel_id, label = _BOARDS[type_param]
    url = f"{_PAGE}?t=hotsearch&channel={channel_id}"
    result = await get(url=url, headers=_HEADERS, no_cache=no_cache, response_type="text")
    items = _parse_page(str(result.data), type_param)
    if not items:
        # 频道 ID 无效时页面仍返回 200，但没有页签和列表（evidence/05_channel_999_invalid）
        raise RuntimeError(f"qqvideo-rank {label} page has no items: {url}")
    return RouterData(
        **ROUTE_META,
        type=label,
        total=len(items),
        fromCache=result.from_cache,
        updateTime=result.update_time,
        data=items,
    )


def _parse_page(html: str, board: str) -> list[ListItem]:
    """解析频道页：先核对页签名，再取 ul.table_list 里每行的搜索词与链接。

    页签名对不上说明频道 ID 被改了或页面结构变了，按错误处理，不静默降级为空榜。
    """
    soup = BeautifulSoup(html, "lxml")
    channel_label = _BOARDS[board][1]
    tab = soup.select_one("div.mod_row_box .mod_rank_tab .link_nav.current")
    tab_name = tab.get_text(strip=True) if tab else ""
    if tab_name != channel_label:
        raise RuntimeError(
            f"qqvideo-rank {board} page tab is {tab_name!r}, expected {channel_label!r}"
        )
    items: list[ListItem] = []
    seen: set[str] = set()
    for li in soup.select("div.mod_row_box ul.table_list > li.item_list"):
        # 第一行 item_title 是表头（关键词 / 搜索热度 / 升降趋势），没有 a.name
        a = li.select_one("a.name")
        if a is None:
            continue
        title = str(a.get("title") or a.get_text(strip=True) or "").strip()
        href = str(a.get("href") or "").strip()
        if not title or not href or title in seen:
            continue
        seen.add(title)
        url = urljoin(_PAGE, href)
        items.append(ListItem(id=title, title=title, url=url, mobileUrl=url))
    return items
