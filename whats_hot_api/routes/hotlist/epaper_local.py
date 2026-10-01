"""地方与行业报电子报(epaper-local)。

数据源与口径照 board_api 证据 tmp/board_api/epaper_local(2026-09-28 冷启动留档,
公开页面、无签名、无 cookie、无需登录):每个子榜是一份报纸当期(最近一期)全部版面
的文章,按版面顺序、版内文章顺序输出;desc 是"第 N 版 版名",timestamp 是出版日期
北京时间 0 点;当天没有出版或还没上传时取最近一期,message 写明期数日期。16 个子榜。

入口一律按原站现在的电子版取(tophub 节点有一半停在改版前的旧格式):
- 系统 A(方正新版):第一财经日报(/epaper/ 与 pc/layout/ 都是 404,入口
  /epaper/pc/index.html)、南方日报、河北日报、新华日报;证券时报是变体:首版 node 页
  #webtree 一页列出全期 128 版(大部分是"信息披露"公告标题,口径是当期全部版面)
- 系统 B(方正经典):南方都市报(首版页叠切换列出几叠取几叠)、河南日报、浙江日报
  (入口直接用 302 落地页 zjrb.zjol.com.cn;Core 共享 http_client 跟随 302 但拿不到
  落地地址,meta refresh 是相对路径,必须以落地页为基准)
- 系统 C(PaperIndex):大众日报、农村大众
- 专用:北京日报(paperindex.htm 的 JS 跳转给出当期移动版整期页)、新京报(首页 meta
  refresh 给出当期目录 → 当期 data.json,文章链接照 outline.js 拼)、解放日报
  (/journal/list.do 取当期日期 → 每版 getJournalPage.do,articlelist 照页面 index.js
  倒序)、21世纪经济报道(首页即当期全部版面,对 python-httpx UA 返回 404)、
  经济观察报(期列表页取最新期号 → 文字版目录,每页 20 篇按"下一页"翻完,无版面
  信息 desc 留空)、每日经济新闻(/newspapers/today 今日报纸文字版)

未移植:大众报业(paper.dzwww.com)CDN 坏节点的"改连备用 IP"回退(board_api
DZWWW_PINS)——Core 共享 http_client 不做进程级 DNS pin,连接失败直接抛错,由调用方
稍后重试;其余反爬口径照 header_matrix:全部请求带浏览器 UA(北京日报 paperindex
不带 UA 返回 403)。
"""

from __future__ import annotations

import re
from datetime import date
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

ROUTE_NAME = "epaper-local"

# 声明序第一个是默认榜(board_api scraper_api.py 的 TYPES 序)
type_map: dict[str, str] = {
    "dzwww-dzrb": "大众日报",
    "dzwww-ncdz": "农村大众",
    "bjd-bjrb": "北京日报",
    "bjnews-xjb": "新京报",
    "jfdaily-jfrb": "解放日报",
    "yicai-dyjrb": "第一财经日报",
    "21jingji-21sjjjbd": "21世纪经济报道",
    "eeo-jjgcb": "经济观察报",
    "nbd-mrjjxw": "每日经济新闻",
    "stcn-zqsb": "证券时报",
    "oeeee-nfdsb": "南方都市报",
    "southcn-nfrb": "南方日报",
    "hebnews-hbrb": "河北日报",
    "dahe-hnrb": "河南日报",
    "xhby-xhrb": "新华日报",
    "zjol-zjrb": "浙江日报",
}

DEFAULT_TYPE = "bjnews-xjb"

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "地方与行业报电子报",
    "description": "地方党报、都市报与财经报电子版的当期全部版面文章(按版面顺序)",
    "link": "https://www.yicai.com/epaper/pc/index.html",
    "params": {"type": {"name": "报纸", "type": type_map}},
}

