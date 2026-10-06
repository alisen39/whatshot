from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urlencode, urljoin

from bs4 import BeautifulSoup
from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get, post

ROUTE_NAME = "exchange-regulator-news"

# 多站点单元,一个路由按"站点-栏目"区分子榜(board_api 证据 tmp/board_api/exchange_regulator_news)。
# 上交所取 sselawsrules2025 新"最新规则"页(tophub 抓的旧页只剩 2 条、停在 2025-03-28);
# 北交所/全国股转同一套 CMS,页面脚本 POST /info/listse.do 渲染列表(tophub 把首页导航抓成了条目);
# 上海证券报是首页信息流缺省"频道排序"(filterIdArray = 首页 __NEXT_DATA__ + indexChannels 两段拼接);
# 中证网是改版后 /xwzx/01/ 的静态 JS 数据文件(置顶 + 按天文件,首屏 15 条);
# 中国货币网按页面缺省 tab「最新」的 channelId;国家金融与发展实验室走旧版研究列表页(服务端渲染)。
# 北交所/股转冷启动会遇到网宿 CC 防护:307 跳回同一地址并 Set-Cookie: C3VK(共享连接池的 cookie
# 罐会自动带上);偶尔直接返回 200 的 JS 跳转页,脚本里明文写着 C3VK 字面值(不需执行 JS),
# 照写后重发一次,见 _fetch_neeq。
_BOARDS: dict[str, str] = {
    "sse-latest-rules": "上交所 · 最新规则",
    "bse-news": "北交所 · 本所动态（本所要闻）",
    "neeq-news": "全国股转 · 股转动态",
    "cnstock-latest": "上海证券报 · 最新消息（首页信息流）",
    "cs-finance": "中证网 · 财经要闻",
    "chinamoney-lpr": "中国货币网 · LPR市场公告",
    "chinamoney-fx": "中国货币网 · 外汇市场公告",
    "chinamoney-bb": "中国货币网 · 本币市场公告",
    "nifd-weekly": "国家金融与发展实验室 · 周报（金融风险周报）",
    "nifd-quarterly": "国家金融与发展实验室 · 季报",
    "nifd-paper": "国家金融与发展实验室 · 学术报告（论文）",
    "nifd-comment": "国家金融与发展实验室 · 研究评价（评论）",
}

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "交易所、监管与证券报",
    "description": "上交所、北交所、全国股转、上海证券报、中证网、中国货币网、国家金融与发展实验室的公告与资讯列表",
    "link": "https://www.sse.com.cn/",
    "params": {"type": {"name": "站点-栏目", "type": _BOARDS}},
}

_HTML_HEADERS = {"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}
_JSON_HEADERS = {"Accept": "application/json, text/javascript, */*; q=0.01"}
_FORM_HEADERS = {"Content-Type": "application/x-www-form-urlencoded"}
_JS_HEADERS = {"Accept": "*/*", "Referer": "https://www.cs.com.cn/xwzx/01/list.html"}

# ---------------------------------------------------------------- 上交所

_SSE_LATEST = "https://www.sse.com.cn/lawandrules/sselawsrules2025/latest/"
_SSE_CODE = re.compile(r"c_(\d+_\d+)\.shtml")

# ---------------------------------------------------------------- 北交所 / 全国股转

# 子榜 -> (站点, 节点 id, 页面脚本额外带的表单字段)。节点 id 取自 /news/important_news.html
_NEEQ_SITES: dict[str, tuple[str, str, dict[str, str]]] = {
    "bse-news": ("https://www.bse.cn", "1289", {}),
    "neeq-news": ("https://www.neeq.com.cn", "94", {"siteId": "1"}),
}
_NEEQ_FIELDS = ("infoId", "title", "metaDescription", "linkUrl", "htmlUrl", "publishDate")
# 两站前面是网宿 WAF:httpx 缺省 UA 直接 403(board_api 的 curl 证据也带 Chrome UA),必须带浏览器 UA
_NEEQ_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/145.0.0.0 Safari/537.36"
)
# CC 防护偶尔直接回 200 的 JS 跳转页,脚本里明文写着 document.cookie="C3VK=<字面值>; ..."
_C3VK_RE = re.compile(r'cookie\s*=\s*"C3VK=([0-9A-Za-z]+)')

# ---------------------------------------------------------------- 上海证券报

