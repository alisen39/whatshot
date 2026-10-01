"""App Store / Mac App Store 排行 + 国区播客 Top 100（board_api B3 单元迁移）。

467 个子榜一个路由，`type` 区分，三个数据源（均为 Apple 公开接口或服务端渲染页面，
无签名、无 cookie、无登录；口径照 board_api appstore_charts 单元证据落实）：

1. 旧版 iTunes RSS（JSON）`itunes.apple.com/{cc}/rss/{feed}/limit=100[/genre={id}]/json`
   —— 458 个榜：6 个不带分类的总榜、2 个 Mac 免费榜、450 个分类榜。与原站网页排行榜
   同源；赚钱榜只有它有。limit 不传只回 10 条、201 起报 400，固定 100（Apple 单榜上限）；
   genre 用不存在的 id 不报错、退回总榜。只 1 条时 `entry` 是对象、0 条时没有 `entry` 键；
   0 条是合法态（证据：`toppaidmacapps` 200 且 0 条），输出空榜并在 message 说明。
2. 原站网页儿童排行榜 `apps.apple.com/{cc}/{iphone|ipad}/charts/36?ageBandId=0&chart=…`
   + iTunes lookup 补字段 —— 8 个儿童榜。儿童按年龄段（ageBandId）分，旧版 RSS 与分类
   服务里都没有。页面数据在 `serialized-server-data`：第一屏 25 条带名称、开发者、图标、
   链接（`shelves[].items`），其余 175 条只有 id（`nextPage.remainingContent`），用 lookup
   （一次最多 200 个 id）补齐。共享 client 恒跟随跳转，国内 KS-CLOUD 节点会把 /us 302 到
   /cn，跟随后拿到的是国区页面，用 canonicalURL / ageBandId 校验拦下，不把别的地区当
   美区输出。lookup 查不到的（App 套装、刚下架）逐个取商品页补名称，最多 10 个。
3. 新版 RSS `rss.marketingtools.apple.com/api/v2/cn/podcasts/top/100/podcasts.json`
   —— 国区播客 Top 100。与原站页面"热门节目"逐位相同（旧版 toppodcasts 漏付费订阅节目）；
   接口没有日期字段，timestamp 留空；该接口实测 2.7~7 秒，恒返回 100 条，空结果是结构变化。

apple.com 系（itunes / apps / rss.marketingtools）1.2 秒最多 1 个请求（board_api
common.throttle 口径，Core 路由层退化为同模块全局限速：只对真实发出的上游请求计时，
缓存命中不占时限）；失败隔 3 秒重试一次（board_api 口径：本机对 itunes.apple.com 偶发
连接超时，紧接着重试就好；共享 client 的 raise_for_status 把 5xx 也归入异常）。
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from typing import Any, NamedTuple

from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import RequestResult, get

ROUTE_NAME = "appstore-charts"

_RSS_URL = "https://itunes.apple.com/{cc}/rss/{feed}/limit=100{genre}/json"
_KIDS_PAGE_URL = "https://apps.apple.com/{cc}/{device}/charts/36?ageBandId=0&chart={chart}"
_LOOKUP_URL = "https://itunes.apple.com/lookup"
_PRODUCT_URL = "https://apps.apple.com/{cc}/{path}/id{ident}"
_PODCASTS_URL = "https://rss.marketingtools.apple.com/api/v2/{cc}/podcasts/top/100/podcasts.json"

# apple.com 系两次真实上游请求至少隔 1.2 秒（board_api common.throttle 口径）。
RATE_LIMIT_SECONDS = 1.2
RETRY_WAIT_SECONDS = 3  # 失败隔 3 秒重试一次
_LOOKUP_BATCH = 200  # 一次 lookup 传的 id 数（实测 200 个 id 一次全部返回）
_PRODUCT_FALLBACK_MAX = 10  # lookup 查不到的条目逐个取商品页，最多这么多个，再多说明结构变了
_JSON_HEADERS = {"Accept": "application/json", "User-Agent": "Mozilla/5.0"}
_HTML_HEADERS = {"User-Agent": "Mozilla/5.0"}
_SERVER_DATA = re.compile(r'<script[^>]*id="serialized-server-data"[^>]*>(.*?)</script>', re.DOTALL)

_REGIONS = {"cn": ("国区", "中国"), "us": ("美区", "美国")}
_DEVICES = {"iphone": "iPhone", "ipad": "iPad"}
_KINDS = {"free": "免费榜", "paid": "付费榜", "grossing": "赚钱榜"}
_KIDS_CHARTS = {"free": "top-free", "paid": "top-paid"}  # 原站儿童榜只有这两种
_FEEDS = {
    ("iphone", "free"): "topfreeapplications",
    ("iphone", "paid"): "toppaidapplications",
    ("iphone", "grossing"): "topgrossingapplications",
    ("ipad", "free"): "topfreeipadapplications",
    ("ipad", "paid"): "toppaidipadapplications",
    ("ipad", "grossing"): "topgrossingipadapplications",
}
# tophub 分类名 -> (Apple genre id, 子榜键里的英文 slug)。slug = Apple 美区分类名转小写
# 短横线，游戏子类加 games- 前缀（board_api evidence/genre_map.tsv，39 行映射照搬）。
_CATEGORIES: dict[str, tuple[int, str]] = {
    "游戏": (6014, "games"),
    "商务": (6000, "business"),
    "天气": (6001, "weather"),
    "工具": (6002, "utilities"),
    "旅游": (6003, "travel"),
    "社交": (6005, "social-networking"),
    "参考资料": (6006, "reference"),
    "效率": (6007, "productivity"),
    "摄影与录像": (6008, "photo-video"),
    "导航": (6010, "navigation"),
    "音乐": (6011, "music"),
    "生活": (6012, "lifestyle"),
    "健康健美": (6013, "health-fitness"),
    "财务": (6015, "finance"),
    "娱乐": (6016, "entertainment"),
    "教育": (6017, "education"),
    "图书": (6018, "books"),
    "医疗": (6020, "medical"),
    "报刊杂志": (6021, "magazines-newspapers"),
    "美食佳饮": (6023, "food-drink"),
    "购物": (6024, "shopping"),
    "软件开发工具": (6026, "developer-tools"),
    "图形与设计": (6027, "graphics-design"),
    "动作游戏": (7001, "games-action"),
    "冒险游戏": (7002, "games-adventure"),
    "休闲": (7003, "games-casual"),
    "桌面游戏": (7004, "games-board"),
    "卡牌游戏": (7005, "games-card"),
    "家庭聚会游戏": (7009, "games-family"),
    "音乐游戏": (7011, "games-music"),
    "益智解谜游戏": (7012, "games-puzzle"),
    "竞速游戏": (7013, "games-racing"),
    "角色扮演游戏": (7014, "games-roleplaying"),
    "模拟游戏": (7015, "games-simulation"),
    "体育": (7016, "games-sports"),
    "策略游戏": (7017, "games-strategy"),
    "问答游戏": (7018, "games-trivia"),
    "字谜游戏": (7019, "games-word"),
}
# 个别榜换分类：(地区, 榜型, tophub 分类名) -> (genre id, slug)。国区付费榜 7016 为 0 条
# （5 个 App 已下架，证据 evidence/06_*、08_*），tophub 显示的是 6004 体育 App，这两个榜
# 用 6004（子榜键 -sports，其余体育榜 -games-sports）。
_GENRE_OVERRIDES = {("cn", "paid", "体育"): (6004, "sports")}
# tophub 没有的组合：国区这三个游戏子类的付费榜（Apple 实测只有 1~2 条）。
_SKIP = {("cn", "paid", c) for c in ("家庭聚会游戏", "桌面游戏", "问答游戏")}
# 不带分类的总榜：子榜键 -> (tophub 榜名, 地区, feed)。Mac 免费榜条目链接带 ?mt=12（原样保留）。
_OVERALL = {
    "cn-iphone-free": ("中国 iPhone 免费榜", "cn", "topfreeapplications"),
    "cn-iphone-paid": ("中国 iPhone 付费榜", "cn", "toppaidapplications"),
    "cn-ipad-paid": ("中国 iPad 付费榜", "cn", "toppaidipadapplications"),
    "us-iphone-free": ("美国 iPhone 免费榜", "us", "topfreeapplications"),
    "us-iphone-paid": ("美国 iPhone 付费榜", "us", "toppaidapplications"),
    "us-ipad-paid": ("美国 iPad 付费榜", "us", "toppaidipadapplications"),
    "cn-mac-free": ("中国 免费榜", "cn", "topfreemacapps"),
    "us-mac-free": ("美国 免费榜", "us", "topfreemacapps"),
}


class _Board(NamedTuple):
    name: str  # tophub 榜名（对外展示的 type 标签）
    cc: str  # cn / us
    source: str  # rss（旧版 iTunes RSS）、kids（网页儿童榜 + lookup）、podcasts（新版 RSS）
    url: str
    device: str = ""  # 只有 kids 用：iphone / ipad
    chart: str = ""  # 只有 kids 用：top-free / top-paid


def _rss_board(name: str, cc: str, feed: str, genre: int | None = None) -> _Board:
    return _Board(
        name, cc, "rss", _RSS_URL.format(cc=cc, feed=feed, genre=f"/genre={genre}" if genre else "")
    )


def _build_boards() -> dict[str, _Board]:
    """生成全部 467 个子榜；声明序第一个是默认榜（cn-iphone-free，与 board_api 一致）。"""
    boards: dict[str, _Board] = {
        key: _rss_board(name, cc, feed) for key, (name, cc, feed) in _OVERALL.items()
    }
    boards["cn-podcasts"] = _Board("中国区播客Top100", "cn", "podcasts", _PODCASTS_URL.format(cc="cn"))
    for cc, (region, _) in _REGIONS.items():
        for device, device_label in _DEVICES.items():
            for kind, kind_label in _KINDS.items():
                for cat, (genre, slug) in _CATEGORIES.items():
                    if (cc, kind, cat) in _SKIP:
                        continue
                    genre, slug = _GENRE_OVERRIDES.get((cc, kind, cat), (genre, slug))
                    boards[f"{cc}-{device}-{kind}-{slug}"] = _rss_board(
                        f"{cat}{kind_label}[{device_label}][{region}]", cc, _FEEDS[(device, kind)], genre
                    )
            for kind, chart in _KIDS_CHARTS.items():
                boards[f"{cc}-{device}-{kind}-kids"] = _Board(
                    f"儿童{_KINDS[kind]}[{device_label}][{region}]",
                    cc,
                    "kids",
                    _KIDS_PAGE_URL.format(cc=cc, device=device, chart=chart),
                    device,
                    chart,
                )
    return boards


BOARDS = _build_boards()
DEFAULT_TYPE = "cn-iphone-free"

type_map: dict[str, str] = {key: board.name for key, board in BOARDS.items()}

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "App Store",
    "description": (
        "App Store 国区 / 美区 iPhone、iPad 免费、付费、赚钱榜（总榜与分类榜）和儿童免费、"
        "付费榜，Mac 免费榜，国区播客 Top 100"
    ),
    "link": "https://apps.apple.com/",
    "params": {"type": {"name": "榜单", "type": type_map}},
}

# apple.com 系全局限速：只对真实发出的上游请求计时（from_cache 不占时限）。
_throttle_lock = asyncio.Lock()
_last_upstream_at = 0.0


def _mark_upstream(from_cache: bool) -> None:
    global _last_upstream_at
    if not from_cache:
        _last_upstream_at = time.monotonic()


async def _polite_delay() -> None:
    """两次真实上游请求之间至少隔 RATE_LIMIT_SECONDS。"""
    global _last_upstream_at
    async with _throttle_lock:
        wait = RATE_LIMIT_SECONDS - (time.monotonic() - _last_upstream_at)
        if wait > 0:
            await asyncio.sleep(wait)
        _last_upstream_at = time.monotonic()


async def _fetch_json(url: str, no_cache: bool, cache_key: str) -> RequestResult:
    """GET 一个 JSON；失败隔 3 秒重试一次（连接类错误 / 5xx，board_api 口径）。

    共享 client 的 raise_for_status 会把非 2xx 直接抛出，因此不区分错误类型。"""
    try:
        await _polite_delay()
        result = await get(
            url=url, headers=_JSON_HEADERS, no_cache=no_cache, response_type="json", cache_key=cache_key
        )
    except Exception:  # noqa: BLE001 - 连接类错误与 raise_for_status 的 5xx 统一重试一次
        await asyncio.sleep(RETRY_WAIT_SECONDS)
        result = await get(
            url=url, headers=_JSON_HEADERS, no_cache=True, response_type="json", cache_key=cache_key
        )
    _mark_upstream(result.from_cache)
    return result


async def _fetch_text(url: str, no_cache: bool, cache_key: str) -> RequestResult:
    """GET 一个文本页（儿童榜 HTML / 商品页）。不重试：商品页失败只是该条不输出。"""
    await _polite_delay()
    result = await get(
        url=url, headers=_HTML_HEADERS, no_cache=no_cache, response_type="text", cache_key=cache_key
    )
    _mark_upstream(result.from_cache)
    return result


def _label(entry: dict[str, Any], key: str) -> str:
    value = entry.get(key)
    return str(value.get("label") or "").strip() if isinstance(value, dict) else ""


def _entry_link(entry: dict[str, Any]) -> str:
    """link 在有预览图的条目里是列表（alternate + enclosure），否则是单个对象；
    取 rel=alternate 的原链接（带 ?uo=2，Mac 榜 ?mt=12&uo=2，与 RSS 一致）。"""
    links = entry.get("link")
    links = links if isinstance(links, list) else [links]
    for link in links:
        attrs = link.get("attributes") if isinstance(link, dict) else None
        if isinstance(attrs, dict) and attrs.get("rel") == "alternate" and attrs.get("href"):
            return str(attrs["href"])
    return _label(entry, "id")  # id.label 与 alternate 链接相同


def _entry_cover(entry: dict[str, Any]) -> str | None:
    # im:image 给 3 个尺寸（53/75/100），取 height 最大的一个。
    images = [i for i in entry.get("im:image") or [] if isinstance(i, dict) and i.get("label")]

    def height(image: dict[str, Any]) -> int:
        try:
            return int((image.get("attributes") or {}).get("height") or 0)
        except (TypeError, ValueError):
            return 0

    return str(max(images, key=height)["label"]) if images else None


def _parse_rss_entry(entry: dict[str, Any]) -> ListItem | None:
    ident = str(((entry.get("id") or {}).get("attributes") or {}).get("im:id") or "").strip()
    title = _label(entry, "im:name")
    url = _entry_link(entry)
    if not ident or not title or not url:
        return None
    category = str(((entry.get("category") or {}).get("attributes") or {}).get("label") or "").strip()
    price = _label(entry, "im:price")  # 免费为"获取"/"Get"，付费如"¥24.00"/"$6.99"
    return ListItem(
        id=ident,
        title=title,
        url=url,
        mobileUrl=url,
        cover=_entry_cover(entry),
        author=_label(entry, "im:artist") or None,
        desc=" · ".join(part for part in (category, price) if part) or None,
        # im:releaseDate 是 App 首次上架时间，一律当天 0 点 -07:00（不区分夏令时）
        timestamp=get_time(_label(entry, "im:releaseDate")),
    )


async def _fetch_rss(board: _Board, no_cache: bool) -> tuple[list[ListItem], bool, str, str | None]:
    result = await _fetch_json(board.url, no_cache, cache_key=f"{ROUTE_NAME}:{board.url}")
    payload = result.data
    feed = payload.get("feed") if isinstance(payload, dict) else None
    if not isinstance(feed, dict):
        raise ValueError(f"App Store RSS {board.url} 不是 iTunes RSS JSON")  # noqa: TRY004 - upstream shape problem
    entries = feed.get("entry") or []  # 0 条时没有 entry 键（board_api 证据：toppaidmacapps 200 且 0 条）
    entries = [entries] if isinstance(entries, dict) else entries  # 只有 1 条时 entry 是对象
    items = [item for item in (_parse_rss_entry(entry) for entry in entries if isinstance(entry, dict)) if item]
    if len(items) != len(entries):
        raise ValueError(
            f"App Store RSS {board.url} 有 {len(entries) - len(items)} 条缺 id / 名称 / 链接，RSS 结构可能变了"
        )
    message = None if items else f"Apple 该榜当前没有条目（{board.url}）"
    return items, result.from_cache, result.update_time, message


def _parse_server_data(html: str, source: str) -> dict[str, Any]:
    match = _SERVER_DATA.search(html)
    if not match:
        raise ValueError(f"{source} 的 serialized-server-data 缺失，页面结构可能变了")
    try:
        return json.loads(match.group(1))["data"][0]["data"]
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise ValueError(f"{source} 的 serialized-server-data 解析失败，页面结构可能变了") from exc


def _icon_from_template(template: object) -> str | None:
    # 图标模板形如 …/AppIcon….png/{w}x{h}{c}.{f}，按 lookup artworkUrl100 的规格填 100x100bb.jpg
    if not isinstance(template, str) or not template:
        return None
    return template.replace("{w}", "100").replace("{h}", "100").replace("{c}", "bb").replace("{f}", "jpg")


async def _lookup_ids(
    order: list[str], cc: str, cache_key: str, no_cache: bool
) -> tuple[dict[str, dict[str, Any]], bool, str]:
    """按 200 个 id 一批查 iTunes lookup，返回 (id -> lookup 行, from_cache, update_time)。"""
    found: dict[str, dict[str, Any]] = {}
    all_cached = True
    update_time = ""
    for index in range(0, len(order), _LOOKUP_BATCH):
        batch = order[index : index + _LOOKUP_BATCH]
        url = f"{_LOOKUP_URL}?id={','.join(batch)}&country={cc}"
        result = await _fetch_json(url, no_cache, cache_key=f"{cache_key}:lookup:{index // _LOOKUP_BATCH}")
        all_cached = all_cached and result.from_cache
        update_time = result.update_time
        results = (result.data.get("results") if isinstance(result.data, dict) else None) or []
        for row in results:
            if isinstance(row, dict) and row.get("trackId"):
                found[str(row["trackId"])] = row
    return found, all_cached, update_time


async def _product_page(cc: str, ident: str, kind: str, no_cache: bool) -> dict[str, Any] | None:
    """lookup 查不到的条目（App 套装、刚下架的 App）取商品页的名称、链接、图标；打不开返回 None。"""
    path = "app-bundle" if kind == "app-bundles" else "app"
    url = _PRODUCT_URL.format(cc=cc, path=path, ident=ident)
    try:
        result = await _fetch_text(url, no_cache, cache_key=f"{ROUTE_NAME}:product:{cc}:{ident}")
        data = _parse_server_data(result.data if isinstance(result.data, str) else "", url)
    except Exception:  # noqa: BLE001 - 商品页打不开 / 结构变了只放弃该条，不拖垮整个榜单
        return None
    title = str(data.get("title") or "").strip()
    if not title:
        return None
    lockup = data.get("lockup") if isinstance(data.get("lockup"), dict) else {}
    return {
        "title": title,
        "url": str(data.get("canonicalURL") or ""),
        "icon": ((lockup or {}).get("icon") or {}).get("template"),
    }


async def _fetch_kids(board: _Board, no_cache: bool) -> tuple[list[ListItem], bool, str, str | None]:
    cache_key = f"{ROUTE_NAME}:{board.url}"
    page = await _fetch_text(board.url, no_cache, cache_key=f"{cache_key}:page")
    data = _parse_server_data(page.data if isinstance(page.data, str) else "", board.url)
    canonical = str(data.get("canonicalURL") or "")
    region_label = _REGIONS[board.cc][0]
    # 共享 client 恒跟随跳转：国内 KS-CLOUD 节点会把 /us 302 到 /cn，跟随后拿到的是国区
    # 页面，这里用 canonicalURL / ageBandId 拦下，不把别的地区的榜当美区输出。
    if not canonical.startswith(f"https://apps.apple.com/{board.cc}/{board.device}/") or str(
        data.get("ageBandId")
    ) != "0":
        raise ValueError(
            f"{board.url} 返回的不是本榜（canonicalURL={canonical!r}，ageBandId={data.get('ageBandId')!r}）；"
            f"国内 CDN 节点会把 /us 跳到 /cn，不能把别的地区的榜当成{region_label}输出"
        )
    segment = next(
        (seg for seg in data.get("segments") or [] if isinstance(seg, dict) and seg.get("chart") == board.chart),
        None,
    )
    if segment is None:
        raise ValueError(f"{board.url} 里没有 {board.chart} 这一段，页面结构可能变了")
    # 页面顺序：第一屏（shelves[].items，带名称）在前，其余（nextPage.remainingContent，只有 id）在后
    first = {
        str(item["adamId"]): item
        for shelf in segment.get("shelves") or []
        for item in shelf.get("items") or []
        if isinstance(item, dict) and item.get("adamId")
    }
    rest = [
        x
        for x in (segment.get("nextPage") or {}).get("remainingContent") or []
        if isinstance(x, dict) and x.get("id")
    ]
    order = list(dict.fromkeys([*first, *(str(x["id"]) for x in rest)]))
    if not order:
        raise ValueError(f"{board.url} 儿童榜没有任何条目，页面结构可能变了")
    kinds = {str(x["id"]): str(x.get("type") or "") for x in rest}
    found, lookup_cached, lookup_time = await _lookup_ids(order, board.cc, cache_key, no_cache)
    missing = [ident for ident in order if ident not in found and ident not in first]
    if len(missing) > _PRODUCT_FALLBACK_MAX:
        raise ValueError(f"{board.url} 有 {len(missing)} 条 lookup 查不到（{missing[:5]}…），接口可能变了")
    pages = {ident: await _product_page(board.cc, ident, kinds.get(ident, ""), no_cache) for ident in missing}
    items: list[ListItem] = []
    dropped: list[str] = []
    suffix = "?platform=ipad" if board.device == "ipad" else ""  # 与页面的条目链接一致：iPad 榜带 platform=ipad
    for rank, ident in enumerate(order, 1):
        page_item = first.get(ident) or {}
        lookup_row = found.get(ident) or {}
        product = pages.get(ident) or {}
        title = str(page_item.get("title") or lookup_row.get("trackName") or product.get("title") or "").strip()
        url = str(((page_item.get("clickAction") or {}).get("pageUrl")) or "")
        if not url and lookup_row.get("trackViewUrl"):
            url = str(lookup_row["trackViewUrl"]).split("?")[0] + suffix
        if not url and product.get("url"):
            url = str(product["url"]) + ("" if "?" in str(product["url"]) else suffix)
        if not title or not url:
            dropped.append(f"第 {rank} 名 id{ident}")
            continue
        genres = lookup_row.get("genres") or [lookup_row.get("primaryGenreName")]  # genres 是本地化名称
        price = lookup_row.get("formattedPrice")
        items.append(
            ListItem(
                id=ident,
                title=title,
                url=url,
                mobileUrl=url,
                cover=lookup_row.get("artworkUrl100")
                or _icon_from_template((page_item.get("icon") or {}).get("template"))
                or _icon_from_template(product.get("icon")),
                author=page_item.get("developerName") or lookup_row.get("artistName") or None,
                desc=" · ".join(str(part) for part in (genres[0] if genres else None, price) if part) or None,
                timestamp=get_time(str(lookup_row.get("releaseDate") or "")),
            )
        )
    if not items:
        raise ValueError(f"{board.url} 的 {len(order)} 条全部缺名称 / 链接，页面或 lookup 结构可能变了")
    notes: list[str] = []
    if any(pages.values()):
        notes.append(
            f"{sum(bool(v) for v in pages.values())} 条 lookup 查不到，名称、链接取自商品页"
            f"（id {'、'.join(i for i, v in pages.items() if v)}）"
        )
    if dropped:
        notes.append(f"{len(dropped)} 条 lookup 与商品页都查不到，未输出：{'、'.join(dropped)}")
    return items, (page.from_cache and lookup_cached), lookup_time or page.update_time, "；".join(notes) or None


async def _fetch_podcasts(board: _Board, no_cache: bool) -> tuple[list[ListItem], bool, str, str | None]:
    result = await _fetch_json(board.url, no_cache, cache_key=f"{ROUTE_NAME}:{board.url}")
    payload = result.data
    feed = payload.get("feed") if isinstance(payload, dict) else None
    results = (feed or {}).get("results") if isinstance(feed, dict) else None
    results = results or []
    if not results:
        # 该接口恒返回 Top 100；空结果说明接口改版，不得静默输出空榜
        raise ValueError(f"App Store 播客榜 {board.url} 返回空列表，接口结构可能变了")
    items: list[ListItem] = []
    for row in results:
        if not isinstance(row, dict):
            raise ValueError(  # noqa: TRY004 - upstream shape problem, not a caller bug
                f"App Store 播客榜 {board.url} 条目不是对象，接口结构可能变了"
            )
        ident, title, url = (str(row.get(key) or "").strip() for key in ("id", "name", "url"))
        if not ident or not title or not url:
            raise ValueError(f"App Store 播客榜 {board.url} 有条目缺 id / 名称 / 链接，接口结构可能变了")
        genres = [str(genre.get("name") or "").strip() for genre in row.get("genres") or [] if isinstance(genre, dict)]
        items.append(
            ListItem(
                id=ident,
                title=title,
                url=url,
                mobileUrl=url,
                cover=row.get("artworkUrl100"),
                author=row.get("artistName") or None,
                desc="、".join(genre for genre in genres if genre) or None,
                timestamp=None,  # 新版接口没有日期字段
            )
        )
    return items, result.from_cache, result.update_time, None


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    selected = request.query_params.get("type") or DEFAULT_TYPE
    if selected not in BOARDS:
        raise ValueError(f"Unknown type '{selected}' for route '{ROUTE_NAME}'")
    board = BOARDS[selected]
    if board.source == "kids":
        data, from_cache, update_time, message = await _fetch_kids(board, no_cache)
    elif board.source == "podcasts":
        data, from_cache, update_time, message = await _fetch_podcasts(board, no_cache)
    else:
        data, from_cache, update_time, message = await _fetch_rss(board, no_cache)
    return RouterData(
        **ROUTE_META,
        type=board.name,
        total=len(data),
        fromCache=from_cache,
        updateTime=update_time,
        data=data,
        message=message,
    )