_SYSTEM_A = {
    # 第一财经日报 /epaper/ 与 pc/layout/ 都是 404,入口用 /epaper/pc/index.html
    "yicai-dyjrb": "https://www.yicai.com/epaper/pc/index.html",
    "southcn-nfrb": "http://epaper.southcn.com/nfdaily/html/index.html",
    "hebnews-hbrb": "https://hbrb.hebnews.cn/pc/paper/layout/index.html",
    "xhby-xhrb": "http://xh.xhby.net/pc/layout/index.html",
}
_SYSTEM_A_TREE = {"stcn-zqsb": "https://epaper.stcn.com/col/index.html"}
_SYSTEM_B = {
    "oeeee-nfdsb": "http://epaper.oeeee.com/epaper/index.htm",
    "dahe-hnrb": "https://newpaper.dahe.cn/hnrb/paperindex.htm",
    # 入口 zjdaily.zjol.com.cn 302 到 zjrb.zjol.com.cn,再 meta refresh 到当期首版;
    # 共享 http_client 跟随 302 但返回不了落地地址,直接用落地页做入口
    "zjol-zjrb": "http://zjrb.zjol.com.cn/",
}
_SYSTEM_C = {
    "dzwww-dzrb": "http://paper.dzwww.com/dzrb/content/PaperIndex.htm",
    "dzwww-ncdz": "http://paper.dzwww.com/ncdz/content/PaperIndex.htm",
}

# ---------------------------------------------------------------- 北京日报

_BJRB_INDEX = "https://bjrbdzb.bjd.com.cn/bjrb/paperindex.htm"


async def _fetch_bjrb(f: EpaperFetch) -> Issue:
    """paperindex.htm 用 JS(window.location.href)跳到当期移动版整期页
    mobile/YYYY/YYYYMMDD/YYYYMMDD_m.html,整期页的 .nav-items 列出全部版面。
    根目录 /bjrb/ 是 403,paperindex 不带 UA 也 403,必须带浏览器 UA。"""
    base, text = await f.page(_BJRB_INDEX)
    m = re.search(r"location(?:\.href)?\s*=\s*[\"']([^\"']+_m\.html)", text)
    if not m:
        raise RuntimeError("epaper-local 北京日报 paperindex.htm 没有跳到当期的 JS")
    url, page_text = await f.page(urljoin(base, m.group(1)))
    dm = re.search(r"/(\d{4})(\d{2})(\d{2})_m\.html", url)
    if not dm:
        raise RuntimeError(f"epaper-local 北京日报当期页地址里没有日期:{url}")
    pages: list[PaperPage] = []
    for box in BeautifulSoup(page_text, "lxml").select("div.nav-items"):
        head = box.select_one(".nav-panel-heading")
        parsed = parse_label(tag_text(head)) if head else None
        if not parsed:
            continue
        page = PaperPage(*parsed)
        for a in box.select("a[data-href]"):
            if tag_text(a):
                page.articles.append(Article(title=tag_text(a), url=urljoin(url, attr_of(a, "data-href"))))
        pages.append(page)
    return Issue(date(int(dm.group(1)), int(dm.group(2)), int(dm.group(3))), pages)


# ---------------------------------------------------------------- 新京报

_BJNEWS_HOME = "http://epaper.bjnews.com.cn/"


async def _fetch_bjnews(f: EpaperFetch) -> Issue:
    """首页 meta refresh 到当期首版 html/YYYY/YYYYMMDD/YYYYMMDD_A01/…html;版面页由
    outline.js 读同期的 ../data.json 渲染,data.json 是全部版面(pageNo/pageName)与
    每版文章(onePageArticleList)。文章链接照 outline.js:
    '../' + issueDate(去横线) + '_' + pageNo + '/' + articleHref。"""
    base, text = await f.page(_BJNEWS_HOME)
    m = re.search(r"html/(\d{4})/(\d{8})/\2_[A-Za-z0-9]+/", text)
    if not m:
        raise RuntimeError("epaper-local 新京报首页没有跳到当期版面")
    issue_dir = urljoin(base, f"html/{m.group(1)}/{m.group(2)}/")
    data = await f.json(issue_dir + "data.json")
    day = date(int(m.group(2)[:4]), int(m.group(2)[4:6]), int(m.group(2)[6:]))
    pages: list[PaperPage] = []
    for p in data if isinstance(data, list) else []:
        page_no = str(p.get("pageNo") or "")
        page = PaperPage(page_no, clean_text(p.get("pageName")))
        for art in p.get("onePageArticleList") or []:
            href = str(art.get("articleHref") or "")
            if href:
                page.articles.append(
                    Article(
                        title=strip_html(art.get("mainTitle")),
                        url=f"{issue_dir}{m.group(2)}_{page_no}/{href}",
                        author=clean_text(art.get("articleAuthor")) or None,
                    )
                )
        pages.append(page)
    return Issue(day, pages)


# ---------------------------------------------------------------- 解放日报

