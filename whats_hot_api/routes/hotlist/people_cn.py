"""人民网栏目(people-cn)。

数据源与口径照 board_api 证据 tmp/board_api/people_cn(2026-09-28 冷启动留档,公开页面、
无签名、无 cookie、无需登录):
- 观点频道 GB 列表页 opinion.people.com.cn/GB/<栏目路径>/index.html(服务端渲染,取第 1 页),
  三种模板:人民日报要论子栏目 div.leftItem li、频道列表 div.p2j_list ul.list_14 li、
  每日最新评论 div.ej_list_box ul li;三评是单页专题 div.p1_1(h3 标题、p 导语、
  每个专题第一篇带配图)
- 习近平系列重要讲话:jhsjk.people.cn/result 页用的列表接口 testnew/result?...&source=2,
  响应头是 text/html 但正文是 JSON;不带 source=2 返回的是 result 页 HTML(证据
  02_jhsjk_result_no_source)
- 共产党新闻网 / 理论频道 / 领导留言板 / 人民网首页:各自首页的对应区块
  (要闻要论、div.headingNews 主列表、section.hot、#aq_one/#aq_two)

反爬口径(verify/header_check.txt):全部请求带浏览器 UA(jhsjk 接口与领导留言板首页
不带 UA 返回 403),无 Referer、无 cookie、无签名;opinion / cpc / politics 等子域的
https 证书主机名不匹配,一律走 http,只有 jhsjk.people.cn 用 https。
"""

from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag
from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "people-cn"

_OPINION = "http://opinion.people.com.cn"

# 观点频道 GB 列表页三种模板的条目选择器(board_api 证据 01_opinion_*):
# leftItem = 人民日报要论下的子栏目(每页 30 条,日期只有年月日);
# p2j_list = 政经·国际 / 文化·艺术 / 科技·教育 / 壹时评(每页 55 条,日期带时分);
# ej_list_box = 每日最新评论(30 条,日期在 <em> 里)。
_SEL_ITEM = "div.leftItem li"
_SEL_CHANNEL = "div.p2j_list ul.list_14 li"
_SEL_LATEST = "div.ej_list_box ul li"

# board -> (中文名, 取数方式, 页面地址, GB 列表条目选择器);声明序第一个是默认榜
_BOARDS: dict[str, tuple[str, str, str, str]] = {
    "opinion-rmsp": ("人民时评", "gb", f"{_OPINION}/GB/8213/49160/49219/index.html", _SEL_ITEM),
    "opinion-sanping": ("三评观点", "sanping", f"{_OPINION}/GB/8213/420650/index.html", ""),
    "jhsjk-latest": ("习近平系列重要讲话", "jhsjk", "https://jhsjk.people.cn/testnew/result", ""),
    "opinion-rmgd": ("人民观点", "gb", f"{_OPINION}/GB/8213/49160/385787/index.html", _SEL_ITEM),
    "opinion-rmlt": ("人民论坛", "gb", f"{_OPINION}/GB/8213/49160/49220/index.html", _SEL_ITEM),
    "opinion-jrt": ("今日谈", "gb", f"{_OPINION}/GB/8213/49160/49221/index.html", _SEL_ITEM),
    "opinion-xcpl": ("现场评论", "gb", f"{_OPINION}/GB/8213/49160/457598/index.html", _SEL_ITEM),
    "opinion-plygc": ("评论员观察", "gb", f"{_OPINION}/GB/8213/49160/457597/index.html", _SEL_ITEM),
    "opinion-zzgj": ("政治经济（政经·国际）", "gb", f"{_OPINION}/GB/1034/index.html", _SEL_CHANNEL),
    "opinion-whys": ("文化艺术（文化·艺术）", "gb", f"{_OPINION}/GB/364183/index.html", _SEL_CHANNEL),
    "opinion-kjjy": ("科技教育（科技·教育）", "gb", f"{_OPINION}/GB/51854/index.html", _SEL_CHANNEL),
    "opinion-rmwp": ("人民网评（壹时评）", "gb", f"{_OPINION}/GB/223228/index.html", _SEL_CHANNEL),
    "opinion-latest": ("观点频道（每日最新评论）", "gb", f"{_OPINION}/GB/159301/index.html", _SEL_LATEST),
    "cpc-yaowen": ("共产党新闻网（要闻要论）", "cpc", "http://cpc.people.com.cn/", ""),
    "theory-home": ("理论频道（首页主列表）", "theory", "http://theory.people.com.cn/", ""),
    "liuyan-hot": ("地方领导留言板（热点）", "liuyan", "http://liuyan.people.com.cn/", ""),
    "www-yaowen": ("要闻·热点（首页要闻）", "www_yaowen", "http://www.people.com.cn/", ""),
}