_CNSTOCK_HOME = "https://www.cnstock.com/"
_CNSTOCK_API = "https://api.cnstock.com/www/index"
# cnstock-client-type 是页面 axios 拦截器加的,缺了返回 code=10304「未登录」
_CNSTOCK_HEADERS = {
    "cnstock-client-type": "01",
    "Content-Type": "application/json",
    "Accept": "application/json, text/plain, */*",
    "Origin": "https://www.cnstock.com",
    "Referer": "https://www.cnstock.com/",
}
# 页面 _app 脚本的链接规则(forwardType -> 路径);ft=6 是外链卡片,直接用 link 字段
_CNSTOCK_LINKS = {
    4: "/commonDetail/{contId}",
    5: "/videoDetail/{contId}",
    7: "/atlasDetail/{contId}",
    8: "/liveDetail/{contId}",
    32: "/liveDetail/{contId}",
    9: "/topicDetail/{contId}",
    13: "/activityDetail/{contId}",
    47: "/topicDetail/01/{contId}",
    48: "/topicDetail/02/{contId}",
}
_CNSTOCK_SLOGAN = "权威、专业、价值 尽在上海证券报客户端"

# ---------------------------------------------------------------- 中证网

_CS_BASE = "https://www.cs.com.cn/js/9/"
_CS_FIRST_SCREEN = 15  # 列表页 simpleLoadMore({count: 15}):首屏 15 条
_CS_MI4_RE = re.compile(r"MI4_PAGE_ARTICLE\s*=\s*(\[.*\])", re.DOTALL)
_CS_INDEX_RE = re.compile(r"PAGE_INDEX_MAP\s*=\s*(\{.*?\})\s*;?\s*$", re.DOTALL | re.MULTILINE)
_CS_DETAIL_ID = re.compile(r"detail_(\d+)\.html")
_CS_JNZ_ID = re.compile(r"jnzstatic\.cs\.com\.cn/.*/htmlInfo/(\d+)\.html")

# ---------------------------------------------------------------- 中国货币网

_CM_SITE = "https://www.chinamoney.com.cn"
# 子榜 -> (接口, channelId, 页面)。channelId 是页面缺省 tab「最新」的值(页面脚本用
# /chinese/cxsymb/index.html 的 path->id 表换算):外汇 scgg-whscgg=2834;本币「最新」=
# 三个子栏目 2839,2840,2841 合并(与「全部」2838 逐条相同);LPR 市场公告 bklprmkn2=3686
_CM_BOARDS: dict[str, tuple[str, str, str]] = {
    "chinamoney-lpr": ("contentsinshorttime", "3686", "/chinese/bklpr/"),
    "chinamoney-fx": ("contents", "2834", "/chinese/scgg-whscgg/"),
    "chinamoney-bb": ("contents", "2839,2840,2841", "/chinese/scggbbscgg/"),
}

# ---------------------------------------------------------------- 国家金融与发展实验室

_NIFD_SITE = "http://www.nifd.cn"
# 研究列表页分类 guid(取自 /Research/Index 的分类导航)
_NIFD_CATEGORIES = {
    "nifd-weekly": "7a6a826d-b525-42aa-b550-4236e524227f",  # 金融风险周报
    "nifd-quarterly": "b66aa691-87ee-4bfe-ac6b-2460386166ee",  # 季报
    "nifd-paper": "e6a6d3a5-4bda-4739-9765-e4e41c900bcc",  # 论文(学术报告)
    "nifd-comment": "3333d2af-91d6-429b-be83-28b92f31b6d7",  # 评论(研究评价)
}
_NIFD_DETAILS_ID = re.compile(r"/Details/(\d+)")


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    selected = request.query_params.get("type", next(iter(_BOARDS)))
    if selected not in _BOARDS:
        raise ValueError(f"Unknown board '{selected}' for route '{ROUTE_NAME}'")
    if selected == "sse-latest-rules":
        rows = await _fetch_sse(no_cache)
    elif selected in _NEEQ_SITES:
        rows = await _fetch_neeq(selected, no_cache)
    elif selected == "cnstock-latest":
        rows = await _fetch_cnstock(no_cache)
    elif selected == "cs-finance":
        rows = await _fetch_cs(no_cache)
    elif selected in _CM_BOARDS:
        rows = await _fetch_chinamoney(selected, no_cache)
    else:
        rows = await _fetch_nifd(selected, no_cache)
    return RouterData(
        **ROUTE_META,
        type=_BOARDS[selected],
        total=len(rows["data"]),
        fromCache=rows["from_cache"],
        updateTime=rows["update_time"],
        data=rows["data"],
    )


def _finish(result: Any, items: list[ListItem], board: str) -> dict:
    if not items:
        raise RuntimeError(f"exchange-regulator-news {board} returned no valid rows")
    return {"from_cache": result.from_cache, "update_time": result.update_time, "data": items}


