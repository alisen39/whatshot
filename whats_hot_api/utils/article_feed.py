"""带全文的 RSS：微信公众号（经 wechat2rss，https://wechat2rss.xlab.app）与媒体网站。

公开条目只带 500 字摘要；正文（最多 32k 字）放在 ``RouterData._analysis_texts``，
仅供 Cloud AI 流程使用，不进入任何序列化输出。wechat2rss 上游平均约 6 小时更新一次
（2026-11-07 实测常落后一天）；媒体网站的 feed 实时更新。feed 都只含最近约 20 篇。
摘要和正文都先去掉开头的署名、版头（见 ``strip_meta``）。
"""

from __future__ import annotations

import re
from email.utils import parsedate_to_datetime
from urllib.parse import parse_qs, parse_qsl, urlencode, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from whats_hot_api.backfill import BackfillSpec, BackfillStrategy
from whats_hot_api.models import NewsFlashItem, RouterData
from whats_hot_api.utils.http_client import get

WECHAT_FEED_BASE = "https://wechat2rss.xlab.app/feed"
REQUEST_HEADERS = {"User-Agent": "WhatsHot/1.0"}
FEED_TTL = 3600  # Cloud 每小时拉一次；普通读一小时内复用缓存
MAX_TEXT_CHARS = 32_000
MAX_SUMMARY_CHARS = 500

# 公众号路由 ``wechat``，每个号是 ``type=<key>``：key → (名称, feed 地址)。第一个是默认号；
# 新号加在末尾，并加进 Cloud pj_07/services/board_intervals.py。
WECHAT_ROUTE = "wechat"
WECHAT_FEEDS: dict[str, tuple[str, str]] = {
    "qbit": ("量子位", f"{WECHAT_FEED_BASE}/7131b577c61365cb47e81000738c10d872685908.xml"),
    "jiqizhixin": ("机器之心", f"{WECHAT_FEED_BASE}/51e92aad2728acdd1fda7314be32b16639353001.xml"),
    "xinzhiyuan": ("新智元", f"{WECHAT_FEED_BASE}/ede30346413ea70dbef5d485ea5cbb95cca446e7.xml"),
    "geekpark": ("极客公园", f"{WECHAT_FEED_BASE}/1a5aec98e71c707c8ca092bc2c255b9d4bac477d.xml"),
    "xixiaoyao": ("夕小瑶科技说", f"{WECHAT_FEED_BASE}/a1cd365aa14ed7d64cabfc8aa086da40ecaba34d.xml"),
    "paperweekly": ("PaperWeekly", f"{WECHAT_FEED_BASE}/3be891c2f4e526629ab055a297cc2cd6c1f0a563.xml"),
    "cv": ("我爱计算机视觉", f"{WECHAT_FEED_BASE}/b81ffcfff1107b5265cd7e39de610dc7ca72caf4.xml"),
    "42zhangjing": ("42章经", f"{WECHAT_FEED_BASE}/31436fcc3bba8c2c2a9337a163afcb3b5a57a0a0.xml"),
}
WECHAT_META: dict = {
    "name": WECHAT_ROUTE,
    "title": "微信公众号",
    "description": "微信公众号文章（经 wechat2rss）",
    "link": "https://wechat2rss.xlab.app/",
    "params": {"type": {"name": "公众号", "type": {key: name for key, (name, _url) in WECHAT_FEEDS.items()}}},
}
# 媒体网站自己的 RSS，正文在 content:encoded 或 description 里。一个网站一个路由。
SITE_FEEDS: dict[str, tuple[str, str]] = {
    "zhidx": ("智东西", "https://zhidx.com/rss"),
    "leiphone": ("雷锋网", "https://www.leiphone.com/feed"),
    "ifanr-news": ("爱范儿", "https://www.ifanr.com/feed"),
}

# Backfill capability; see whats_hot_api/backfill.py.
BACKFILL: dict[str, BackfillSpec] = {
    "*": BackfillSpec(
        strategy=BackfillStrategy.SNAPSHOT,
        notes="RSS 只含最近若干篇，不能翻页或按时间回溯。",
        verified_at="2026-11-07",
    ),
}

_BLOCK_TAGS = ["p", "section", "div", "li", "blockquote", "br", "tr", "h1", "h2", "h3", "h4", "h5", "h6"]

# 署名与版头，2026-11-08 按 11 个来源各 20 篇核对过，只删这些已确认的写法。
# 首段署名只看第 1 段，其余版头只看前 8 段；“阅读原文”和图注在全文删。
_HEAD_PARAS = 8
_BYLINE = re.compile(r"^(原创\s+)?.{1,30}?\s+\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}(\s+\S+)?$")  # 公众号首段“[原创] 作者 日期 时间 地点”
_HEAD_META = [
    re.compile(r"^.{1,20}?\s*(发自|投稿)(\s*凹非寺)?$"),  # “梦瑶 发自 凹非寺”“VISTA团队 投稿”
    re.compile(r"^量子位\s*[|｜]\s*公众号\s*QbitAI$"),
    re.compile(r"^(新智元|机器之心)报道$"),
    re.compile(r"^©?(作者|编辑|编译|撰文|责编|编辑整理|单位|研究方向)\s*[|｜丨:：]"),  # “编辑｜郑玄”“作者丨高允毅”
    re.compile(r"^智东西$"),
    re.compile(r"^\S{1,20}（公众号：\w+）$"),  # “AI应用风向标（公众号：ZhidxcomAI）”
]
_ANY_META = [re.compile(r"^(阅读原文|跳转微信打开)$"), re.compile(r"^▲")]  # 公众号尾部按钮；智东西、爱范儿的图注


