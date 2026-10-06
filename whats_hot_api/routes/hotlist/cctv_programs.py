"""央视网栏目：电视节目往期列表、新闻频道（多 type 单路由）。

迁移自 board_api cctv_programs 单元（11 个已完成榜；NBA 热门资讯已因上游不可达下线），两类数据源都是原站页面自己用的数据：
- 电视节目（tv.cctv.com/lm/<栏目>/，7 个子榜）：栏目页 JS 调的官方接口
  ``api.cntv.cn/NewVideo/getVideoListByColumn?id=<栏目 id>&n=<条数>&sort=desc&p=1
  &mode=<类型>&serviceId=tvcctv``，不带 cb 回调直接回 JSON。栏目 id 照栏目页源码的
  ``topicID`` / ``lmtopId`` 变量（今日说法页注释里的另一个 id 是百家讲坛，不能用）；
  mode 与条数照栏目页缺省显示的那一栏（``li.cur`` 的 ``data-num``）：0=完整视频/整期、
  1=精彩片段、2=全部视频。每周质量报告只有"全部视频"一栏（mode=2）；经济信息联播栏目页
  是按日期查的日历页、没有往期列表，照 board_api 已认可口径取整期列表 mode=0；
  经济半小时取"往期节目"一栏（mode=0、n=10）。serviceId 必需（去掉返回
  errcode=1105"无效服务"）；接口对 UA 不敏感（python-httpx 缺省 UA 实测 200）
- 新闻频道（news.cctv.com/<china|world|law>/，3 个子榜）：频道页顶部头图（静态 HTML 的
  ``.xinwen18886_ind01 #slide .silde``，编辑放的，常在列表里也可能不在）+ 列表数据文件
  ``news.cctv.com/2019/07/gaiban/cmsdatainterface/page/<频道>_1.jsonp``（频道页源码
  jsonpurl 声明，每个文件 80 条，页面每次显示 20 条是前端切片）。头图在列表里时留页面
  先出现的位置（头图优先），不在列表里时该条没有发布时间（timestamp 留空，不从链接日期编造）
- 节目 timestamp 用播出时间 ``time``（北京时间，栏目页显示的就是它），缺失时用上线时间
  ``focus_date``（毫秒）；新闻用 ``focus_date``。统一毫秒输出

不做：致富经（2023-05-21 改版更名为《共富经》，原站另建新栏目、旧栏目页不跳转、栏目信息
接口标"已停播"，列表停在 2023-05-19；board_api README 与推翻性验证修正记录维持不做）。
"""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "cctv-programs"

_TYPE_MAP: dict[str, str] = {
    "news-china": "国内新闻",
    "news-world": "国际新闻",
    "news-law": "法治新闻",
    "tv-jrsf": "今日说法",
    "tv-xinwen1j1": "新闻1+1",
    "tv-xwdc": "新闻调查",
    "tv-mzzlbg": "每周质量报告",
    "tv-jdft": "焦点访谈",
    "tv-jjxxll": "经济信息联播",
    "tv-jjbxs": "经济半小时",
}

_DEFAULT_TYPE = "news-china"

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "央视网",
    "description": "央视网：今日说法、新闻1+1、焦点访谈等节目往期列表，国内 / 国际 / 法治新闻。",
    "link": "https://www.cctv.com/",
    "params": {"type": {"name": "栏目", "type": _TYPE_MAP}},
}

_BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"
)
_HEADERS = {"User-Agent": _BROWSER_UA, "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"}
_JSON_ACCEPT = "application/json, text/javascript, */*; q=0.01"
_HTML_ACCEPT = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"