async def _fetch_sse(no_cache: bool) -> dict:
    result = await get(
        url=_SSE_LATEST,
        no_cache=no_cache,
        response_type="text",
        cache_key="exchange-regulator-news:sse-latest-rules",
        headers=_HTML_HEADERS,
    )
    soup = BeautifulSoup(result.data or "", "lxml")
    items: list[ListItem] = []
    for dd in soup.select("div.sse_list_1 dl dd"):
        a = dd.select_one("a[href]")
        if a is None:
            continue
        href = urljoin(_SSE_LATEST, str(a.get("href")))
        title = str(a.get("title") or "").strip() or a.get_text(" ", strip=True)
        if not title:
            continue
        matched = _SSE_CODE.search(href)
        span = dd.select_one("span")
        items.append(
            ListItem(
                id=matched.group(1) if matched else href,  # c_<日期>_<编号>
                title=title,
                url=href,
                timestamp=get_time(span.get_text(strip=True)) if span else None,
            )
        )
    return _finish(result, items, "sse-latest-rules")


def _neeq_form(site: str, node: str, extra: dict[str, str]) -> str:
    # 与页面 neeqNews.min.js 相同的表单(jQuery 把数组序列化成 nodeIds[]、needFields[])
    pairs: list[tuple[str, str]] = [
        ("page", "0"),
        ("pageSize", "20"),
        ("keywords", ""),
        ("startTime", ""),
        ("endTime", ""),
        ("nodeIds[]", node),
        *(("needFields[]", field) for field in _NEEQ_FIELDS),
        *extra.items(),
    ]
    return urlencode(pairs)


def _parse_jsonp(text: str) -> Any:
    start, end = text.find("("), text.rfind(")")
    if start < 0 or end <= start:
        raise ValueError("not a JSONP payload")
    return json.loads(text[start + 1 : end])


async def _fetch_neeq(board: str, no_cache: bool) -> dict:
    site, node, extra = _NEEQ_SITES[board]
    url = f"{site}/info/listse.do"
    headers = {
        "Accept": _JSON_HEADERS["Accept"],
        "User-Agent": _NEEQ_UA,
        "X-Requested-With": "XMLHttpRequest",
        "Referer": f"{site}/news/important_news.html",
        "Content-Type": _FORM_HEADERS["Content-Type"],
    }
    body = _neeq_form(site, node, extra)
    cache_key = f"exchange-regulator-news:{board}"
    result = await post(url=url, headers=headers, body=body, no_cache=no_cache, response_type="text", cache_key=cache_key)
    text = result.data if isinstance(result.data, str) else ""
    try:
        payload = _parse_jsonp(text)
    except (ValueError, json.JSONDecodeError):
        payload = None
    if payload is None:
        # CC 防护偶尔跳过 307、直接回 200 的 JS 页:C3VK 字面值就写在脚本里(服务器给定,
        # 不需执行 JS 计算),照写进 Cookie 头重发一次
        challenge = _C3VK_RE.search(text[:2000])
        if challenge is None:
            raise RuntimeError(
                f"exchange-regulator-news {board} returned an unexpected page (CC challenge may have changed): {text[:150]}"
            )
        result = await post(
            url=url,
            headers={**headers, "Cookie": f"C3VK={challenge.group(1)}"},
            body=body,
            no_cache=True,
            response_type="text",
            cache_key=f"{cache_key}:retry",
        )
        text = result.data if isinstance(result.data, str) else ""
        try:
            payload = _parse_jsonp(text)
        except (ValueError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"exchange-regulator-news {board} returned a non-list payload: {text[:150]}") from exc
    try:
        rows = payload[0]["data"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"exchange-regulator-news {board} returned a non-list payload: {text[:150]}") from exc
    items: list[ListItem] = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        link = str(row.get("linkUrl") or "").strip() or str(row.get("htmlUrl") or "").strip()
        if not link:
            continue
        items.append(
            ListItem(
                id=str(row.get("infoId") or link),
                title=str(row.get("title") or "").replace("\\n", "").strip(),
                url=urljoin(f"{site}/", link),
                desc=str(row.get("metaDescription") or "").strip() or None,
                timestamp=get_time(str(row.get("publishDate") or "")[:19]),
            )
        )
    return _finish(result, items, board)


def _cnstock_timestamp(share: dict) -> int | None:
    date_info = share.get("dateInfo") or {}
    if not date_info.get("year"):
        return None
    # pubTime 是"1小时前"这类相对时间,不用;dateInfo 是绝对时间
    text = (
        f"{date_info['year']}-{date_info.get('month')}-{date_info.get('day')} "
        f"{date_info.get('hour')}:{date_info.get('minute')}"
    )
    return get_time(text)