DEFAULT_TYPE = "opinion-rmsp"

type_map: dict[str, str] = {key: label for key, (label, _, _, _) in _BOARDS.items()}

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "人民网",
    "description": (
        "人民网栏目：观点频道各子栏目、三评观点、习近平系列重要讲话、"
        "共产党新闻网、理论频道、地方领导留言板、首页要闻。"
    ),
    "link": "http://www.people.com.cn/",
    "params": {
        "type": {
            "name": "栏目",
            "type": type_map,
        },
    },
}

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"
    ),
}

# jhsjk result 页 searchSubmit() 发的检索参数;source=2 是必需的(不带返回 HTML 页),
# 其余参数照页面表单缺省值带上(实验:只带 source=2 返回相同 10 条)
_JHSJK_QUERY: dict[str, str] = {
    "keywords": "",
    "isFuzzy": "0",
    "searchArea": "0",
    "year": "0",
    "form": "",
    "type": "0",
    "page": "1",
    "origin": "全部",
    "source": "2",
}

# 文章地址里的稿件号与日期:/n1/2026/0924/c461529-40804629.html(地方频道是 /n2/)
_URL_DATE = re.compile(r"/n\d/(\d{4})/(\d{2})(\d{2})/c\d+-(\d+)\.html")


def _text(node: Tag | None) -> str:
    """节点文字,连续空白(含 &nbsp;)合成一个空格。"""
    return " ".join(node.get_text(" ").split()) if node else ""


def _article_id(url: str) -> str:
    match = _URL_DATE.search(url)
    return match.group(4) if match else url


def _url_timestamp(url: str) -> int | None:
    """文章地址里的日期,北京时间当天 0 点的毫秒值;地址里没有日期返回 None。"""
    match = _URL_DATE.search(url)
    if not match:
        return None
    return get_time(f"{match.group(1)}-{match.group(2)}-{match.group(3)}")


def _item(
    title: str,
    url: str,
    *,
    timestamp: int | None = None,
    desc: str | None = None,
    cover: str | None = None,
) -> ListItem:
    return ListItem(
        id=_article_id(url),
        title=title,
        url=url,
        mobileUrl=url,
        desc=desc,
        cover=cover,
        timestamp=timestamp if timestamp is not None else _url_timestamp(url),
    )


def _links(node: Tag, base: str) -> list[tuple[str, str]]:
    """节点里有文字的文章链接(/n1/、/n2/ 或留言详情),按出现顺序;
    纯图片链接、专题页/平台入口等其它地址跳过。"""
    out: list[tuple[str, str]] = []
    for a in node.find_all("a", href=True):
        title = _text(a)
        url = urljoin(base, str(a["href"]).strip())
        if title and ("/n1/" in url or "/n2/" in url or "threads/content" in url):
            out.append((title, url))
    return out


def _dedupe(items: list[ListItem]) -> list[ListItem]:
    """同一篇(按链接)在区块里出现两次只留第一次。"""
    seen: set[str] = set()
    out: list[ListItem] = []
    for item in items:
        if item.url not in seen:
            seen.add(item.url)
            out.append(item)
    return out


