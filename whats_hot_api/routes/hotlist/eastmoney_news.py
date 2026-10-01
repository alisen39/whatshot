from __future__ import annotations

import re
import time
from datetime import datetime, timedelta, timezone
from html import unescape
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "eastmoney-news"

# board_api 证据(tmp/board_api/eastmoney_news):公开数据、无签名、无 cookie、无需特殊请求头。
# 4 个资讯栏目走 np-listapi 栏目接口(栏目页 newslistbefore.js 调的就是它,取第 1 页 20 条,
# 顺序照接口 order=1);资讯榜是财经栏目页服务端直出的"网友点击排行榜"(div.Wydj,无时间);
# 股吧热榜是股吧首页组件的 gbapi 接口(必须带 plat/version/product,缺了返回"系统繁忙");
# 策略报告走研报中心 dg 接口(qType=2、近 2 年、每页 50,与页面 /report/jg 同一份列表且多给 infoCode)。
# 子榜键 -> (取数方式, 栏目 id, 页面, 展示名)。声明序第一个是默认榜。
_BOARDS: dict[str, tuple[str, int, str, str]] = {
    "finance-ccjdd": ("column", 344, "https://finance.eastmoney.com/a/ccjdd.html", "财经导读"),
    "finance-cywjh": ("column", 345, "https://finance.eastmoney.com/a/cywjh.html", "资讯精华"),
    "stock-cbkjj": ("column", 408, "https://stock.eastmoney.com/a/cbkjj.html", "板块聚焦"),
    "stock-cwjkx": ("column", 398, "https://stock.eastmoney.com/a/cwjkx.html", "最新公告"),
    # 财经晚报:原站栏目 1205 的页面名叫"晚间要闻",第 1 页 20 条里 18 条是"东方财富财经晚报"系列
    # (board_api 推翻性验证后定的口径,tophub 那份是把多家财经晚报按站内搜索混排的)
    "stock-cxwlb": ("column", 1205, "https://stock.eastmoney.com/a/cxwlb.html", "财经晚报（晚间要闻）"),
    "finance-rank": ("rank", 0, "https://finance.eastmoney.com/a/ccjdd.html", "资讯榜（网友点击排行榜）"),
    "guba-hot": ("guba", 0, "https://guba.eastmoney.com/", "股吧热榜"),
    "data-strategy": ("report", 0, "https://data.eastmoney.com/report/strategyreport.jshtml", "策略报告"),
}

type_map: dict[str, str] = {key: meta[3] for key, meta in _BOARDS.items()}

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "东方财富网",
    "description": "东方财富资讯栏目（财经导读、资讯精华、板块聚焦、最新公告）、网友点击排行榜、股吧热榜、研报中心策略报告",
    "link": "https://finance.eastmoney.com/",
    "params": {"type": {"name": "栏目", "type": type_map}},
}

