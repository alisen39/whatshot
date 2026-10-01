"""新华网频道列表(www.news.cn 新版 CMS 的频道页数据文件 ds_<id>.json)。

board_api 单元 `tmp/board_api/xinhua_channels` 的 1:1 迁移,证据见该目录 README 与
`analysis_report.md`、`verify/page_vs_json.md`、`verify/phase2_page_vs_json.md`。
一期 7 个子榜 + 二期(seg78 批次 a6)5 个子榜,数据源同一套,共 12 个子榜:

- 每个频道页的列表容器带 `data="datasource:<id>" datatype="ds" preview="ds_"`,
  数据文件是 `<频道页目录>/ds_<id>.json`,公开、无签名、无 cookie,无查询参数,
  每个子榜 1 个请求(header_matrix 实测不需要任何请求头;这里照 board_api 口径
  带 Accept,Referer/UA/cookie 都不需要)。
- 文件顺序就是页面顺序:频道页首屏由服务端按该文件渲染,"加载更多"在前端对同一
  文件切片(dw.js 的 Xhwpage)。只取页面首屏的行数(时政/国际 50、网评/地方/科技 15、
  财经滚动 20、军事 64;二期 jsxw 13、新华时评 20、新华网评 15、最新播报 15、钟华论 40)。
- tophub 的财经/军事节点抓的是旧版 CMS 的 nodeart 列表(已停更 2024-12-31/2024-07-10),
  这里照 board_api 改取新版频道页的"新财经滚动"与 milpro 电脑版首屏 64 行,与 tophub
  重合预期为 0;"即时新闻"旧静态页 jsxw.htm 停在 2024-04-16,不提供(二期 home-latest
  是首页"最新播报",tophub 另一节点,不是它的继任)。

字段口径:
- id:单链接行用 contentId;一行多链接拆出的条目没有独立 contentId,用文章 URL。
- 一行多链接(linkUrls 多个)按页面显示拆成多条:标签链接(以"|"结尾或就是"专题",
  指向专题页)与"全文"这类附属链接跳过;拆条后每条只取链接文字当标题。
- 同一篇文章在首屏出现两次只留第一次(按 URL 去重)。
- timestamp:稿件型行(MultiMedia)取 publishTime(北京时间)转毫秒;链接型行(Link)的
  publishTime 是编辑把链接放进列表的时间,实测比文章发布晚 9~10 小时,不是内容发布
  时间,留空。
- hot:列表不提供,恒为空。
"""

from __future__ import annotations

import html
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urljoin

from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "xinhua-channels"

# 子榜 -> (标签, 频道页 base URL, datasource id, 首屏行数)。
# datasource id 取自频道页列表容器的 data 属性;首屏行数取自页面模板
# (index.js/worldpro.js 的 startSize、index_v1.js 的 pageSize 等),频道页改版时两处
# 都要到页面里重找。声明序第一个(politics)是默认榜。
_BOARDS: dict[str, tuple[str, str, str, int]] = {
    "politics": ("时政", "https://www.news.cn/politics/", "a6d618872de143bdafa2556915a7ae12", 50),
    "world": ("国际", "https://www.news.cn/world/", "8d5294ed513c4779af6242a3623aa27b", 50),
    "comments": ("网评", "https://www.news.cn/comments/", "8e0f870f8f8b4643a239608debe7f2ee", 15),
    "local": ("地方联播", "https://www.news.cn/local/", "5c5939c2f07b4d9c96de44dad32eadc8", 15),
    "tech": ("科技", "https://www.news.cn/tech/", "fd79514d92f34849bc8baef7ce3d5aae", 15),
    # 财经频道页已把旧 nodeart"滚动新闻"(nid 115033,停在 2024-12-31)换成数据文件"新财经滚动"
    "fortune": ("财经", "https://www.news.cn/fortune/", "1e491dadc8944459b71b7ab13422623d", 20),
    # 电脑版 milpro/index.htm 的瀑布流就是"新闻"列表的前 64 行(推翻性验证更正)
    "mil": ("军事", "https://www.news.cn/milpro/", "efa406de9b714538a958d4a20a80ecf3", 64),
    # ---- 二期补充(seg78 批次 a6 并入,同一数据源,解析逻辑不变) ----
    # 首屏行数:jsxw 是 index_v1.js 的 startNumber 13;新华时评是 2023homepro_pc_observe.js
    # 的 pageSize 20;新华网评是 index_v1.js 的 pageSize 15(服务端渲染首屏都与之一致);
    # 最新播报文件只有 15 行;钟华论 40 行全部渲染。
    "world-jsxw": ("国际即时新闻", "https://www.news.cn/world/jsxw/", "29089f6bdec84f03b12804d9fe4897be", 13),
    "depth-xhsp": ("新华时评", "https://www.news.cn/depthobserve/", "1636c5be477b4b519c0a4e969cfd28ee", 20),
    "comments-wpyc": ("新华网评", "https://www.news.cn/comments/wpyc/", "2d7f116cc1f34730974912b1512cb10d", 15),
    "home-latest": ("滚动新闻（首页最新播报）", "https://www.news.cn/", "bbc6736b83a14fbb9caf24d78f9aab7f", 15),
    # 钟华论页有两个同序的数据文件:顶部轮播 d95d3173…(只有标题图)与下方列表 42a90569…
    # (带配图与导语),取列表那个。
    "comments-zhonghualun": (
        "钟华论",
        "https://www.news.cn/comments/plldzt/zhonghualun/",
        "42a905699ddb4f5298955c4c1388d868",
        40,
    ),
}

