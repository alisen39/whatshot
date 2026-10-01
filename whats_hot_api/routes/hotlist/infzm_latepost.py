"""南方周末与晚点 LatePost(www.infzm.com / www.latepost.com,公开接口,无签名无 cookie)。

board_api 单元 `tmp/board_api/infzm_latepost` 的 1:1 迁移,证据见该目录 README、
`analysis_report.md`、`verify/header_matrix.md` 与 `verify/date_infer_check.md`。14 个子榜:

- 南方周末 9 个:8 个频道/推荐列表走 `GET /contents?term_id=<id>&page=1&format=json`
  (PC 列表页自己的"加载更多"接口,第 1 页与页面服务端渲染逐条相同);今日推荐取 term_id=998
  (PC 首页"推荐"区块、导航"推荐"都是它;term_id=1 是 App 频道,PC 站没有入口)。
  频道 2/3/4/5/7/8 是 App 频道,PC 导航没有入口但 `/contents?term_id=<id>` 每天更新,
  频道名与榜名一致(DEV_PLAN_78 口径)。热门文章走 `GET /hot_contents?format=json`
  (首页右栏 HotContents 组件),按名次
- 晚点 5 个:4 个栏目(晚点独家 1、人物访谈 2、晚点早知道 3、长报道 4)走
  `POST /news/get-news-data`,表单 page=1、limit=10、programa=<n>(栏目页自己的 jQuery 接口,
  只接受 POST,programa 必需)。最新报道取首页"最新报道"区块:服务端渲染的头条
  (`#content-box .headlines`)+ `POST /site/index`(page=1、limit=5)第 1 页,按 id 去重;
  `/site/index` 的 release_time 是坏的(全部返回同一日期),发布日期另发一个
  `POST /news/get-news-data`(programa=0、limit=20)按 id 对上

时间口径:
- 南方周末 `publish_time` 是北京时间到秒;晚点 `release_time` 只有日期、没有时刻,取北京时间
  当天 0 点。当年只给"MM月DD日",按"不晚于今天"推年份(2 月 29 日往前找到有这一天的年份);
  最近几天的稿件给相对日期"今天 / 昨天 / 前天"。"今天"以接口响应的 Date 头为基准
  (common.http.page_time 口径,Date 减 Age 换成北京日期),不用本机当前时间
- 两站的 `hot` 都留空:接口的分享数 / 评论数不是榜单热度,页面也不显示为热度

晚点证书:服务器只发叶子 + Let's Encrypt YR1,上级 ISRG Root YR 不在 certifi(2026.02.25)里,
共享 http_client 缺省校验会 CERTIFICATE_VERIFY_FAILED;补 AIA 交叉签名证书可过,但共享客户端
不支持注入,本机回放按受阻处理,留档见 board_api `evidence/15_*`、`evidence/16_*`。
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urlencode, urljoin

from bs4 import BeautifulSoup
from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get, post

ROUTE_NAME = "infzm-latepost"

INFZM = "https://www.infzm.com"
LATEPOST = "https://www.latepost.com"

# 子榜键声明序第一个(infzm-recommend)是默认榜。
INFZM_TERMS: dict[str, int] = {
    "infzm-recommend": 998,
    "infzm-news": 2,
    "infzm-opinion": 3,
    "infzm-culture": 4,
    "infzm-life": 5,
    "infzm-people": 7,
    "infzm-photo": 8,
    "infzm-video": 225,
}
INFZM_HOT = "infzm-hot"
LATEPOST_PROGRAMA: dict[str, int] = {
    "latepost-exclusive": 1,
    "latepost-interview": 2,
    "latepost-newsletter": 3,
    "latepost-longform": 4,
}
LATEPOST_LATEST = "latepost-latest"
LATEPOST_PAGE_SIZE = 10  # 栏目页内联脚本 limit:10
LATEPOST_HOME_SIZE = 5  # 首页"最新报道"列表内联脚本 limit:5
LATEPOST_DATE_LOOKUP_SIZE = 20  # 最新报道的日期对照(programa=0 最新 20 篇,首页 5 篇都在其中)

type_map: dict[str, str] = {
    "infzm-recommend": "南方周末 · 今日推荐",
    "infzm-news": "南方周末 · 新闻",
    "infzm-opinion": "南方周末 · 观点",
    "infzm-culture": "南方周末 · 文化",
    "infzm-life": "南方周末 · 生活",
    "infzm-people": "南方周末 · 人物",
    "infzm-photo": "南方周末 · 影像",
    "infzm-video": "南方周末 · 视频",
    INFZM_HOT: "南方周末 · 热门文章",
    LATEPOST_LATEST: "晚点 · 最新报道",
    "latepost-exclusive": "晚点 · 晚点独家",
    "latepost-interview": "晚点 · 人物访谈",
    "latepost-newsletter": "晚点 · 晚点早知道",
    "latepost-longform": "晚点 · 长报道",
}

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "南方周末与晚点",
    "description": "南方周末各频道列表与热门文章;晚点 LatePost 最新报道与晚点独家、人物访谈、晚点早知道、长报道栏目",
    "link": "https://www.infzm.com/",
    "params": {"type": {"name": "栏目", "type": type_map}},
}

_JSON_HEADERS = {"Accept": "application/json, text/plain, */*"}
# 晚点 POST 照页面 jQuery $.ajax:表单编码;X-Requested-With 与 Accept 实测去掉也一样,照页面一致带上。
_FORM_HEADERS = {
    "X-Requested-With": "XMLHttpRequest",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Content-Type": "application/x-www-form-urlencoded",
}
_HTML_HEADERS = {"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}

_BEIJING = timezone(timedelta(hours=8))
# 作者字段偶有零宽空格开头(如外部来稿),连同其他不可见字符一起去掉。
_INVISIBLE_RE = re.compile(r"[\u200b-\u200d\u2060\ufeff]")
_DATE_RE = re.compile(r"(?:(\d{4})\s*年\s*)?(\d{1,2})\s*月\s*(\d{1,2})\s*日")
_RELATIVE_DAYS = {"今天": 0, "昨天": 1, "前天": 2}
_HEADLINE_ID_RE = re.compile(r"[?&]id=(\d+)")
_HEADLINE_COVER_TS_RE = re.compile(r"\?\d+$")


def _clean(value: Any) -> str:
    """去标签、去不可见字符、收敛空白(board_api _clean 同口径)。"""
    text = _INVISIBLE_RE.sub("", re.sub(r"<[^>]+>", "", str(value or "")))
    return re.sub(r"\s+", " ", text).strip()


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    type_param = request.query_params.get("type", next(iter(type_map)))
    if type_param not in type_map:
        raise ValueError(f"Unknown board '{type_param}' for route '{ROUTE_NAME}'")
    if type_param.startswith("infzm-"):
        board = await _get_infzm(type_param, no_cache)
    else:
        board = await _get_latepost(type_param, no_cache)
    return RouterData(
        **ROUTE_META,
        type=type_map[type_param],
        total=len(board["data"]),
        fromCache=board["from_cache"],
        updateTime=board["update_time"],
        data=board["data"],
        message=board.get("message"),
    )


# ---------------------------------------------------------------- 南方周末


async def _get_infzm(board: str, no_cache: bool) -> dict:
    if board == INFZM_HOT:
        url = f"{INFZM}/hot_contents"
        params: dict[str, str] = {"format": "json"}
        key, message = "hot_contents", "热门文章"
    else:
        term_id = INFZM_TERMS[board]
        url = f"{INFZM}/contents"
        params = {"term_id": str(term_id), "page": "1", "format": "json"}
        key, message = "contents", f"term_id={term_id}"
    result = await get(
        url=url,
        params=params,
        headers=_JSON_HEADERS,
        no_cache=no_cache,
        response_type="json",
        cache_key=f"{ROUTE_NAME}:{board}",
    )
    payload = result.data if isinstance(result.data, dict) else {}
    if payload.get("code") != 200 or not isinstance(payload.get("data"), dict):
        raise RuntimeError(
            f"infzm {board} returned code={payload.get('code')} (business error shell)"
        )
    rows = payload["data"].get(key)
    if not isinstance(rows, list):
        raise RuntimeError(f"infzm {board} response has no '{key}' list (feed changed)")  # noqa: TRY004 - 上游结构漂移是路由级错误
    data = [item for item in (_infzm_item(row) for row in rows if isinstance(row, dict)) if item]
    if not data:
        raise RuntimeError(f"infzm {board} parsed no items")
    term = payload["data"].get("current_term")
    if isinstance(term, dict) and _clean(term.get("title")):
        message = f"{_clean(term['title'])}（{message}）"
    return {"from_cache": result.from_cache, "update_time": result.update_time, "data": data, "message": message}


def _infzm_item(row: dict[str, Any]) -> ListItem | None:
    content_id = row.get("id")
    title = _clean(row.get("subject") or row.get("short_subject"))
    if not content_id or not title:
        return None
    # 页面链接带的 ?source=133&source_1=<term> 是统计参数,文章页用不带参数的形式(tophub 同)。
    url = f"{INFZM}/contents/{content_id}"
    covers = row.get("covers")
    cover = covers[0].get("file_path") if isinstance(covers, list) and covers and isinstance(covers[0], dict) else None
    return ListItem(
        id=content_id,
        title=title,
        url=url,
        mobileUrl=url,
        cover=cover or None,
        author=_clean(row.get("author")) or None,
        desc=_clean(row.get("introtext") or row.get("list_desc")) or None,
        timestamp=get_time(_beijing_seconds(row.get("publish_time"), "%Y-%m-%d %H:%M:%S")),
    )


def _beijing_seconds(value: Any, pattern: str) -> float | None:
    """"YYYY-MM-DD HH:MM:SS"(北京时间,到秒)→ Unix 秒;解析不了返回 None(get_time 会丢弃)。"""
    try:
        moment = datetime.strptime(str(value or "").strip(), pattern).replace(tzinfo=_BEIJING)
    except ValueError:
        return None
    return moment.timestamp()


# ---------------------------------------------------------------- 晚点


async def _latepost_rows(path: str, form: dict[str, Any], cache_key: str, no_cache: bool) -> tuple[Any, list[dict], date]:
    """POST 一个晚点列表接口,返回(响应结果, 列表, 响应生成那天的北京日期)。

    release_time 的"今天 / 昨天 / 前天"相对的是响应 Date 头,不是本机当前时间;
    Date 减 Age(有 Age 头时)换成北京日期(board_api common.http.page_time 口径)。
    """
    result = await post(
        url=LATEPOST + path,
        body=urlencode(form),
        headers=_FORM_HEADERS,
        no_cache=no_cache,
        response_type="json",
        cache_key=cache_key,
        origin_info=True,
    )
    wrapped = result.data if isinstance(result.data, dict) else {}
    payload = wrapped.get("data")
    if (
        not isinstance(payload, dict)
        or str(payload.get("code")) != "1"
        or not isinstance(payload.get("data"), list)
    ):
        raise RuntimeError(f"latepost {path} {form} returned code={payload.get('code') if isinstance(payload, dict) else None}")
    return result, [row for row in payload["data"] if isinstance(row, dict)], _response_date(wrapped.get("headers"))


def _response_date(headers: Any) -> date:
    """页面生成时间(Date 减 Age)的北京日期;没有 Date 头时用当前时间。"""
    lower = {str(key).lower(): str(value) for key, value in (headers or {}).items()}
    try:
        moment = parsedate_to_datetime(lower["date"]).astimezone(_BEIJING)
    except (KeyError, TypeError, ValueError):
        return datetime.now(_BEIJING).date()
    try:
        age = int(lower.get("age") or 0)
    except ValueError:
        age = 0
    return (moment - timedelta(seconds=max(age, 0))).date()


def _latepost_seconds(release_time: Any, today: date) -> float | None:
    """release_time → 北京时间当天 0 点的 Unix 秒。

    相对日期"今天 / 昨天 / 前天"按 today 换算;"MM月DD日"没有年份,按"不晚于今天"推
    (取今年,比今天晚就算去年;2 月 29 日这类日期往前找到有这一天的年份);
    "YYYY年MM月DD日"照用。没有时刻,取当天 0 点。
    """
    text = str(release_time or "").strip()
    if text in _RELATIVE_DAYS:
        day = today - timedelta(days=_RELATIVE_DAYS[text])
        return datetime(day.year, day.month, day.day, tzinfo=_BEIJING).timestamp()
    match = _DATE_RE.fullmatch(text)
    if not match:
        return None
    month, day_of_month = int(match.group(2)), int(match.group(3))
    years = [int(match.group(1))] if match.group(1) else [today.year - offset for offset in range(5)]
    for year in years:
        try:
            day = date(year, month, day_of_month)
        except ValueError:
            continue
        if match.group(1) or day <= today:
            return datetime(day.year, day.month, day.day, tzinfo=_BEIJING).timestamp()
    return None


def _desc_field(programa: int) -> str:
    # 栏目页模板:晚点独家、长报道、首页显示 abstract;人物访谈、晚点早知道显示 intro。
    return "intro" if programa in (2, 3) else "abstract"


def _latepost_item(row: dict[str, Any], *, desc_field: str, seconds: float | None) -> ListItem | None:
    item_id = str(row.get("id") or "").strip()
    title = _clean(row.get("title"))
    if not item_id or not title:
        return None
    url = urljoin(LATEPOST + "/", str(row.get("detail_url") or f"/news/dj_detail?id={item_id}"))
    cover = str(row.get("cover") or "").strip()
    return ListItem(
        id=item_id,
        title=title,
        url=url,
        mobileUrl=url,
        cover=urljoin(LATEPOST + "/", cover) if cover else None,
        desc=_clean(row.get(desc_field)) or None,
        timestamp=get_time(seconds),
    )


def _home_headline(page_html: str) -> dict[str, Any] | None:
    """首页"最新报道"区块的头条(服务端渲染,#content-box .headlines)。"""
    box = BeautifulSoup(page_html, "lxml").select_one("#content-box .headlines")
    if box is None:
        return None
    link = box.select_one(".headlines-title a[href]") or box.select_one("a[href]")
    href = str(link.get("href") or "") if link else ""
    match = _HEADLINE_ID_RE.search(href)
    if not link or not match:
        return None
    image = box.select_one("img.headlines-pic")
    abstract = box.select_one(".headlines-abstract")
    return {
        "id": match.group(1),
        "title": _clean(link.get_text(" ")),
        "detail_url": href,
        "cover": _HEADLINE_COVER_TS_RE.sub("", str(image.get("src") or "")) if image else "",
        "abstract": _clean(abstract.get_text(" ")) if abstract else "",
    }


async def _get_latepost(board: str, no_cache: bool) -> dict:
    if board != LATEPOST_LATEST:
        programa = LATEPOST_PROGRAMA[board]
        result, rows, today = await _latepost_rows(
            "/news/get-news-data",
            {"page": "1", "limit": LATEPOST_PAGE_SIZE, "programa": programa},
            cache_key=f"{ROUTE_NAME}:{board}",
            no_cache=no_cache,
        )
        field = _desc_field(programa)
        data = [
            item
            for item in (_latepost_item(row, desc_field=field, seconds=_latepost_seconds(row.get("release_time"), today)) for row in rows)
            if item
        ]
        if not data:
            raise RuntimeError(f"latepost {board} parsed no items")
        return {
            "from_cache": result.from_cache,
            "update_time": result.update_time,
            "data": data,
            "message": f"programa={programa}",
        }

    # 最新报道:首页头条 + /site/index 第 1 页 5 篇,按 id 去重;日期从 programa=0 按 id 对上
    # (/site/index 的 release_time 是坏的,全部返回同一日期,不能用)。
    home = await get(
        url=LATEPOST + "/",
        headers=_HTML_HEADERS,
        no_cache=no_cache,
        response_type="text",
        cache_key=f"{ROUTE_NAME}:home",
    )
    headline = _home_headline(home.data if isinstance(home.data, str) else "")
    listing, list_rows, _ = await _latepost_rows(
        "/site/index",
        {"page": "1", "limit": LATEPOST_HOME_SIZE},
        cache_key=f"{ROUTE_NAME}:site-index",
        no_cache=no_cache,
    )
    # 日期对照是本榜最后一次请求:updateTime 取它(整榜抓取完成的时刻)。
    dated, dated_rows, today = await _latepost_rows(
        "/news/get-news-data",
        {"page": "1", "limit": LATEPOST_DATE_LOOKUP_SIZE, "programa": 0},
        cache_key=f"{ROUTE_NAME}:date-lookup",
        no_cache=no_cache,
    )
    dates = {str(row.get("id")): _latepost_seconds(row.get("release_time"), today) for row in dated_rows}
    data: list[ListItem] = []
    seen: set[str] = set()
    for row in ([headline] if headline else []) + list_rows:
        item = _latepost_item(row, desc_field="abstract", seconds=dates.get(str(row.get("id"))))
        if item and item.id not in seen:
            seen.add(item.id)
            data.append(item)
    if not data:
        raise RuntimeError(f"latepost {board} parsed no items")
    return {
        # 三个请求都命中缓存才算 fromCache(任一实时拉取说明整榜刷新过)。
        "from_cache": home.from_cache and listing.from_cache and dated.from_cache,
        "update_time": dated.update_time,
        "data": data,
        "message": "首页头条 + 列表" if headline else "首页列表（本次没有头条）",
    }