# 电视节目：子榜键 -> (栏目页, 栏目 id, mode, 条数)；mode / 条数照栏目页缺省显示的列表
_PROGRAMS: dict[str, tuple[str, str, int, int]] = {
    "tv-jrsf": ("https://tv.cctv.com/lm/jrsf/", "TOPC1451464665008914", 0, 20),
    "tv-xinwen1j1": ("https://tv.cctv.com/lm/xinwen1j1/", "TOPC1451559066181661", 0, 20),
    "tv-xwdc": ("https://tv.cctv.com/lm/xwdc/", "TOPC1451558819463311", 0, 20),
    "tv-mzzlbg": (  # 只有"全部视频"一栏
        "https://tv.cctv.com/lm/mzzlbg/",
        "TOPC1451558650605123",
        2,
        20,
    ),
    "tv-jdft": ("https://tv.cctv.com/lm/jdft/", "TOPC1451558976694518", 0, 20),
    # 经济信息联播栏目页是按日期查的日历页（mode=2&bd=日期），没有往期列表；取整期列表 mode=0
    "tv-jjxxll": ("https://tv.cctv.com/lm/jjxxll/", "TOPC1451533782742171", 0, 20),
    # "往期节目"一栏 mode=0&n=10
    "tv-jjbxs": ("https://tv.cctv.com/lm/jjbxs/", "TOPC1451533652476962", 0, 10),
}
_VIDEO_API = "https://api.cntv.cn/NewVideo/getVideoListByColumn"

# 新闻频道：子榜键 -> (频道页, 数据文件名)；数据文件名来自频道页源码 jsonpurl
_NEWS_PAGES: dict[str, tuple[str, str]] = {
    "news-china": ("https://news.cctv.com/china/", "china"),
    "news-world": ("https://news.cctv.com/world/", "world"),
    "news-law": ("https://news.cctv.com/law/", "law"),
}
_NEWS_DATA_URL = "https://news.cctv.com/2019/07/gaiban/cmsdatainterface/page/{name}_1.jsonp"

_JSONP_CALL = re.compile(r"\s*[\w$.]+\((.*)\)\s*;?\s*$", re.DOTALL)


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    board = request.query_params.get("type", _DEFAULT_TYPE)
    if board not in _TYPE_MAP:
        raise ValueError(f"Unknown board '{board}' for route '{ROUTE_NAME}'")
    if board in _PROGRAMS:
        result, link, items = await _get_program(board, no_cache)
    else:
        result, link, items = await _get_news(board, no_cache)
    if not items:
        raise RuntimeError(f"cctv-programs board '{board}' returned no items")
    return RouterData(
        **{**ROUTE_META, "link": link},
        type=_TYPE_MAP[board],
        total=len(items),
        fromCache=result.from_cache,
        updateTime=result.update_time,
        data=items,
    )


# ---------------------------------------------------------------- 条目组装


def _clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _https(url: str) -> str:
    return "https:" + url if url.startswith("//") else url


def _id_from_url(url: str) -> str:
    match = re.search(r"/((?:ARTI|VIDE|PHOA)\w+)\.shtml", url)
    return match.group(1) if match else url


def _item(row: dict[str, Any], time_key: str) -> ListItem | None:
    url = str(row.get("url") or "").strip()
    title = _clean_text(row.get("title"))
    if not url or not title:
        return None
    return ListItem(
        id=str(row.get("id") or row.get("guid") or url),
        title=title,
        url=url,
        mobileUrl=url,  # 原站没有单独的移动链接
        cover=_https(str(row.get("image") or "")) or None,
        desc=(_clean_text(row.get("brief")) or "")[:500] or None,
        # 节目用播出时间 time（北京时间），缺失时用上线时间 focus_date（毫秒）；新闻用 focus_date
        timestamp=get_time(row.get(time_key)) or get_time(row.get("focus_date")),
    )


def _dedupe(items: list[ListItem | None]) -> list[ListItem]:
    out: list[ListItem] = []
    seen: set[str] = set()
    for item in items:
        if item and item.id not in seen:  # 头图 / 置顶条也在列表里时，留页面先出现的位置
            seen.add(item.id)
            out.append(item)
    return out


