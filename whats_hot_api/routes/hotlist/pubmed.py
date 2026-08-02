from __future__ import annotations

import hashlib

from bs4 import BeautifulSoup
from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "pubmed"

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "PubMed",
    "description": "PubMed 近期活跃度上升的生物医学与生命科学文献",
    "link": "https://pubmed.ncbi.nlm.nih.gov/trending/",
}

_TRENDING_URL = "https://pubmed.ncbi.nlm.nih.gov/trending/"
_ESUMMARY_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
_MAX_ITEMS = 50
_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/json",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:  # noqa: ARG001
    list_data = await _get_list(no_cache)
    return RouterData(
        **ROUTE_META,
        type="趋势论文",
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


async def _get_list(no_cache: bool) -> dict:
    trending_result = await get(
        url=_TRENDING_URL,
        params={"size": str(_MAX_ITEMS)},
        no_cache=no_cache,
        response_type="text",
        headers=_HEADERS,
        cache_key=f"pubmed:trending:html:{_MAX_ITEMS}",
    )
    pmids = _parse_trending_pmids(trending_result.data or "")
    if not pmids:
        return {
            "from_cache": trending_result.from_cache,
            "update_time": trending_result.update_time,
            "data": [],
        }

    summary_result = await get(
        url=_ESUMMARY_URL,
        params={
            "db": "pubmed",
            "retmode": "json",
            "id": ",".join(pmids),
            "tool": "whats_hot",
        },
        no_cache=no_cache,
        response_type="json",
        headers={
            "Accept": "application/json",
            "User-Agent": _HEADERS["User-Agent"],
        },
        cache_key=_summary_cache_key(pmids),
    )
    data = _parse_summaries(pmids, summary_result.data)
    return {
        "from_cache": trending_result.from_cache and summary_result.from_cache,
        "update_time": summary_result.update_time,
        "data": data,
    }


def _parse_trending_pmids(html: str) -> list[str]:
    soup = BeautifulSoup(html, "lxml")
    pmids: list[str] = []
    seen: set[str] = set()
    for article in soup.select("article.full-docsum"):
        node = article.select_one(".docsum-pmid")
        pmid = _text(node.get_text(" ", strip=True) if node else "")
        if not pmid.isdigit() or pmid in seen:
            continue
        seen.add(pmid)
        pmids.append(pmid)
        if len(pmids) >= _MAX_ITEMS:
            break
    return pmids


def _parse_summaries(pmids: list[str], payload: object) -> list[ListItem]:
    result = payload.get("result") if isinstance(payload, dict) else None
    if not isinstance(result, dict):
        raise ValueError("PubMed ESummary returned an unreadable result")

    data: list[ListItem] = []
    for rank, pmid in enumerate(pmids, start=1):
        row = result.get(pmid)
        item = _summary_item(row, pmid, rank)
        if item is None:
            raise ValueError(f"PubMed ESummary omitted or invalidated PMID {pmid}")
        data.append(item)
    return data


def _summary_item(row: object, pmid: str, rank: int) -> ListItem | None:
    if not isinstance(row, dict) or _text(row.get("uid")) != pmid:
        return None
    title = _text(row.get("title"))
    publication_time = _text(
        row.get("sortpubdate") or row.get("epubdate") or row.get("pubdate")
    )
    if not title or not publication_time:
        return None

    journal = _text(row.get("fulljournalname") or row.get("source"))
    publication_type = _publication_type(row.get("pubtype"))
    languages = row.get("lang")
    language = (
        ", ".join(_text(value) for value in languages if _text(value))
        if isinstance(languages, list)
        else ""
    )
    doi = _article_id(row.get("articleids"), "doi")
    pmc = _article_id(row.get("articleids"), "pmc")

    desc_parts = [f"趋势排名：{rank}"]
    if journal:
        desc_parts.append(f"期刊：{journal}")
    if publication_type:
        desc_parts.append(f"类型：{publication_type}")
    if language:
        desc_parts.append(f"语言：{language}")
    desc_parts.append(f"PMID：{pmid}")
    if doi:
        desc_parts.append(f"DOI：{doi}")
    if pmc:
        desc_parts.append(f"PMC：{pmc}")

    url = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
    return ListItem(
        id=pmid,
        title=title,
        author=_authors(row.get("authors")) or None,
        desc=" · ".join(desc_parts),
        timestamp=get_time(publication_time),
        url=url,
        mobileUrl=url,
    )


def _authors(value: object) -> str:
    if not isinstance(value, list):
        return ""
    names = [
        _text(author.get("name"))
        for author in value
        if isinstance(author, dict) and _text(author.get("name"))
    ]
    if not names:
        return ""
    return ", ".join(names[:3]) + (" et al." if len(names) > 3 else "")


def _publication_type(value: object) -> str:
    types = [_text(item) for item in value] if isinstance(value, list) else []
    priority = (
        "Systematic Review",
        "Meta-Analysis",
        "Review",
        "Randomized Controlled Trial",
        "Clinical Trial, Phase III",
        "Clinical Trial",
        "Guideline",
        "Journal Article",
    )
    for wanted in priority:
        if wanted in types:
            return wanted
    return types[0] if types else ""


def _article_id(value: object, id_type: str) -> str:
    if not isinstance(value, list):
        return ""
    for article_id in value:
        if (
            isinstance(article_id, dict)
            and _text(article_id.get("idtype")).casefold() == id_type.casefold()
        ):
            return _text(article_id.get("value"))
    return ""


def _text(value: object) -> str:
    return " ".join(str(value or "").split())


def _summary_cache_key(pmids: list[str]) -> str:
    identity = ",".join(pmids).encode()
    return f"pubmed:trending:summary:{hashlib.sha256(identity).hexdigest()}"