_JFRB_API = "https://www.jfdaily.com/journal"
# 文章页照页面模板拼:detail.html?code=jfrb&date=&id=&page=
_JFRB_DETAIL = "https://www.jfdaily.com/staticsg/res/html/journal/detail.html"


async def _fetch_jfrb(f: EpaperFetch) -> Issue:
    """电子报入口 default.html?code=jfrb 调 /journal/list.do 取当期日期与首版版号;
    版面页 index.js 按版调 /journal/<date>/getJournalPage.do(pagelist 是全部版面,
    articlelist 是本版文章)。index.js 把 articlelist 倒序(articleList.reverse())后
    显示,这里照页面顺序同样倒序。"""
    listing = await f.json(f"{_JFRB_API}/list.do")
    departs = ((listing or {}).get("object") or {}).get("departList") or []
    paper = next((d for d in departs if isinstance(d, dict) and d.get("code") == "jfrb"), None)
    if not paper or not paper.get("jdate"):
        raise RuntimeError(f"epaper-local 解放日报 list.do 没有 jfrb:{str(listing)[:200]}")
    day_s = str(paper["jdate"])
    day = date.fromisoformat(day_s)

    async def journal_page(page_no: str) -> dict:
        res = await f.json(f"{_JFRB_API}/{day_s}/getJournalPage.do?" + urlencode({"page": page_no, "code": "jfrb"}))
        if not isinstance(res, dict) or not res.get("success"):
            raise RuntimeError(f"epaper-local 解放日报 getJournalPage.do {day_s} {page_no}:{str(res)[:200]}")
        return res.get("object") or {}

    first = await journal_page(str(paper.get("pnumber") or "01"))
    pages: list[PaperPage] = []
    for p in first.get("pagelist") or []:
        page_no = str(p.get("pnumber") or "")
        obj = first if page_no == str((first.get("page") or {}).get("pnumber")) else await journal_page(page_no)
        page = PaperPage(page_no, clean_text(p.get("pname")))
        for art in reversed(obj.get("articlelist") or []):
            query = urlencode({"code": "jfrb", "date": day_s, "id": art.get("id"), "page": page_no})
            page.articles.append(
                Article(
                    title=clean_text(art.get("title")),
                    url=f"{_JFRB_DETAIL}?{query}",
                    id=str(art.get("id") or "") or None,
                )
            )
        pages.append(page)
    return Issue(day, pages)


# ---------------------------------------------------------------- 21世纪经济报道

_JJ21_HOME = "http://epaper.21jingji.com/"


async def _fetch_21jingji(f: EpaperFetch) -> Issue:
    """首页直接渲染当期全部版面:.content .main 里依次是 <a><h5>01版：头版</h5></a> 与
    本版 <ul>(每条 <a>标题<p>摘要</p></a>)。头版列表是导读,与后面各版同一篇的链接
    不同(hash 不同),照页面分别输出。对 python-httpx UA 返回 404,必须带浏览器 UA。"""
    _, text = await f.page(_JJ21_HOME)
    soup = BeautifulSoup(text, "lxml")
    m = re.search(r"(\d{4})年(\d{2})月(\d{2})日", tag_text(soup.select_one(".content h1")) or tag_text(soup))
    if not m:
        raise RuntimeError("epaper-local 21世纪经济报道首页没有出版日期")
    main = soup.select_one(".content .main")
    if main is None:
        raise RuntimeError("epaper-local 21世纪经济报道首页没有 .content .main")
    pages: list[PaperPage] = []
    for el in main.find_all(["a", "ul"], recursive=False):
        if el.name == "a":
            parsed = parse_label(tag_text(el.find("h5")))
            if parsed:
                pages.append(PaperPage(*parsed))
        elif pages:
            for a in el.find_all("a"):
                href = attr_of(a, "href")
                if "/article/" not in href:
                    continue
                for p in a.find_all("p"):  # <p> 是摘要
                    p.extract()
                if tag_text(a):
                    pages[-1].articles.append(Article(title=tag_text(a), url=href))
    return Issue(date(int(m.group(1)), int(m.group(2)), int(m.group(3))), pages)


# ---------------------------------------------------------------- 经济观察报

_EEO_COVER = "https://www.eeo.com.cn/epaper/eeocover/1.shtml"
_EEO_TEXT = "https://app.eeo.com.cn/"