type_map: dict[str, str] = {key: label for key, (label, _, _, _) in _BOARDS.items()}

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "新华网",
    "description": "新华网各频道页的主列表：时政、国际、网评、地方联播、科技、财经滚动、军事；国际即时新闻、新华时评、新华网评、首页最新播报、钟华论。",
    "link": "https://www.news.cn/",
    "params": {
        "type": {
            "name": "频道",
            "type": type_map,
        },
    },
}

# header_matrix 实测不需要任何请求头,照 board_api 口径带 Accept;不含 Referer/UA/cookie
_HEADERS = {"Accept": "application/json, text/javascript, */*; q=0.01"}

_BEIJING = timezone(timedelta(hours=8))

# 一行多链接里不单独成条的附属链接(如"标题 全文"里的"全文"),跳过
_ATTACHED_LINKS = {"全文"}
# 标签链接:以"|"结尾,或就是"专题"这类栏目名,指向专题页而不是文章,跳过
_TAG_LINKS = {"专题"}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    type_param = request.query_params.get("type", "politics")
    if type_param not in _BOARDS:
        raise ValueError(f"Unknown board '{type_param}' for route '{ROUTE_NAME}'")
    label, page, datasource, first_screen = _BOARDS[type_param]
    url = f"{page}ds_{datasource}.json"
    result = await get(url=url, headers=_HEADERS, no_cache=no_cache, response_type="json")
    payload = result.data if isinstance(result.data, dict) else {}
    rows = payload.get("datasource")
    # 数据文件异常壳(非 dict、没有 datasource 数组、空数组)按错误处理,不静默降级为空榜
    if not isinstance(rows, list) or not rows:
        raise RuntimeError(f"Xinhua channels {type_param} datasource has no rows ({url})")
    items = _parse_items(rows[:first_screen], page)
    if not items:
        raise RuntimeError(f"Xinhua channels {label} parsed no items")
    return RouterData(
        **ROUTE_META,
        type=label,
        total=len(items),
        fromCache=result.from_cache,
        updateTime=result.update_time,
        data=items,
    )


def _text(fragment: str) -> str:
    """行内 HTML(title/summary 是 <a> 片段)取页面显示的文字。"""
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", fragment or ""))).strip()


def _publish_time_ms(value: object) -> int | None:
    """publishTime(北京时间)→ Unix 毫秒;缺失或格式不对返回 None。"""
    if not isinstance(value, str):
        return None
    try:
        dt = datetime.strptime(value.strip(), "%Y-%m-%d %H:%M:%S").replace(tzinfo=_BEIJING)
    except ValueError:
        return None
    return int(dt.timestamp() * 1000)


def _row_links(row: dict) -> list[tuple[str, str]]:
    """一行拆成 (标题, 链接) 列表。

    链接型行(Link)的 title 可能是一串 <a>:"专题 | 标题1 标题2"、"标题 全文"、"标题A 标题B"。
    除了标签链接(以"|"结尾或就是"专题")和"全文"这类附属链接(跳过),每个链接都是一篇
    独立文章,拆成多条(推翻性验证发现合成一条会丢掉文章);拆出来的标题是页面上的链接
    文字,有时只有半句(如"特朗普拒绝"),与页面显示一致。
    """
    links = [
        (str(x.get("linkTitle") or "").strip(), str(x.get("linkUrl") or "").strip())
        for x in row.get("linkUrls") or []
        if isinstance(x, dict)
    ]
    links = [(t, u) for t, u in links if t and u]
    if len(links) <= 1:
        # 单链接行的 title 可能带 HTML,按页面显示的文字取
        title = _text(row.get("title") or row.get("showTitle") or "")
        link = (row.get("publishUrl") or "").strip()
        return [(title, link)] if title and link else []
    out: list[tuple[str, str]] = []
    for title, url in links:
        if title.endswith(("|", "｜")) or title in _TAG_LINKS:
            continue
        if title in _ATTACHED_LINKS and out:
            continue
        out.append((title, url))
    return out


def _parse_items(rows: list, page: str) -> list[ListItem]:
    items: list[ListItem] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        links = _row_links(row)
        if not links:
            continue
        images = row.get("titleImages") or []
        image = images[0].get("imageUrl") if images and isinstance(images[0], dict) else None
        # 链接型行的 publishTime 是编辑放进列表的时间(实测晚 9~10 小时),不是内容发布
        # 时间,timestamp 留空;稿件型行(MultiMedia)的 publishTime 与页面发布时间一致
        is_link_row = row.get("contentType") == "Link"
        for i, (title, link) in enumerate(links):
            url = urljoin(page, link)
            if url in seen:  # 编辑偶尔把同一篇放进列表两次(页面也显示两次),只留第一次
                continue
            seen.add(url)
            single = len(links) == 1
            items.append(
                ListItem(
                    # 拆条没有独立 contentId,用文章 URL 当稳定标识;名次不参与 id
                    id=(row.get("contentId") or url) if single else url,
                    title=title,
                    url=url,
                    mobileUrl=url,
                    # 封面只有行首条带(拆出的子链接共用一行的图没有依据),相对地址按频道页补全
                    cover=urljoin(page, image) if image and i == 0 else None,
                    author=(row.get("author") or "").strip() or None,
                    desc=_text(row.get("summary") or "") if single else None,
                    timestamp=None if is_link_row else _publish_time_ms(row.get("publishTime")),
                )
            )
    return items