def _parse_gb(soup: BeautifulSoup, page: str, selector: str) -> list[ListItem]:
    """观点频道 GB 列表页:<li><a href=/n1/…>标题</a> <i class=gray>日期</i></li>
    (每日最新评论的日期在 <em>)。"""
    items: list[ListItem] = []
    for li in soup.select(selector):
        date_node = li.find("i", class_="gray") or li.find("em")
        timestamp = get_time(_text(date_node)) if date_node else None
        for title, url in _links(li, page):
            items.append(_item(title, url, timestamp=timestamp))
    return items


def _parse_sanping(soup: BeautifulSoup, page: str) -> list[ListItem]:
    """三评索引页:div.p1_1 每个一篇,h3 是标题,p 是导语,专题第一篇带配图;单页。"""
    items: list[ListItem] = []
    for box in soup.select("div.p1_1"):
        h3 = box.find("h3")
        links = _links(h3, page) if h3 else []
        if not links:
            continue
        img = box.find("img", src=True)
        title, url = links[0]
        items.append(
            _item(
                title,
                url,
                desc=_text(box.find("p")) or None,
                cover=urljoin(page, str(img["src"])) if img else None,
            )
        )
    return items


def _parse_cpc(soup: BeautifulSoup, page: str) -> list[ListItem]:
    """共产党新闻网首页"要闻要论":h2 后面的 ul;块尾的平台入口(zzxszy.people.cn)
    不是文章,由 _links 的地址过滤跳过。"""
    h2 = next((h for h in soup.find_all("h2") if "要闻要论" in _text(h)), None)
    ul = h2.find_next_sibling("ul") if isinstance(h2, Tag) else None
    if not isinstance(ul, Tag):
        raise RuntimeError(  # noqa: TRY004 - upstream shape problem, not a caller bug
            "people-cn cpc home has no '要闻要论' block (page changed)"
        )
    return [_item(title, url) for title, url in _links(ul, page)]


def _parse_theory(soup: BeautifulSoup, page: str) -> list[ListItem]:
    """理论频道首页主列表:党建政治 / 经济社会 / 国际外交 / 文史哲教 / 学术动态
    5 个页签(div.headingNews),每条 strong 是标题、em.gray2 是导语,按页签顺序输出。"""
    items: list[ListItem] = []
    for tab in soup.select("div.headingNews"):
        for box in tab.select("div.hdNews"):
            strong = box.find("strong")
            links = _links(strong, page) if strong else []
            if not links:
                continue
            title, url = links[0]
            items.append(_item(title, url, desc=_text(box.find("em", class_="gray2")) or None))
    return items


def _parse_liuyan(soup: BeautifulSoup, page: str) -> list[ListItem]:
    """领导留言板首页"热点"(section.hot):头条 1 条 + 列表(留言详情与报道混排);
    留言详情地址里没有日期,timestamp 留空。"""
    hot = soup.select_one("section.hot")
    if hot is None:
        raise RuntimeError("people-cn liuyan home has no 'hot' section (page changed)")
    items: list[ListItem] = []
    for part in hot.select("div.hotTitle, div.hotList > ul"):
        for title, url in _links(part, page):
            item = _item(title, url)
            match = re.search(r"tid=(\d+)", url)
            items.append(item.model_copy(update={"id": match.group(1)}) if match else item)
    return items


def _parse_www_yaowen(soup: BeautifulSoup, page: str) -> tuple[str | None, list[ListItem]]:
    """人民网首页"要闻"块:h2#aq_one(头条,常是标题图片)+ ul#aq_two。
    返回 (头条没有文字时的文章地址, 列表条目);一行两个链接拆成两条。"""
    head = soup.select_one("#aq_one")
    ul = soup.select_one("#aq_two")
    if ul is None:
        raise RuntimeError("people-cn www home has no '#aq_two' block (page changed)")
    pending: str | None = None
    items: list[ListItem] = []
    if head is not None:
        links = _links(head, page)
        if links:
            items.append(_item(*links[0]))
        else:
            a = head.find("a", href=True)
            pending = urljoin(page, str(a["href"])) if a else None
    for li in ul.find_all("li"):
        for title, url in _links(li, page):
            items.append(_item(title, url))
    return pending, items