_COLUMN_API = "https://np-listapi.eastmoney.com/comm/web/getNewsByColumns"
# 栏目接口的字段表(newslistbefore.js 写死);缺 req_trace/client/biz 返回 code=0 参数缺失
_COLUMN_FIELDS = "code,showTime,title,mediaName,summary,image,url,uniqueUrl,Np_dst"
_COLUMN_PAGE_SIZE = 20  # 栏目页 __PageSize
_GUBA_API = "https://gbapi.eastmoney.com/operation/api/HotRanking/List"
# 股吧页面请求封装的固定参数(plat/version/product 缺任一个返回"系统繁忙[0000x]");deviceid 非必需
_GUBA_PARAMS = {"pageSize": "50", "condition": "", "plat": "Web", "version": "2022", "product": "Guba"}
_REPORT_API = "https://reportapi.eastmoney.com/report/dg"
_REPORT_DETAIL = "https://data.eastmoney.com/report/zw_strategy.jshtml?encodeUrl="
_JSON_HEADERS = {"Accept": "application/json, text/javascript, */*; q=0.01"}
_HTML_HEADERS = {"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}
_BEIJING = timezone(timedelta(hours=8))
_CODE_IN_URL = re.compile(r"/a/(\d+)\.html")
_TAG_RE = re.compile(r"<[^>]+>")


def _clean(value: Any) -> str:
    """上游字段里的实体与零散标签照 board_api 口径清洗成纯文本。"""
    text = unescape(_TAG_RE.sub("", str(value or "")))
    return re.sub(r"\s+", " ", text).strip()


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    selected = request.query_params.get("type", next(iter(type_map)))
    if selected not in _BOARDS:
        raise ValueError(f"Unknown board '{selected}' for route '{ROUTE_NAME}'")
    kind, column, page, label = _BOARDS[selected]
    if kind == "column":
        rows = await _get_column(column, page, selected, no_cache)
    elif kind == "rank":
        rows = await _get_click_rank(page, no_cache)
    elif kind == "guba":
        rows = await _get_guba(no_cache)
    else:
        rows = await _get_strategy_reports(no_cache)
    return RouterData(
        **ROUTE_META,
        type=label,
        total=len(rows["data"]),
        fromCache=rows["from_cache"],
        updateTime=rows["update_time"],
        data=rows["data"],
    )


def _article_link(code: str, np_dst: str) -> str:
    # newslistbefore.js 的链接规则:财富号文章链到 caifuhao,其余一律 finance.eastmoney.com/a/<code>.html
    # (接口的旧格式 url 字段 /news/<栏目>,<code>.html 不用)
    if np_dst == "CFH":
        return f"http://caifuhao.eastmoney.com/news/{code}"
    return f"https://finance.eastmoney.com/a/{code}.html"


async def _get_column(column: int, page: str, board: str, no_cache: bool) -> dict:
    result = await get(
        url=_COLUMN_API,
        params={
            "client": "web",
            "biz": "web_news_col",
            "column": column,
            "order": "1",
            "page_index": "1",
            "page_size": _COLUMN_PAGE_SIZE,
            # 页面传当前毫秒时间;实测任意值都行,但缺了返回 code=0
            "req_trace": int(time.time() * 1000),
            "fields": _COLUMN_FIELDS,
        },
        no_cache=no_cache,
        response_type="json",
        cache_key=f"eastmoney-news:{board}",
        headers=_JSON_HEADERS,
    )
    payload = result.data if isinstance(result.data, dict) else {}
    if str(payload.get("code")) != "1":
        raise RuntimeError(
            f"Eastmoney column {column} returned code={payload.get('code')} message={payload.get('message')}"
        )
    rows = (payload.get("data") or {}).get("list") or []
    items: list[ListItem] = []
    for row in rows:
        if not isinstance(row, dict) or not row.get("code"):
            continue
        title = _clean(row.get("title"))
        if not title:
            continue
        code = str(row["code"])
        items.append(
            ListItem(
                id=code,
                title=title,
                url=_article_link(code, str(row.get("np_dst") or "")),
                cover=row.get("image") or None,
                author=_clean(row.get("mediaName")) or None,
                desc=_clean(row.get("summary")) or None,
                timestamp=get_time(str(row.get("showTime") or "")[:19]),
            )
        )
    if not items:
        raise RuntimeError(f"Eastmoney column {column} returned no valid rows")
    return {"from_cache": result.from_cache, "update_time": result.update_time, "data": items}


async def _get_click_rank(page: str, no_cache: bool) -> dict:
    result = await get(
        url=page,
        no_cache=no_cache,
        response_type="text",
        cache_key="eastmoney-news:finance-rank",
        headers=_HTML_HEADERS,
    )
    soup = BeautifulSoup(result.data or "", "lxml")
    box = soup.select_one("div.Wydj")
    if box is None:
        raise RuntimeError("Eastmoney finance page has no click-rank box (div.Wydj)")
    items: list[ListItem] = []
    for a in box.select("ul li a[href]"):
        title = _clean(a.get_text(" "))
        if not title:
            continue
        url = urljoin("https://finance.eastmoney.com/", str(a["href"]))
        matched = _CODE_IN_URL.search(url)
        items.append(ListItem(id=matched.group(1) if matched else url, title=title, url=url))
    if not items:
        raise RuntimeError("Eastmoney click-rank box returned no valid rows")
    return {"from_cache": result.from_cache, "update_time": result.update_time, "data": items}


async def _get_guba(no_cache: bool) -> dict:
    result = await get(
        url=_GUBA_API,
        params=_GUBA_PARAMS,
        no_cache=no_cache,
        response_type="json",
        cache_key="eastmoney-news:guba-hot",
        headers=_JSON_HEADERS,
    )
    payload = result.data if isinstance(result.data, dict) else {}
    if payload.get("rc") != 1 or not isinstance(payload.get("re"), list):
        raise RuntimeError(
            f"Eastmoney guba hot list returned rc={payload.get('rc')} message={payload.get('me')}"
        )
    items: list[ListItem] = []
    for row in payload["re"]:
        if not isinstance(row, dict) or not row.get("post_id"):
            continue
        title = _clean(row.get("post_title"))
        if not title:
            continue
        source_id = str(row.get("post_source_id") or "")
        if source_id:
            # 组件链接照写 caifuhao.eastmoney.com/news/<post_source_id>
            url = f"https://caifuhao.eastmoney.com/news/{source_id}"
        else:
            # 没有财富号 id 的普通帖子退回股吧帖子页
            bar = (row.get("post_guba") or {}).get("stockbar_code") or ""
            url = f"https://guba.eastmoney.com/news,{bar},{row['post_id']}.html"
        pics = row.get("post_pic_url") or []
        desc = _clean(row.get("post_abstract") or row.get("post_content"))[:200]
        items.append(
            ListItem(
                id=str(row["post_id"]),
                title=title,
                url=url,
                hot=row.get("post_click_count"),
                cover=pics[0] if pics and isinstance(pics[0], str) else None,
                author=_clean((row.get("post_user") or {}).get("user_nickname")) or None,
                desc=desc or None,
                timestamp=get_time(str(row.get("post_publish_time") or "")[:19]),
            )
        )
    if not items:
        raise RuntimeError("Eastmoney guba hot list returned no valid rows")
    return {"from_cache": result.from_cache, "update_time": result.update_time, "data": items}


def _report_range() -> tuple[str, str]:
    """页面 strategyreport.js 的时间范围:抓取当天(北京时间)往前 2 年。"""
    today = datetime.now(_BEIJING).date()
    try:
        begin = today.replace(year=today.year - 2)
    except ValueError:  # 2 月 29 日
        begin = today.replace(year=today.year - 2, day=28)
    return begin.isoformat(), today.isoformat()


async def _get_strategy_reports(no_cache: bool) -> dict:
    begin, end = _report_range()
    result = await get(
        url=_REPORT_API,
        # 与页面 strategyreport.js 一致;qType=2 是策略报告(3 是宏观研究、4 是券商晨会)
        params={
            "pageSize": "50",
            "beginTime": begin,
            "endTime": end,
            "pageNo": "1",
            "fields": "",
            "qType": "2",
            "orgCode": "",
            "author": "",
        },
        no_cache=no_cache,
        response_type="json",
        cache_key="eastmoney-news:data-strategy",
        headers=_JSON_HEADERS,
    )
    payload = result.data if isinstance(result.data, dict) else {}
    rows = payload.get("data")
    rows = rows if isinstance(rows, list) else []
    items: list[ListItem] = []
    for row in rows:
        if not isinstance(row, dict) or not row.get("encodeUrl"):
            continue
        title = _clean(row.get("title"))
        if not title:
            continue
        org = _clean(row.get("orgSName"))
        researchers = _clean(str(row.get("researcher") or "")).replace(",", "、")
        author = " ".join(x for x in (org, researchers) if x)
        # publishDate 只有日期(0 点);截掉毫秒尾巴,统一转毫秒
        items.append(
            ListItem(
                id=str(row.get("infoCode") or row["encodeUrl"]),
                title=title,
                url=_REPORT_DETAIL + str(row["encodeUrl"]),
                author=author or None,
                timestamp=get_time(str(row.get("publishDate") or "")[:19]),
            )
        )
    if not items:
        raise RuntimeError("Eastmoney strategy report list returned no valid rows")
    return {"from_cache": result.from_cache, "update_time": result.update_time, "data": items}