def route_meta(route: str) -> dict:
    name, url = SITE_FEEDS[route]
    return {"name": route, "title": name, "description": f"{name}网站最新文章", "link": url}


async def fetch_article_feed(route: str, no_cache: bool = False) -> RouterData:
    """媒体网站路由。"""
    name, url = SITE_FEEDS[route]
    return await fetch_feed(route_meta(route), name, url, "最新文章", no_cache)


async def fetch_wechat_feed(account: str, no_cache: bool = False) -> RouterData:
    """公众号路由的一个号。"""
    name, url = WECHAT_FEEDS[account]
    return await fetch_feed(WECHAT_META, name, url, name, no_cache)


async def fetch_feed(meta: dict, source: str, url: str, type_label: str, no_cache: bool) -> RouterData:
    # 缓存原始 XML，命中缓存时也重新解析，正文因此始终可用。
    result = await get(
        url=url,
        no_cache=no_cache,
        ttl=FEED_TTL,
        response_type="text",
        headers=REQUEST_HEADERS,
    )
    items, texts = parse_feed(result.data, source)
    data = RouterData(
        kind="newsflash",
        **meta,
        type=type_label,
        total=len(items),
        fromCache=result.from_cache,
        updateTime=result.update_time,
        data=items,
    )
    data._analysis_texts = texts
    return data


def parse_feed(xml: str, account: str) -> tuple[list[NewsFlashItem], dict[str, str]]:
    """RSS → (公开条目, 条目 id → 正文)。"""
    soup = BeautifulSoup(xml, "xml")
    rss = soup.find("rss")
    channel = rss.find("channel") if rss else None
    nodes = channel.find_all("item", recursive=False) if channel else []
    if not nodes:
        raise RuntimeError(f"{account} response is not a non-empty RSS feed")

    items: list[NewsFlashItem] = []
    texts: dict[str, str] = {}
    for node in nodes:
        title = _tag_text(node, "title")
        url = _tag_text(node, "link")
        if not title or not url.startswith(("http://", "https://")):
            continue
        item_id = article_id(url)
        text = strip_meta(article_text(_tag_text(node, "content:encoded") or _tag_text(node, "description"))) or title
        texts[item_id] = text[:MAX_TEXT_CHARS]
        summary = text[:MAX_SUMMARY_CHARS]
        items.append(
            NewsFlashItem(
                id=item_id,
                title=title,
                content=summary,
                summary=summary,
                contentStatus="summary",
                source=account,
                timestamp=_parse_pub_date(_tag_text(node, "pubDate")),
                url=url,
                mobileUrl=url,
            )
        )

    if not items:
        raise RuntimeError(f"{account} RSS contains no usable articles")
    items.sort(key=lambda item: item.timestamp or 0, reverse=True)
    return items, texts


def article_id(url: str) -> str:
    """标准公众号链接用 __biz + mid + idx（与 sn、分享参数无关）；其他链接用去掉 utm_* 参数和锚点的 URL
    （爱范儿的链接带 utm_*）。"""
    parts = urlsplit(url)
    query = parse_qs(parts.query)
    biz, mid, idx = (query.get(key, [""])[0] for key in ("__biz", "mid", "idx"))
    mid = mid or query.get("appmsgid", [""])[0]
    if biz and mid and idx:
        return f"wechat:{biz}:{mid}:{idx}"
    kept = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not k.startswith("utm_")]
    return urlunsplit(parts._replace(query=urlencode(kept), fragment=""))


def article_text(html: str) -> str:
    """文章 HTML → 纯文本，一段一行。"""
    soup = BeautifulSoup(html or "", "lxml")
    for tag in soup(["script", "style"]):
        tag.decompose()
    for tag in soup.find_all(_BLOCK_TAGS):
        tag.append("\n")
    lines = (" ".join(line.split()) for line in soup.get_text().splitlines())
    return "\n".join(line for line in lines if line)


def strip_meta(text: str) -> str:
    """去掉署名、版头、作者编辑行和“阅读原文”等，只看开头几段（一段一行）。"""
    kept = []
    for i, line in enumerate(text.splitlines()):
        if (i == 0 and _BYLINE.match(line)) or (i < _HEAD_PARAS and any(r.match(line) for r in _HEAD_META)):
            continue
        if not any(r.match(line) for r in _ANY_META):
            kept.append(line)
    return "\n".join(kept)


def _tag_text(node, name: str) -> str:
    tag = node.find(name)
    return tag.get_text(" ", strip=True) if tag else ""


def _parse_pub_date(value: str) -> int | None:
    if not value:
        return None
    try:
        return int(parsedate_to_datetime(value).timestamp() * 1000)
    except (TypeError, ValueError, IndexError, OverflowError):
        return None