async def _fetch_cnstock(no_cache: bool) -> dict:
    board = "cnstock-latest"
    home = await get(
        url=_CNSTOCK_HOME,
        no_cache=no_cache,
        response_type="text",
        cache_key=f"exchange-regulator-news:{board}:home",
        headers=_HTML_HEADERS,
    )
    match = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', home.data or "", re.DOTALL)
    if match is None:
        raise RuntimeError("exchange-regulator-news cnstock home has no __NEXT_DATA__ (page structure changed)")
    try:
        home_filter = ((json.loads(match.group(1)).get("props") or {}).get("pageProps") or {}).get("data", {}).get("filterIdArray") or []
    except json.JSONDecodeError as exc:
        raise RuntimeError("exchange-regulator-news cnstock home __NEXT_DATA__ is not valid JSON") from exc
    # 页面缺省「频道排序」:先取 indexChannels 的 filterIdArray 接在首页后面,
    # 信息流就不再重复上方区块已展示的文章(「时间排序」传 [] 会多出专题卡,不用)
    channels = await post(
        url=f"{_CNSTOCK_API}/indexChannels",
        body={},
        headers=_CNSTOCK_HEADERS,
        no_cache=no_cache,
        response_type="json",
        cache_key=f"exchange-regulator-news:{board}:channels",
    )
    channels_payload = channels.data if isinstance(channels.data, dict) else {}
    if channels_payload.get("code") != 200:
        raise RuntimeError(f"exchange-regulator-news cnstock indexChannels returned {str(channels_payload)[:150]}")
    channel_filter = (channels_payload.get("data") or {}).get("filterIdArray") or []
    result = await post(
        url=f"{_CNSTOCK_API}/waterfallPage",
        body={"filterIdArray": [*home_filter, *channel_filter], "pageNum": 1},
        headers=_CNSTOCK_HEADERS,
        no_cache=no_cache,
        response_type="json",
        cache_key=f"exchange-regulator-news:{board}",
    )
    payload = result.data if isinstance(result.data, dict) else {}
    if payload.get("code") != 200:
        raise RuntimeError(f"exchange-regulator-news cnstock waterfallPage returned {str(payload)[:150]}")
    items: list[ListItem] = []
    for row in (payload.get("data") or {}).get("list") or []:
        if not isinstance(row, dict):
            continue
        cont_id = str(row.get("contId") or "")
        forward_type = row.get("forwardType")
        if forward_type == 6 and row.get("link"):
            url = str(row["link"])
        elif forward_type in _CNSTOCK_LINKS and cont_id:
            url = _CNSTOCK_HOME.rstrip("/") + _CNSTOCK_LINKS[forward_type].format(contId=cont_id)
        else:
            continue  # 频道、标签等导航卡片不是条目
        share = row.get("shareInfo") or {}
        summary = str(share.get("summary") or "").strip()
        items.append(
            ListItem(
                id=cont_id or url,
                title=str(row.get("name") or "").strip(),
                url=url,
                mobileUrl=share.get("shareUrl") or None,
                cover=row.get("pic") or None,
                author=row.get("author") or None,
                # 客户端宣传语不是摘要
                desc=None if not summary or summary == _CNSTOCK_SLOGAN else summary,
                timestamp=_cnstock_timestamp(share),
            )
        )
    return _finish(result, items, board)


def _mi4_array(text: str, name: str) -> list[dict[str, Any]]:
    match = _CS_MI4_RE.search(text)
    if match is None:
        raise RuntimeError(f"exchange-regulator-news cs data file {name} has no MI4_PAGE_ARTICLE (format changed)")
    rows = json.loads(match.group(1))
    return rows if isinstance(rows, list) else []


