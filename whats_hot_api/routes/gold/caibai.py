from __future__ import annotations

import json

from starlette.requests import Request

from whats_hot_api.models import RouterData
from whats_hot_api.routes.gold._common import GOLD_CACHE_TTL, gold_item, gold_response
from whats_hot_api.utils.http_client import post

ROUTE_NAME = "caibai"
SOURCE_LINK = "http://cbwx.bjcaibai.com.cn/wbap/#/"
_API_URL = "http://111.198.86.222/BAP/OpenApi"

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "菜百首饰",
    "description": "菜百首饰北京地区黄金零售人民币报价",
    "link": SOURCE_LINK,
}

_PAYLOAD = json.dumps(
    {
        "Context": {
            "token": "",
            "version": "",
            "from": "2",
            "mchid": "",
            "appid": "",
            "timestamp": "",
        },
        "SQLBuilderItem": [
            {
                "SQLBuilderID": "{005A5001-B9AD-41CB-8409-8F7675D19143}",
                "TableName": "BS_POS_GP_MA",
                "Caption": "每日金价",
                "Enabled": True,
                "Save": [],
                "Execute": [],
                "Select": {
                    "FMID": "{9753EB2A-C629-4DE4-8A92-5A425560150C}",
                    "FPID": "{9753EB2A-C629-4DE4-8A92-5A425560150C}",
                    "FTID": "",
                    "FUID": "",
                    "FOID": "{7D77D027-9824-4156-A25E-12FC59527DDE}",
                    "FWID": "",
                    "FORG_STORE_ID": "",
                },
            }
        ],
    },
    ensure_ascii=False,
)

_ITEM_IDS = {
    "足金饰品": "gold-jewellery",
    "足金999饰品": "gold-999-jewellery",
    "足金999饰品金条": "gold-999-bar",
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    result = await post(
        url=_API_URL,
        headers={"content-type": "application/x-www-form-urlencoded;"},
        body=_PAYLOAD,
        no_cache=no_cache,
        ttl=GOLD_CACHE_TTL,
        cache_key=_API_URL,
    )
    payload = result.data if isinstance(result.data, dict) else {}
    blocks = (
        payload.get("JsonData")
        if str(payload.get("JsonResult")).lower() == "true"
        else []
    )
    rows: list[dict] = []
    if isinstance(blocks, list):
        for block in blocks:
            if isinstance(block, dict) and isinstance(block.get("ROW"), list):
                rows = [row for row in block["ROW"] if isinstance(row, dict)]
                break

    items = []
    for row in rows:
        title = str(row.get("FKIND_NAME") or "").strip()
        item_id = _ITEM_IDS.get(title)
        if item_id is None:
            continue
        items.append(
            gold_item(
                item_id=item_id,
                title=title,
                url=SOURCE_LINK,
                sell_price=row.get("FPRICE_BASE"),
                quote_time=row.get("FNEWTIME"),
                note="北京地区实体店参考价，实际以门店公示为准",
            )
        )
    return gold_response(route_meta=ROUTE_META, result=result, items=items)
