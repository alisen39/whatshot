from __future__ import annotations

import hashlib
import re

from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get
from whats_hot_api.utils.newsflash import strip_html

ROUTE_NAME = "cls-depth"

# 财联社深度频道页(www.cls.cn/depth?id=<频道 id>)的首屏接口,每个频道 1 个请求。
# whatshot 既有 cls 路由(电报快讯)的 depth 子榜请求的是同一个 assembled/1000 接口,
# 但只取 depth_list 并按 ctime 倒序重排——头条频道的 depth_list 是编辑顺序,重排后
# 与页面不一致;本路由按页面口径输出(见 _parse_items 注释)。
# 频道 id 取自 v2/base/common_config 的 column_bar;原站调整频道时去那里重新取。
_CHANNELS: dict[str, tuple[int, str]] = {
    "headline": (1000, "头条"),
    "a-share": (1003, "A股"),
    "hk-stock": (1135, "港股"),
    "global": (1007, "环球"),
    "company": (1005, "公司"),
    "brokerage": (1118, "券商"),
    "fund": (1110, "基金·ETF"),
    "real-estate": (1006, "地产"),
    "finance": (1032, "金融"),
    "auto": (1119, "汽车"),
    "sci-tech": (1111, "科创"),
    "futures": (1124, "期货"),
    "investor-edu": (1176, "投教"),
}

type_map: dict[str, str] = {key: label for key, (_, label) in _CHANNELS.items()}

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "财联社",
    "description": "财联社深度频道:头条、A股、港股、环球、公司、券商、基金·ETF、地产、金融、汽车、科创、期货、投教(置顶区块 + 列表,原站顺序)",
    "link": "https://www.cls.cn/depth?id=1000",
    "params": {"type": {"name": "深度频道", "type": type_map}},
}

_DEFAULT_TYPE = "headline"

# 页面 request 封装固定加的三个参数(pages/_app chunk);签名只校验与实际参数集自洽,
# 缺少它们但按新参数集重算 sign 也能通过,这里照页面写法固定传。
_BASE_PARAMS: dict[str, str] = {"app": "CailianpressWeb", "os": "web", "sv": "8.7.9"}

# 置顶区块的 ctype 链接规则(pages/depth-*.js):1 专题 /subject/、2 话题 /topic/,
# 其余(含列表)是文章 /detail/<id>;external_link 非空时优先。
_PINNED_PATHS = {1: "subject", 2: "topic"}

_WS_RE = re.compile(r"\s+")


def _signed_url(channel_id: int) -> str:
    # sign = md5(sha1(按键排序的 k=v&k=v)),无密钥、无时间戳,本地计算;缺失或与
    # 参数集不自洽时接口返回 errno=10012「签名错误」(HTTP 仍是 200)。
    qs = "&".join(f"{key}={value}" for key, value in sorted(_BASE_PARAMS.items()))
    sha1_value = hashlib.sha1(qs.encode(), usedforsecurity=False).hexdigest()
    sign = hashlib.md5(sha1_value.encode(), usedforsecurity=False).hexdigest()
    return f"https://www.cls.cn/v3/depth/home/assembled/{channel_id}?{qs}&sign={sign}"


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    selected = request.query_params.get("type", _DEFAULT_TYPE)
    if selected not in _CHANNELS:
        raise ValueError(f"Unknown board '{selected}' for route '{ROUTE_NAME}'")
    channel_id, label = _CHANNELS[selected]
    # 反爬实测(board_api verify/param_matrix.md):接口不需要任何请求头,httpx 缺省 UA
    # 即返回同一份数据,这里不额外带 UA/Referer。
    result = await get(url=_signed_url(channel_id), no_cache=no_cache, response_type="json")
    payload = result.data if isinstance(result.data, dict) else {}
    if payload.get("errno") != 0 or not isinstance(payload.get("data"), dict):
        raise RuntimeError(
            f"CLS depth {selected} returned errno={payload.get('errno')}: {payload.get('msg') or ''}"
        )
    items = _parse_items(payload["data"])
    if not items:
        raise RuntimeError(f"CLS depth {label} returned no items")
    return RouterData(
        **ROUTE_META,
        type=label,
        total=len(items),
        fromCache=result.from_cache,
        updateTime=result.update_time,
        data=items,
    )


def _parse_items(data: dict) -> list[ListItem]:
    # 页面渲染顺序(pages/depth-*.js):轮播图 banner → 置顶区块 top_article(每条带
    # 「头条」标)→ 列表 depth_list。输出先置顶再列表、按链接去重、保留接口给的顺序,
    # 不按 ctime 重排——头条频道的 depth_list 是编辑顺序(相邻条目时间交错),这正是
    # whatshot cls 路由 depth 子榜与页面不一致的原因,本路由不得重蹈。轮播图不输出:
    # 图片轮播,多数没有标题,混有话题页与广告位;assembled 其余 12 个键页面脚本也不引用。
    items: list[ListItem] = []
    seen: set[str] = set()
    for key, pinned in (("top_article", True), ("depth_list", False)):
        rows = data.get(key)
        if not isinstance(rows, list):
            continue
        for row in rows:
            item = _item(row, pinned)
            if item is None or item.url in seen:
                continue
            seen.add(item.url)
            items.append(item)
    return items


def _clean_text(value: object) -> str | None:
    # 页面用 html-react-parser 渲染标题与摘要;这里去标签、还原实体、合并空白。
    text = _WS_RE.sub(" ", strip_html(value)).strip()
    return text or None


def _item(row: object, pinned: bool) -> ListItem | None:
    if not isinstance(row, dict):
        return None
    item_id = row.get("id")
    title = _clean_text(row.get("title"))
    if not item_id or not title:
        return None
    external = str(row.get("external_link") or "").strip()
    if external:
        url, path = external, "detail"
    else:
        path = _PINNED_PATHS.get(row.get("ctype") or 0, "detail") if pinned else "detail"
        url = f"https://www.cls.cn/{path}/{item_id}"
    return ListItem(
        # 专题/话题条目的 id 加路径前缀,避免与普通文章 id 撞号(当前数据里没有)
        id=str(item_id) if path == "detail" else f"{path}-{item_id}",
        title=title,
        url=url,
        hot=row.get("reading_num"),
        cover=str(row.get("img" if pinned else "image") or "").strip() or None,
        author=_clean_text(row.get("author") if pinned else row.get("source")),
        desc=_clean_text(row.get("brief")),
        timestamp=get_time(row.get("ctime")),  # ctime 秒级,get_time 统一转毫秒
    )