async def _fetch_eeo(f: EpaperFetch) -> Issue:
    """期列表页第一格是最新一期(e_cid 期号、e_cbqh 出版日期);"文字版"打开
    app.eeo.com.cn 的文字版目录(免登录),每页 20 篇、按"下一页"翻完。
    文字版没有版面信息,desc 留空。cid=261 是期列表页 JS 里写死的常量。"""
    _, text = await f.page(_EEO_COVER)
    soup = BeautifulSoup(text, "lxml")
    box = soup.select_one("div.dzkw_dzb_box")
    cid = box.find("input", id=re.compile(r"^e_cid_")) if box else None
    cbqh = box.find("input", id=re.compile(r"^e_cbqh_")) if box else None
    if not cid or not cbqh:
        raise RuntimeError("epaper-local 经济观察报期列表页没有最新一期")
    qid, day_s = attr_of(cid, "value"), attr_of(cbqh, "value")
    url: str | None = _EEO_TEXT + "?" + urlencode(
        {"app": "epaper", "controller": "text", "action": "eeolist", "cid": 261, "qid": qid}
    )
    page = PaperPage("", "")
    seen: set[str] = set()
    for _ in range(10):  # 一期 40 多篇、3 页以内;上限只防死循环
        if not url or url in seen:
            break
        seen.add(url)
        base, page_text = await f.page(url)
        psoup = BeautifulSoup(page_text, "lxml")
        for a in psoup.select("div.wzlist ul.new_list li a"):
            if tag_text(a):
                page.articles.append(Article(title=tag_text(a), url=urljoin(base, attr_of(a, "href"))))
        nxt = psoup.select_one("div.wzlist_page a.next")
        url = urljoin(base, attr_of(nxt, "href")) if nxt is not None and attr_of(nxt, "href").startswith("http") else None
    return Issue(date.fromisoformat(day_s), [page], name=f"第{qid}期")


# ---------------------------------------------------------------- 每日经济新闻

_NBD_TODAY = "https://www.nbd.com.cn/newspapers/today"


async def _fetch_nbd(f: EpaperFetch) -> Issue:
    """今日报纸文字版:div.newspapper 块,每块 p.newspapper-title("01 - 封面")+
    本版文章;日期在"今日报纸 : YYYY-MM-DD"。周末显示上一个周五那一期
    (board_api 用 5 个周末的 Wayback 存档核对过)。"""
    _, text = await f.page(_NBD_TODAY)
    soup = BeautifulSoup(text, "lxml")
    m = re.search(r"今日报纸\s*[:：]\s*(\d{4}-\d{2}-\d{2})", soup.get_text(" "))
    if not m:
        raise RuntimeError("epaper-local 每日经济新闻今日报纸页没有日期")
    pages: list[PaperPage] = []
    for block in soup.select("div.newspapper"):
        head = block.select_one("p.newspapper-title")
        if head is None:
            continue
        hm = re.match(r"\s*([A-Za-z]*\d+)\s*-\s*(.*)", tag_text(head))
        page = PaperPage(hm.group(1), clean_text(hm.group(2))) if hm else PaperPage("", tag_text(head))
        for a in block.select("ul li a"):
            if "/articles/" in attr_of(a, "href") and tag_text(a):
                page.articles.append(Article(title=tag_text(a), url=urljoin(_NBD_TODAY, attr_of(a, "href"))))
        pages.append(page)
    return Issue(date.fromisoformat(m.group(1)), pages)


# ---------------------------------------------------------------- 入口


async def _fetch_board(board: str, f: EpaperFetch) -> Issue:
    if board == "bjd-bjrb":
        return await _fetch_bjrb(f)
    if board == "bjnews-xjb":
        return await _fetch_bjnews(f)
    if board == "jfdaily-jfrb":
        return await _fetch_jfrb(f)
    if board == "21jingji-21sjjjbd":
        return await _fetch_21jingji(f)
    if board == "eeo-jjgcb":
        return await _fetch_eeo(f)
    if board == "nbd-mrjjxw":
        return await _fetch_nbd(f)
    if board in _SYSTEM_A:
        return await epaper.fangzheng_a(f, _SYSTEM_A[board])
    if board in _SYSTEM_A_TREE:
        return await epaper.fangzheng_a_tree(f, _SYSTEM_A_TREE[board])
    if board in _SYSTEM_B:
        return await epaper.fangzheng_b(f, _SYSTEM_B[board])
    if board in _SYSTEM_C:
        return await epaper.paperindex_c(f, _SYSTEM_C[board])
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
            f"epaper-local {board} 当期没有解析到文章({epaper.issue_message(issue)})"
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