async def _fetch_cs(no_cache: bool) -> dict:
    board = "cs-finance"
    top = await get(
        url=f"{_CS_BASE}mi4_sub_articles_top.js",
        no_cache=no_cache,
        response_type="text",
        cache_key=f"exchange-regulator-news:{board}:top",
        headers=_JS_HEADERS,
    )
    rows: list[dict[str, Any]] = list(_mi4_array(top.data or "", "mi4_sub_articles_top.js"))
    guide = await get(
        url=f"{_CS_BASE}mi4_page_articles_guide.js",
        no_cache=no_cache,
        response_type="text",
        cache_key=f"exchange-regulator-news:{board}:guide",
        headers=_JS_HEADERS,
    )
    match = _CS_INDEX_RE.search(guide.data or "")
    if match is None:
        raise RuntimeError("exchange-regulator-news cs guide file has no PAGE_INDEX_MAP (format changed)")
    index = json.loads(match.group(1))
    n = 1
    latest = guide  # updateTime 取最后一次成功请求
    # 页面按索引顺序(最新一天在前)逐个取按天的数据文件,跳过 isTop=1(已在置顶文件里),首屏 15 条
    while len(rows) < _CS_FIRST_SCREEN and str(n) in index and n <= 10:
        name = index[str(n)]
        latest = await get(
            url=f"{_CS_BASE}{name}",
            no_cache=no_cache,
            response_type="text",
            cache_key=f"exchange-regulator-news:{board}:day{n}",
            headers=_JS_HEADERS,
        )
        rows += [row for row in _mi4_array(latest.data or "", name) if row.get("isTop") != 1]
        n += 1
    items: list[ListItem] = []
    seen: set[str] = set()
    for row in rows[:_CS_FIRST_SCREEN]:
        url = str(row.get("external_link") or "").strip() or str(row.get("url") or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        # 站内文章 detail_<id>.html;外链到金牛座的两套编号不混,加 jnz- 前缀
        site_match = _CS_DETAIL_ID.search(url)
        jnz_match = _CS_JNZ_ID.search(url)
        item_id = site_match.group(1) if site_match else (f"jnz-{jnz_match.group(1)}" if jnz_match else url)
        items.append(
            ListItem(
                id=item_id,
                title=str(row.get("title") or "").strip(),
                url=url,
                author=row.get("pubAuthor") or None,
                desc=row.get("miSummary") or None,
                cover=row.get("miCover43") or row.get("miCover169") or None,
                timestamp=get_time(str(row.get("pubDateShow") or row.get("pub_date") or "")[:16]),
            )
        )
    return _finish(latest, items, board)


async def _fetch_chinamoney(board: str, no_cache: bool) -> dict:
    path, channel, page = _CM_BOARDS[board]
    result = await post(
        url=f"{_CM_SITE}/ags/ms/cm-s-notice-query/{path}",
        headers={**_JSON_HEADERS, **_FORM_HEADERS, "X-Requested-With": "XMLHttpRequest", "Referer": _CM_SITE + page},
        body=urlencode([("pageNo", "1"), ("pageSize", "15"), ("channelId", channel)]),
        no_cache=no_cache,
        response_type="json",
        cache_key=f"exchange-regulator-news:{board}",
    )
    payload = result.data if isinstance(result.data, dict) else {}
    if (payload.get("head") or {}).get("rep_code") != "200" or not isinstance(payload.get("records"), list):
        raise RuntimeError(f"exchange-regulator-news {board} returned {str(payload)[:150]}")
    items: list[ListItem] = []
    for row in payload["records"]:
        if not isinstance(row, dict):
            continue
        # 页面:有 url 用 url,否则 draftPath(页面会再加 #cp=<栏目> 导航锚点,这里不带)
        link = str(row.get("url") or "").strip() or str(row.get("draftPath") or "").strip()
        if not link:
            continue
        items.append(
            ListItem(
                id=str(row.get("contentId") or link),
                title=str(row.get("title") or "").strip(),
                url=urljoin(f"{_CM_SITE}/", link),
                timestamp=get_time(str(row.get("releaseDate") or "")[:10]),
            )
        )
    return _finish(result, items, board)


async def _fetch_nifd(board: str, no_cache: bool) -> dict:
    result = await get(
        url=f"{_NIFD_SITE}/Research?categoryGuid={_NIFD_CATEGORIES[board]}",
        no_cache=no_cache,
        response_type="text",
        cache_key=f"exchange-regulator-news:{board}",
        headers=_HTML_HEADERS,
    )
    soup = BeautifulSoup(result.data or "", "lxml")
    items: list[ListItem] = []
    for div in soup.select("div.qr-main-item"):
        a = div.select_one("h4 a[href]")
        if a is None:
            continue
        title = re.sub(r"\s+", " ", a.get_text(" ", strip=True))
        if not title:
            continue
        href = urljoin(f"{_NIFD_SITE}/", str(a.get("href")))
        matched = _NIFD_DETAILS_ID.search(href)
        span = div.select_one("span")
        # 日期是 [2026年09月28日] 形式,只有日期(北京时间 0 点)
        date_text = re.sub(r"[年月]", "-", re.sub(r"[\[\]\s]", "", span.get_text())).rstrip("日") if span else ""
        items.append(
            ListItem(
                id=matched.group(1) if matched else href,
                title=title,
                url=href,
                timestamp=get_time(date_text) if date_text else None,
            )
        )
    return _finish(result, items, board)
