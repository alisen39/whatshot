from __future__ import annotations

import re

from bs4 import BeautifulSoup
from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "douban-movie"

type_map: dict[str, str] = {
    "hot": "热门电影",
    "new": "新片榜",
    "top250": "Top 250",
}

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "豆瓣电影",
    "link": "https://movie.douban.com/chart",
    "params": {
        "type": {
            "name": "榜单分类",
            "type": type_map,
        },
    },
}

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
}


def _get_numbers(text: str | None) -> int:
    if not text:
        return 0
    match = re.search(r"\d+", text)
    return int(match.group(0)) if match else 0


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    type_param = request.query_params.get("type", "hot")
    selected_type = type_param if type_param in type_map else "hot"
    list_data = (
        await _get_top250(no_cache)
        if selected_type == "top250"
        else await _get_new(no_cache)
        if selected_type == "new"
        else await _get_hot(no_cache)
    )
    return RouterData(
        **{
            **ROUTE_META,
            "link": (
                "https://movie.douban.com/top250"
                if selected_type == "top250"
                else "https://movie.douban.com/chart"
                if selected_type == "new"
                else "https://movie.douban.com/explore"
            ),
        },
        type=type_map[selected_type],
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


async def _get_new(no_cache: bool) -> dict:
    result = await get(
        url="https://movie.douban.com/chart/",
        no_cache=no_cache,
        response_type="text",
        headers=_HEADERS,
    )
    soup = BeautifulSoup(result.data, "html.parser")
    data = []
    for item in soup.select(".article tr.item"):
        a_tag = item.find("a")
        href = a_tag.get("href", "") if a_tag else ""
        item_id = _get_numbers(href)
        title_attr = a_tag.get("title", "") if a_tag else ""
        if not item_id or not title_attr:
            continue
        score_el = item.select_one(".rating_nums")
        score = score_el.get_text(strip=True) if score_el else "0.0"
        img_tag = item.find("img")
        desc_el = item.select_one("p.pl")
        pl_span = item.select_one("span.pl")
        data.append(
            ListItem(
                id=item_id,
                title=f"【{score}】{title_attr}",
                cover=img_tag.get("src") if img_tag else None,
                desc=desc_el.get_text(" ", strip=True) if desc_el else None,
                hot=_get_numbers(pl_span.get_text() if pl_span else None),
                url=href or f"https://movie.douban.com/subject/{item_id}/",
                mobileUrl=f"https://m.douban.com/movie/subject/{item_id}/",
            )
        )
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": data,
    }


async def _get_hot(no_cache: bool) -> dict:
    result = await get(
        url="https://m.douban.com/rexxar/api/v2/subject/recent_hot/movie",
        no_cache=no_cache,
        response_type="json",
        headers={**_HEADERS, "Referer": "https://movie.douban.com/"},
    )
    data: list[ListItem] = []
    for row in (result.data or {}).get("items") or []:
        item_id = row.get("id")
        title = str(row.get("title") or "").strip()
        if not item_id or not title:
            continue
        url = f"https://movie.douban.com/subject/{item_id}/"
        data.append(
            ListItem(
                id=item_id,
                title=title,
                desc=str(row.get("card_subtitle") or "").strip() or None,
                cover=row.get("cover_url") or row.get("pic"),
                url=url,
                mobileUrl=f"https://m.douban.com/movie/subject/{item_id}/",
            )
        )
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": data,
    }


async def _get_top250(no_cache: bool) -> dict:
    data: list[ListItem] = []
    from_cache = True
    update_time = ""
    for start in range(0, 250, 25):
        result = await get(
            url="https://movie.douban.com/top250",
            params={"start": str(start)},
            no_cache=no_cache,
            response_type="text",
            headers=_HEADERS,
        )
        from_cache = from_cache and result.from_cache
        update_time = result.update_time or update_time
        soup = BeautifulSoup(result.data, "html.parser")
        page_items = _parse_top250_page(soup)
        data.extend(page_items)
        if len(page_items) < 25:
            break
    return {"from_cache": from_cache, "update_time": update_time, "data": data}


def _parse_top250_page(soup: BeautifulSoup) -> list[ListItem]:
    data: list[ListItem] = []
    for item in soup.select(".item"):
        anchor = item.select_one(".hd a[href]")
        title_element = item.select_one(".hd .title")
        href = str(anchor.get("href") or "").strip() if anchor else ""
        match = re.search(r"/subject/(\d+)", href)
        title = title_element.get_text(" ", strip=True) if title_element else ""
        if match is None or not title:
            continue
        item_id = match.group(1)
        rating = item.select_one(".rating_num")
        quote = item.select_one(".quote .inq")
        info = item.select_one(".bd p")
        votes = item.find(string=re.compile(r"\d+\s*人评价"))
        cover = item.select_one(".pic img")
        description = " · ".join(
            part
            for part in [
                f"评分：{rating.get_text(strip=True)}" if rating else None,
                info.get_text(" ", strip=True) if info else None,
                quote.get_text(" ", strip=True) if quote else None,
            ]
            if part
        )
        data.append(
            ListItem(
                id=item_id,
                title=title,
                desc=description or None,
                cover=cover.get("src") if cover else None,
                hot=_get_numbers(str(votes) if votes else None),
                url=href,
                mobileUrl=f"https://m.douban.com/movie/subject/{item_id}/",
            )
        )
    return data
