from __future__ import annotations

import re
from urllib.parse import urlencode

from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import post

ROUTE_NAME = "szse-rules"

# 深交所"全部业务规则"页面(lawrules/rule/allrules/bussiness/index.html)是空壳,
# 列表由 articleList.js POST /api/search/content(concatversion.js: search_path + "/content")
# 渲染;本路由发页面第 1 页的同一个请求,返回顺序即页面顺序。
# 表单与页面一致:实测只有 keyword(字段必须存在、可为空串,缺了 400)和 channelCode[]
# (缺了返回全站 530 多万条)是必需的;其余字段保留,避免服务端缺省值变化时与页面不一致
# (board_api verify/param_matrix.jsonl)。
_API = "https://www.szse.cn/api/search/content"
_CHANNEL = "szserulesAllRulesBuss"  # 页面 cmsParam.currentMenuId:"全部规则 > 全部业务规则"
_PAGE_SIZE = 20  # 与官方页面每页一致;服务端上限 50
_FORM = {
    "keyword": "",
    "time": "0",
    "range": "title",
    "channelCode[]": _CHANNEL,
    "currentPage": "1",
    "pageSize": str(_PAGE_SIZE),
    "scope": "0",
}
# httpx 发 content= 字符串时不自动带表单头;实测 JSON 体或 text/plain 都返回 400
_FORM_HEADERS = {"Content-Type": "application/x-www-form-urlencoded"}

type_map = {
    "hot": "全部业务规则",
}

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "深圳证券交易所",
    "description": "深交所本所业务规则 · 全部业务规则(最新发布的规则通知)",
    "link": "https://www.szse.cn/lawrules/rule/allrules/bussiness/index.html",
    "params": {
        "type": {
            "name": "榜单",
            "type": type_map,
        },
    },
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    board_type = request.query_params.get("type", "hot")
    if board_type not in type_map:
        raise ValueError(f"Unknown board '{board_type}' for route '{ROUTE_NAME}'")
    # 实测 UA/Referer/X-Requested-With/cookie 都不需要(param_matrix 的 4 组请求头矩阵)
    result = await post(
        url=_API, headers=_FORM_HEADERS, body=urlencode(_FORM), no_cache=no_cache
    )
    payload = result.data if isinstance(result.data, dict) else {}
    # 业务错误壳:keyword 缺失等场景返回 {"code":"400","msg":"null"}
    code = payload.get("code")
    if code is not None and str(code) != "200":
        raise RuntimeError(
            f"SZSE rules API returned code={code} message={payload.get('msg')}"
        )
    docs = payload.get("data")
    if not isinstance(docs, list):
        # 接口路径失效后常见 200 + HTML 错误页:拿不到行数组属于源变更,按路由错误上报
        # (与 kuaishou_index 等路由一致用 RuntimeError,不是调用方的 TypeError)
        raise RuntimeError(  # noqa: TRY004
            f"SZSE rules API response has no data list (totalSize={payload.get('totalSize')})"
        )
    items = _items(docs)
    if not items:
        raise RuntimeError("SZSE rules list produced no parsable items")
    return RouterData(
        **ROUTE_META,
        type=type_map[board_type],
        total=len(items),
        fromCache=result.from_cache,
        updateTime=result.update_time,
        data=items,
    )


def _text(value: object) -> str:
    # 页面 replaceTitle 同款:标题里可能有搜索高亮 <em> 标签,一律剥掉
    return " ".join(re.sub(r"<[^>]+>", "", str(value or "")).split())


def _items(docs: list) -> list[ListItem]:
    items: list[ListItem] = []
    for doc in docs:
        if not isinstance(doc, dict):
            continue
        doc_id = doc.get("id")
        title = _text(doc.get("doctitle"))
        url = str(doc.get("docpuburl") or "").strip()
        if not doc_id or not title or not url.startswith(("http://", "https://")):
            continue
        # docpubtime 已是毫秒;docpuburl 是 http:// 照上游原样输出(与官方页面一致,https 也能打开)
        items.append(
            ListItem(
                id=str(doc_id),  # 文档号,与详情页文件名 t日期_文档号.html 一致
                title=title,
                url=url,
                mobileUrl=url,
                desc=_text(doc.get("doccontent")) or None,
                timestamp=get_time(doc.get("docpubtime")),
            )
        )
    return items
