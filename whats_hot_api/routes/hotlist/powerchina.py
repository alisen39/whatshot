from __future__ import annotations

from urllib.parse import urlencode

from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import post

ROUTE_NAME = "powerchina"

type_map: dict[str, str] = {
    "notice": "招采公告",
    "change": "变更公告",
    "termination": "终止公告",
    "candidate": "中标候选人公示",
    "result": "中标/成交公示",
}

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "中国电建阳光采购网",
    "description": "中国电建公开招采公告、变更终止公告及中标公示",
    "params": {
        "type": {
            "name": "公告分类",
            "type": type_map,
        },
    },
    "link": "https://bid.powerchina.cn/",
}

_API_URL = (
    "https://bid.powerchina.cn/newcbs/recpro-newmember/"
    "BidAnnouncementSummary/list"
)
_MAX_ITEMS = 50


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    requested = request.query_params.get("type", "notice")
    selected = requested if requested in type_map else "notice"
    list_data = await _get_list(selected, no_cache)
    return RouterData(
        **ROUTE_META,
        type=type_map[selected],
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


async def _get_list(board_type: str, no_cache: bool) -> dict:
    announcement_type = type_map[board_type]
    result = await post(
        url=_API_URL,
        body={
            "pageNum": 1,
            "pageSize": _MAX_ITEMS,
            "announcementType": announcement_type,
            # The official site uses 3 for the combined public list.
            "companyType": "3",
        },
        no_cache=no_cache,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json;charset=utf-8",
            "Referer": "https://bid.powerchina.cn/",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        },
        cache_key=f"powerchina:{board_type}:latest:{_MAX_ITEMS}",
    )
    return {
        "from_cache": result.from_cache,
        "update_time": result.update_time,
        "data": _parse_rows(result.data, announcement_type),
    }


def _parse_rows(payload: object, announcement_type: str) -> list[ListItem]:
    if not isinstance(payload, dict) or payload.get("code") != 200:
        return []
    rows = payload.get("rows")
    if not isinstance(rows, list):
        return []

    data: list[ListItem] = []
    seen_ids: set[str] = set()
    for row in rows:
        item = _announcement_item(row, announcement_type)
        if item is None:
            continue
        if item.id in seen_ids:
            continue
        seen_ids.add(item.id)
        data.append(item)
        if len(data) >= _MAX_ITEMS:
            break
    return data


def _announcement_item(
    row: object,
    announcement_type: str,
) -> ListItem | None:
    if not isinstance(row, dict):
        return None
    item_id = _text(row.get("id"))
    title = _text(row.get("title"))
    publish_time = _text(row.get("publishTime"))
    if (
        not item_id
        or not title
        or not publish_time
        or _text(row.get("announcementType")) != announcement_type
        or str(row.get("isDeleted") or "0") not in {"0", "None"}
        or _text(row.get("isShow")) not in {"", "1"}
    ):
        return None

    desc_parts = []
    title_type = _text(row.get("titleTypeName"))
    source = _text(row.get("source"))
    project_number = _text(row.get("projectNumber"))
    registration_deadline = _text(row.get("registrationDeadline"))
    submission_deadline = _text(row.get("submissionDeadline"))
    bid_open_time = _text(row.get("bidOpenTime"))
    if title_type:
        desc_parts.append(f"类别：{title_type}")
    if source:
        desc_parts.append(f"来源：{source}")
    if project_number:
        desc_parts.append(f"项目编号：{project_number}")
    if registration_deadline:
        desc_parts.append(f"报名截止：{registration_deadline}")
    if submission_deadline:
        desc_parts.append(f"提交截止：{submission_deadline}")
    if bid_open_time:
        desc_parts.append(f"开标时间：{bid_open_time}")

    url = _detail_url(row, announcement_type)
    return ListItem(
        id=item_id,
        title=title,
        author=_text(row.get("procuringEntity") or row.get("author")) or None,
        desc=" · ".join(desc_parts) or None,
        hot=_integer(row.get("readCount")),
        timestamp=get_time(publish_time),
        url=url,
        mobileUrl=url,
    )


def _detail_url(row: dict, announcement_type: str) -> str:
    public_url = _text(row.get("publicUrl"))
    if public_url.startswith(("https://", "http://")):
        return public_url
    if str(row.get("isPublic") or "0") == "1":
        picture_url = _text(row.get("pictureUrl"))
        if picture_url.startswith(("https://", "http://")):
            return picture_url

    path = (
        "/consult/publicity"
        if announcement_type in {"中标候选人公示", "中标/成交公示"}
        else "/consult/notice"
    )
    query = urlencode(
        {
            "id": _text(row.get("id")),
            "type": announcement_type,
            "typeName": announcement_type,
            "path": path,
            "companyType": "3",
            "bidType": _scalar_text(row.get("bidType")),
        }
    )
    return f"https://bid.powerchina.cn/notice/detail?{query}"


def _text(value: object) -> str:
    return " ".join(str(value or "").split())


def _scalar_text(value: object) -> str:
    return "" if value is None else str(value).strip()


def _integer(value: object) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