def _data_rows(payload: Any, source: str) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        raise RuntimeError(f"cctv {source} response is not a JSON object: {str(payload)[:200]}")  # noqa: TRY004 - 上游结构漂移是路由级错误
    if payload.get("errcode"):
        # 业务错误壳（如去掉 serviceId 后的 {"errcode":"1105","msg":"无效服务"}）
        raise RuntimeError(
            f"cctv {source} returned business error errcode={payload.get('errcode')}: {payload.get('msg')}"
        )
    data = payload.get("data")
    rows = data.get("list") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        raise RuntimeError(f"cctv {source} response has no data.list (feed changed): {str(payload)[:200]}")  # noqa: TRY004 - 上游结构漂移是路由级错误
    return [row for row in rows if isinstance(row, dict)]


def _jsonp_payload(text: str) -> Any:
    """去掉 JSONP 回调（china(...)），接口直接回 JSON 时原样解析。"""
    text = text.strip()
    match = _JSONP_CALL.match(text)
    return json.loads(match.group(1) if match else text)


# ---------------------------------------------------------------- 电视节目


async def _get_program(board: str, no_cache: bool) -> tuple[Any, str, list[ListItem]]:
    page, column, mode, n = _PROGRAMS[board]
    result = await get(
        url=_VIDEO_API,
        params={"id": column, "n": n, "sort": "desc", "p": 1, "mode": mode, "serviceId": "tvcctv"},
        headers={**_HEADERS, "Accept": _JSON_ACCEPT},
        no_cache=no_cache,
        cache_key=f"{ROUTE_NAME}:{board}",
    )
    payload = result.data if isinstance(result.data, dict) else {}
    rows = _data_rows(payload, board)
    return result, page, _dedupe([_item(row, "time") for row in rows])


# ---------------------------------------------------------------- 新闻频道


def _news_slides(html: str, page: str) -> list[dict[str, Any]]:
    """频道页顶部头图（.xinwen18886_ind01 #slide .silde）：静态 HTML，编辑放的头条，通常 1 条。"""
    soup = BeautifulSoup(html, "lxml")
    out: list[dict[str, Any]] = []
    for slide in soup.select(".xinwen18886_ind01 #slide .silde"):
        a = slide.select_one("h3 a[href]")
        href = str(slide.get("dataurl") or "") or (str(a.get("href")) if a else "")
        url = urljoin(page, href.strip())
        img = slide.select_one("img")
        brief = slide.select_one(".right_text p")
        if a and url:
            out.append(
                {
                    "id": _id_from_url(url),
                    "url": url,
                    "title": a.get_text(" ", strip=True),
                    "image": str(img.get("data-echo") or img.get("src") or "") if img else "",
                    "brief": brief.get_text(" ", strip=True) if brief else "",
                }
            )
    return out


async def _get_news(board: str, no_cache: bool) -> tuple[Any, str, list[ListItem]]:
    page, name = _NEWS_PAGES[board]
    html_result = await get(
        url=page,
        headers={**_HEADERS, "Accept": _HTML_ACCEPT},
        no_cache=no_cache,
        response_type="text",
        cache_key=f"{ROUTE_NAME}:{board}:page",
    )
    data_result = await get(
        url=_NEWS_DATA_URL.format(name=name),
        headers={**_HEADERS, "Accept": _JSON_ACCEPT},
        no_cache=no_cache,
        response_type="text",  # JSONP 不是合法 JSON,必须按文本取回再解包
        cache_key=f"{ROUTE_NAME}:{board}:data",
    )
    rows = _data_rows(_jsonp_payload(str(data_result.data)), board)
    listed = {str(row.get("id")): row for row in rows}
    # 头图在列表里时用列表里的完整字段（含发布时间），不在时保留头图自身字段（timestamp 为空）
    head = [listed.get(str(slide["id"]), slide) for slide in _news_slides(str(html_result.data), page)]
    return data_result, page, _dedupe([_item(row, "focus_date") for row in head + rows])
