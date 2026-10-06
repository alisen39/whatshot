"""中央媒体电子报(epaper-central)。

数据源与口径照 board_api 证据 tmp/board_api/epaper_central(2026-09-28 冷启动留档,
公开页面、无签名、无 cookie、无需登录):每个子榜是一份报纸(或期刊)当期(最近一期)
全部版面的文章,按版面顺序、版内文章顺序输出;desc 是"第 N 版 版名"(期刊是栏目名),
timestamp 是出版日期北京时间 0 点;当天没有出版或还没上传时取最近一期,message 写明
期数日期。原 17 个子榜覆盖 18 个 backlog 行(工人日报已因上游不可达下线,现存 16 个)——人民网"电子版"与人民日报"电子报"是原站
同一份(paper.people.com.cn/rmrb),共用 people-rmrb。

入口一律按原站现在的电子版取(tophub 节点大多停在改版前的旧格式):
- 系统 A(方正新版):人民日报、人民日报海外版、光明日报、文摘报、中华读书报、
  经济日报、中国青年报;文摘报/中华读书报旧入口 paperindex.htm 仍跳改版前旧日期,
  必须用 html/layout/index.html
- 系统 B(方正经典):经济参考报(根域 403,入口带 /www/pages/webpage2009/)、科普时报
- 系统 C(PaperIndex):法治日报(/fzrb/ 目录 403,入口用 content/PaperIndex.htm)、
  新华每日电讯(首版页 .listdaohang 一页列出全期)
- 专用:解放军报(rmt-zuul.81.cn newestPaper → www.81.cn 当期 index.json,列表页 JS
  渲染,文章页地址照 list.js 拼)、科技日报(新平台免登录 uv 接口,POST JSON 三步,
  必须带 x-requested-with: XMLHttpRequest)、中国科学报(图形版页取期 id → 文字版目录页)、军事记者/国防教育
  (中国军网期刊列表页取期号最大的一期 → 该期目录页;无单一出版日期,timestamp 留空)
不做:环球时报英文版电子报——入口跳付费订阅平台、免费试读也要登录
(board_api evidence/90_globaltimes_*)。

反爬口径(board_api verify/header_matrix.jsonl):解放军报 newestPaper 对 python-httpx
UA 返回 403,其余站点不挑 UA,统一带浏览器 UA;经济日报 https 返回 504,只用 http。
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from urllib.parse import urlencode, urljoin

from bs4 import BeautifulSoup
from starlette.requests import Request

from whats_hot_api.models import RouterData
from whats_hot_api.routes.hotlist import _epaper_common as epaper
from whats_hot_api.routes.hotlist._epaper_common import (
    Article,
    EpaperFetch,
    Issue,
    PaperPage,
    attr_of,
    clean_text,
    parse_label,
    strip_html,
    tag_text,
)

ROUTE_NAME = "epaper-central"

# 声明序第一个是默认榜(board_api scraper_api.py 的 TYPES 序)
type_map: dict[str, str] = {
    "people-rmrb": "人民日报",
    "people-rmrbhwb": "人民日报海外版",
    "gmw-gmrb": "光明日报",
    "gmw-wzb": "文摘报",
    "gmw-zhdsb": "中华读书报",
    "ce-jjrb": "经济日报",
    "cyol-zgqnb": "中国青年报",
    "jjckb-jjckb": "经济参考报",
    "legaldaily-fzrb": "法治日报",
    "mrdx-mrdx": "新华每日电讯",
    "sciencenet-zgkxb": "中国科学报",
    "stdaily-kjrb": "科技日报",
    "stdaily-kpsb": "科普时报",
    "81cn-jfjb": "解放军报",
    "81cn-jsjz": "军事记者",
    "81cn-gfjy": "国防教育",
}

DEFAULT_TYPE = "people-rmrb"

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "中央媒体电子报",
    "description": "中央媒体报纸与期刊电子版的当期全部版面文章(按版面顺序)",
    "link": "https://paper.people.com.cn/",
    "params": {"type": {"name": "报纸", "type": type_map}},
}

# 入口地址(协议照各站自己页面上的链接:经济日报 https 返回 504,只用 http)
_SYSTEM_A = {
    "people-rmrb": "https://paper.people.com.cn/rmrb/pc/layout/index.html",
    "people-rmrbhwb": "https://paper.people.com.cn/rmrbhwb/pc/layout/index.html",
    "gmw-gmrb": "https://epaper.gmw.cn/gmrb/html/layout/index.html",
    "gmw-wzb": "https://epaper.gmw.cn/wzb/html/layout/index.html",
    "gmw-zhdsb": "https://epaper.gmw.cn/zhdsb/html/layout/index.html",
    "ce-jjrb": "http://paper.ce.cn/pc/layout/index.html",
    "cyol-zgqnb": "http://zqb.cyol.com/pc/layout/index.html",
}
_SYSTEM_B = {
    # 经济参考报根域 dz.jjckb.cn/ 返回 403,入口必须带这段路径
    "jjckb-jjckb": "http://dz.jjckb.cn/www/pages/webpage2009/",
    "stdaily-kpsb": "https://digitalpaper.stdaily.com/http_www.kjrb.com/kjwzb/paperindex.htm",
}
_SYSTEM_C = {
    # 法治日报 /fzrb/ 目录 403,入口用 content/PaperIndex.htm
    "legaldaily-fzrb": "http://epaper.legaldaily.com.cn/fzrb/content/PaperIndex.htm",
    "mrdx-mrdx": "http://mrdx.cn/content/PaperIndex.htm",
}
_PERIODICALS = {
    "81cn-jsjz": "http://www.81.cn/rmjz_203219/jsjz/index.html",
    "81cn-gfjy": "http://www.81.cn/rmjz_203219/gfjy_203685/index.html",
}

# ---------------------------------------------------------------- 解放军报

_JFJB_NEWEST = "https://rmt-zuul.81.cn/api-paper/api/newestPaper"
_JFJB_JSON = "http://www.81.cn/_szb/jfjb/{y}/{m}/{d}/index.json"
# 列表页是 JS 渲染,文章页地址照 list.js 拼:szbxq 详情页 + paperName/paperDate/paperNumber/articleid
_JFJB_ARTICLE = "http://www.81.cn/szb_223187/szbxq/index.html"


async def _fetch_jfjb(f: EpaperFetch) -> Issue:
    """先调 newestPaper 取最新日期,再取当天 index.json(全部版面与文章)。"""
    newest = await f.json(_JFJB_NEWEST)
    papers = newest.get("data") if isinstance(newest, dict) else None
    paper = next(
        (p for p in papers or [] if isinstance(p, dict) and p.get("paperName") == "解放军报"),
        None,
    )
    if not paper or not paper.get("paperData"):
        raise RuntimeError(f"epaper-central 解放军报 newestPaper 没有当期数据:{str(newest)[:200]}")
    day = date.fromisoformat(str(paper["paperData"]))
    data = await f.json(_JFJB_JSON.format(y=f"{day.year}", m=f"{day.month:02d}", d=f"{day.day:02d}"))
    pages: list[PaperPage] = []
    for info in (data or {}).get("paperInfo") or []:
        number = str(info.get("paperNumber") or "")
        page = PaperPage(number, clean_text(info.get("paperBk")))
        for xy in info.get("xyList") or []:
            # 列表页用 xy.title 显示标题,链接拼到 szbxq 详情页(list.js 同样的参数)
            query = urlencode(
                {
                    "paperName": "jfjb",
                    "paperDate": f"{day:%Y-%m-%d}",
                    "paperNumber": number,
                    "articleid": xy.get("id"),
                }
            )
            page.articles.append(
                Article(
                    title=clean_text(xy.get("title")),
                    url=f"{_JFJB_ARTICLE}?{query}",
                    id=str(xy.get("id") or "") or None,
                )
            )
        pages.append(page)
    return Issue(day, pages)


# ---------------------------------------------------------------- 军事记者 / 国防教育(中国军网期刊)


async def _fetch_periodical(f: EpaperFetch, list_url: str) -> Issue:
    """期刊列表页列出各期("2026年第4期"),取期号最大的一期,再从该期目录页按栏目取文章。
    期刊没有单一的出版日期,timestamp 留空。"""
    base, text = await f.page(list_url)
    issues: list[tuple[tuple[int, int], str, str]] = []
    for a in BeautifulSoup(text, "lxml").find_all("a"):
        m = re.fullmatch(r"(\d{4})年第(\d+)期", tag_text(a))
        if m:
            issues.append(((int(m.group(1)), int(m.group(2))), tag_text(a), urljoin(base, attr_of(a, "href"))))
    if not issues:
        raise RuntimeError(f"epaper-central 期刊列表页没有解析到期号:{list_url}")
    _, name, issue_url = max(issues)
    issue_base, issue_text = await f.page(issue_url)
    issue_dir = issue_base.rsplit("/", 1)[0] + "/"
    pages: list[PaperPage] = []
    for dl in BeautifulSoup(issue_text, "lxml").find_all("dl"):
        # 军事记者:<dt>栏目</dt><dd><ul><li><a>标题<span class=author>作者:…</span></a>;
        # 国防教育:<dd>栏目</dd><dt><a>标题</a><span class=author>作者:…</span></dt>
        column = next((tag_text(x) for x in dl.find_all(["dt", "dd"], recursive=False) if not x.find("a")), "")
        page = PaperPage("", column)
        for a in dl.find_all("a"):
            url = urljoin(issue_base, attr_of(a, "href"))
            if not url.startswith(issue_dir) or not re.search(r"/\d+\.html$", url):
                continue
            span = a.find("span", class_="author") or a.find_next_sibling("span", class_="author")
            author = re.sub(r"^作者[：:]\s*", "", tag_text(span)) if span else ""
            if span is not None and span.parent is a:
                span.extract()  # 标题链接里的"作者:…"是作者信息,不属标题
            page.articles.append(Article(title=tag_text(a), url=url, author=author or None))
        if page.articles:
            pages.append(page)
    return Issue(None, pages, name=name)


# ---------------------------------------------------------------- 科技日报

_STDAILY_API = "https://epaper.stdaily.com/stdailynewspaperapi/uv/article"
# app.*.js 常量:epaper.stdaily 域名下的 siteId(改版会变)
_STDAILY_SITE = "811c18b08cf04e79be3b67d6902ee1a7"
_STDAILY_PAGE = "https://epaper.stdaily.com/statics/technology-site/index.html"
# 页面 axios 实例的缺省请求头;不带它(也不带 Referer)接口返回 {"status":"500","msg":"no access!"}
_STDAILY_HEADERS = {"x-requested-with": "XMLHttpRequest"}


async def _stdaily_post(f: EpaperFetch, path: str, body: dict) -> dict:
    res = await f.post_json(f"{_STDAILY_API}/{path}", body, headers=_STDAILY_HEADERS)
    if not isinstance(res, dict) or str(res.get("status")) != "200":
        raise RuntimeError(f"epaper-central 科技日报 uv 接口 {path} 返回:{str(res)[:200]}")
    return res


async def _fetch_kjrb(f: EpaperFetch) -> Issue:
    """新平台(Vue SPA)的免登录 uv 接口:period/date 取本月出版日期 → period/periodTime
    取当期版面 → article/editionId 取每版文章。"""
    today = epaper.beijing_today()
    days: list[str] = []
    for month in (today.replace(day=1), (today.replace(day=1) - timedelta(days=1)).replace(day=1)):
        # 月份参数是 date="YYYY-MM-01"(页面 home.*.js 的写法);periodTime 服务端不读
        res = await _stdaily_post(
            f,
            "period/date",
            {"code": "KJRB", "siteId": _STDAILY_SITE, "date": f"{month:%Y-%m-01}"},
        )
        days = [d for d in ((res.get("obj") or {}).get("dateList") or []) if d <= f"{today:%Y-%m-%d}"]
        if days:
            break
    if not days:
        raise RuntimeError("epaper-central 科技日报 period/date 本月和上月都没有出版日期")
    day_s = max(days)
    res = await _stdaily_post(
        f, "period/periodTime", {"code": "KJRB", "siteId": _STDAILY_SITE, "periodTime": day_s}
    )
    editions = sorted((res.get("obj") or {}).get("editionList") or [], key=lambda e: e.get("weight") or 0)
    pages: list[PaperPage] = []
    for ed in editions:
        parsed = parse_label(clean_text(ed.get("editionName"))) or (str(ed.get("editionCode") or ""), "")
        page = PaperPage(parsed[0], parsed[1].replace(" ", ""))  # 版名"要 闻"中间的空格是排版用的
        data = await _stdaily_post(f, "article/editionId", {"siteId": _STDAILY_SITE, "id": ed.get("id")})
        for art in data.get("list") or []:
            # 与页面点击标题时的路由一致(home.*.js:isDetail/currentNewsId/currentVersionName/…)
            query = urlencode(
                {
                    "isDetail": 1,
                    "currentNewsId": art.get("id"),
                    "currentVersionName": ed.get("editionName"),
                    "currentVersion": ed.get("weight"),
                    "timeValue": day_s,
                }
            )
            page.articles.append(
                Article(
                    title=strip_html(art.get("title")),
                    url=f"{_STDAILY_PAGE}#/home?{query}",
                    id=str(art.get("id") or "") or None,
                    author=clean_text(art.get("author")) or None,
                )
            )
        pages.append(page)
    return Issue(date.fromisoformat(day_s), pages)


# ---------------------------------------------------------------- 中国科学报

_ZGKXB_PHOTO = "https://news.sciencenet.cn/dz/dznews_photo.aspx"


async def _fetch_zgkxb(f: EpaperFetch) -> Issue:
    """图形版页(当期)的"转为文字版"链接给出期 id(dzzz_1.aspx?dzsbqkid=…),
    文字版一页列出全部版面与文章。页面 meta 写 gb2312、实际是 UTF-8(响应头是 UTF-8)。"""
    base, text = await f.page(_ZGKXB_PHOTO)
    link = next((a for a in BeautifulSoup(text, "lxml").find_all("a") if "dzsbqkid=" in attr_of(a, "href")), None)
    if link is None:
        raise RuntimeError("epaper-central 中国科学报图形版页没有'转为文字版'链接")
    text_url, page_text = await f.page(urljoin(base, attr_of(link, "href")))
    soup = BeautifulSoup(page_text, "lxml")
    m = re.search(r"日期：\s*(\d{4})-(\d{1,2})-(\d{1,2})", soup.get_text(" "))
    if not m:
        raise RuntimeError(f"epaper-central 中国科学报文字版没有出版日期:{text_url}")
    day = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    heads: dict[str, str] = {}
    for td in soup.find_all("td"):
        mm = re.search(r"showmenu_item\((\d+)\)", attr_of(td, "onclick"))
        if mm and mm.group(1) not in heads:
            heads[mm.group(1)] = tag_text(td)
    pages: list[PaperPage] = []
    for div in soup.select("div.sec_menu"):
        mm = re.fullmatch(r"menu_item(\d+)", attr_of(div, "id"))
        if not mm:
            continue
        parsed = parse_label(heads.get(mm.group(1), "")) or ("", heads.get(mm.group(1), ""))
        page = PaperPage(*parsed)
        for a in div.find_all("a"):
            href = attr_of(a, "href")
            if "/sbhtmlnews/" in href and tag_text(a):
                page.articles.append(Article(title=tag_text(a), url=urljoin(text_url, href)))
        pages.append(page)
    return Issue(day, pages)


# ---------------------------------------------------------------- 入口


async def _fetch_board(board: str, f: EpaperFetch) -> Issue:
    if board == "81cn-jfjb":
        return await _fetch_jfjb(f)
    if board == "stdaily-kjrb":
        return await _fetch_kjrb(f)
    if board == "sciencenet-zgkxb":
        return await _fetch_zgkxb(f)
    if board in _SYSTEM_A:
        return await epaper.fangzheng_a(f, _SYSTEM_A[board])
    if board in _SYSTEM_B:
        return await epaper.fangzheng_b(f, _SYSTEM_B[board])
    if board in _SYSTEM_C:
        return await epaper.paperindex_c(f, _SYSTEM_C[board])
    if board in _PERIODICALS:
        return await _fetch_periodical(f, _PERIODICALS[board])
    raise ValueError(f"Unknown board '{board}' for route '{ROUTE_NAME}'")


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    board = request.query_params.get("type", DEFAULT_TYPE)
    if board not in type_map:
        raise ValueError(f"Unknown board '{board}' for route '{ROUTE_NAME}'")
    fetch = EpaperFetch(no_cache=no_cache)
    issue = await _fetch_board(board, fetch)
    items = epaper.issue_to_items(issue)
    if not items:
        raise RuntimeError(
            f"epaper-central {board} 当期没有解析到文章({epaper.issue_message(issue)})"
        )
    return RouterData(
        **ROUTE_META,
        type=f"{type_map[board]} · 电子报",
        total=len(items),
        fromCache=fetch.from_cache,
        updateTime=fetch.update_time,
        message=epaper.issue_message(issue),
        data=items,
    )