def _parse_head_title(html: str) -> str:
    """头条文章页的标题:第一个有文字的 <h1>;退回 <title> 去掉"--"后缀。"""
    soup = BeautifulSoup(html, "lxml")
    h1 = next((h for h in soup.find_all("h1") if _text(h)), None)
    if h1 is not None:
        return _text(h1)
    return _text(soup.title).split("--")[0].strip() if soup.title else ""


async def _fetch_jhsjk(url: str, no_cache: bool) -> tuple[list[ListItem], bool, str]:
    result = await get(
        url=url,
        params=dict(_JHSJK_QUERY),
        headers=_HEADERS,
        no_cache=no_cache,
        response_type="json",
    )
    payload = result.data if isinstance(result.data, dict) else {}
    if payload.get("status") != "success":
        raise RuntimeError(
            f"people-cn jhsjk returned status={payload.get('status')!r} (feed changed)"
        )
    items: list[ListItem] = []
    for row in payload.get("list") or []:
        article_id = str(row.get("article_id") or "").strip()
        title = " ".join(str(row.get("title") or "").split())
        if not article_id or not title:
            continue
        article_url = f"https://jhsjk.people.cn/article/{article_id}"
        items.append(
            ListItem(
                id=article_id,
                title=title,
                url=article_url,
                mobileUrl=article_url,
                desc=_text_str(row.get("newcontent")),
                timestamp=get_time(str(row.get("input_date") or "")),
            )
        )
    return items, result.from_cache, result.update_time


def _text_str(value: object) -> str | None:
    return " ".join(str(value).split()) or None if value else None


async def _fetch_html(kind: str, url: str, selector: str, no_cache: bool) -> tuple[list[ListItem], bool, str]:
    result = await get(url=url, headers=_HEADERS, no_cache=no_cache, response_type="text")
    soup = BeautifulSoup(result.data, "lxml")  # 页面 meta 声明 UTF-8
    if kind == "gb":
        items = _parse_gb(soup, url, selector)
    elif kind == "sanping":
        items = _parse_sanping(soup, url)
    elif kind == "cpc":
        items = _parse_cpc(soup, url)
    elif kind == "theory":
        items = _parse_theory(soup, url)
    elif kind == "liuyan":
        items = _parse_liuyan(soup, url)
    else:  # www_yaowen
        pending, items = _parse_www_yaowen(soup, url)
        if pending:
            # 头条是标题图片、页面上没有文字:到文章页取标题,放在最前面
            head = await get(url=pending, headers=_HEADERS, no_cache=no_cache, response_type="text")
            title = _parse_head_title(head.data)
            if title:
                items = [_item(title, pending)] + [x for x in items if x.url != pending]
    return _dedupe(items), result.from_cache, result.update_time


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    board = request.query_params.get("type", DEFAULT_TYPE)
    if board not in _BOARDS:
        raise ValueError(f"Unknown board '{board}' for route '{ROUTE_NAME}'")
    label, kind, url, selector = _BOARDS[board]
    if kind == "jhsjk":
        items, from_cache, update_time = await _fetch_jhsjk(url, no_cache)
    else:
        items, from_cache, update_time = await _fetch_html(kind, url, selector, no_cache)
    if not items:
        raise RuntimeError(f"people-cn {board} parsed no items from {url}")
    return RouterData(
        **ROUTE_META,
        type=label,
        total=len(items),
        fromCache=from_cache,
        updateTime=update_time,
        data=items,
    )
