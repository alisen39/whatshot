"""澎湃新闻频道与栏目(www.thepaper.cn 频道页 / 栏目页 / 首页同款 contentapi 接口)。

board_api 单元 `tmp/board_api/thepaper_channels` 的 1:1 迁移,证据见该目录 README 与
`analysis_report.md`、`verify/page_vs_api.md`、`verify/min_request.log`。21 个子榜,
全部是 `api.thepaper.cn/contentapi/*` 的 POST JSON 接口(页面 XHR 同款),无签名、
无 cookie,三种页面三种取法:

- 栏目页 `www.thepaper.cn/list_<nodeId>`(16 个):`nodeCont/getByNodeIdPortal
  {nodeId, pageSize:20, pageNum:1}`,接口顺序就是页面服务端渲染的列表(置顶条最前);
  `pageNum` 实测不起作用,翻页靠返回的 `startTime`,这里只取第 1 页。
- 频道页 `www.thepaper.cn/channel_<channelId>`(国际、思想、科技、暖闻 4 个):
  `channel/normalTopInfo {channelId}` 取头条区(文字头条 `recommendTxt`、轮播
  `recommendImg`),再 `nodeCont/getByChannelId {channelId, excludeContIds,
  listRecommendIds, pageSize:20, startTime:""}` 取信息流(开头是编辑钉住的"推荐"条)。
- 首页要闻:`wwwIndex/recommendNews {}` 取头条区(该接口用 `resultCode=1` 表示成功),
  再 `getByChannelId {channelId:""}` 取"时间排序"视图的信息流,两步调用与首页 JS
  时间排序分支逐参数一致;首页缺省的"频道排序"分频道区块在首页 SSR 数据里
  (`recommendNews` 响应没有该字段),取不到,不取。

输出顺序照页面 JS 渲染树(文字头条区在轮播上面):文字头条 → 轮播 → 信息流,
按 contId 去重、留先出现的位置。国际、思想、科技、暖闻现在文字头条为空,
输出就是轮播 → 信息流。

与既有路由的边界:whatshot 的 `thepaper` 路由只取 cache.thepaper.cn 的
`wwwIndex/rightSidebar`(首页侧栏热榜、财经资讯、编辑精选),不含频道与栏目;
本路由另起名 `thepaper-channels`,两者数据源不同、子榜不重叠。

反爬口径(board_api 实测):
- `api.thepaper.cn` 在腾讯云 WAF 后面:不带 Referer 一律 403「WAF拦截页面」,
  带任意非空 Referer 就是 200(页面 XHR 自带),这里带 `Referer: https://www.thepaper.cn/`;
  返回 HTML(如 WAF 拦截页)时 JSON 解析失败,按错误处理,不静默降级。
- `Content-Type: application/json` 必需,不带返回 `code=99998 系统繁忙`。
- 同站(thepaper.cn,api 与 www 共用)两次真实上游请求至少隔 3 秒
  (board_api 脚本口径,3 秒 1 次从未被拦);只对真实发出的请求计时,缓存命中不占时限。

字段口径(与既有 thepaper 路由一致):
- id=contId;author=nodeInfo.name(所属栏目名);hot=praiseTimes 点赞数,"1.2万"换算 12000;
  timestamp=pubTimeLong(毫秒)。首页文字头条条目不带 nodeInfo,author 为空。
- 条目带 link(外链、澎湃早晚报、合集页)时 url 用 link(与页面 href 一致),
  否则拼站内详情页;mobileUrl 站内条目用 m.thepaper.cn。
- 列表接口不带摘要,desc 恒空;频道 / 首页信息流是编辑推荐顺序,不是时间顺序
  (开头几条是 listRecommendIds 钉住的推荐位)。
- 暖闻频道头条区里的 `nwHighQualityContent`(精选辑)与 `nwChannelHotList`(热榜入口)
  是专题模块,不是文章条目,不输出。
"""

from __future__ import annotations

import asyncio
import re
import time
from typing import Any

from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.get_time import get_time
from whats_hot_api.utils.http_client import RequestResult, post

ROUTE_NAME = "thepaper-channels"

_API = "https://api.thepaper.cn/contentapi"
_WWW = "https://www.thepaper.cn"
_PAGE_SIZE = 20  # 页面"加载更多"每次取 20 条(list / channel / index 三个页面 JS 一致)

# 子榜键 -> (中文名, 类型, id)。类型:node=栏目(getByNodeIdPortal)、
# channel=频道(normalTopInfo + getByChannelId)、home=首页要闻(recommendNews + getByChannelId)。
# 声明序第一个(yaowen)是默认榜。
_BOARDS: dict[str, tuple[str, str, str]] = {
    "yaowen": ("首页要闻", "home", ""),
    "guoji": ("国际", "channel", "122908"),
    "sixiang": ("思想", "channel", "25952"),
    "keji": ("科技", "channel", "119908"),
    "nuanwen": ("暖闻", "channel", "136261"),
    "shanghai-shuping": ("上海书评", "node", "26878"),
    # tophub 的"专栏":原站没有叫"专栏"的栏目,证据核对 tophub 前 3 条的详情页
    # nodeInfo 都是"理论·学术"(25536),第 1 条就是 25536 的置顶条
    "lilun-xueshu": ("专栏（理论·学术）", "node", "25536"),
    "zhongnanhai": ("中南海", "node", "25488"),
    "zhengku": ("中国政库", "node", "25462"),
    "renshi-fengxiang": ("人事风向", "node", "25423"),
    "sixiang-shichang": ("思想市场", "node", "25483"),
    "dahuji": ("打虎记", "node", "25490"),
    "wenhuake": ("文化课", "node", "25450"),
    "wenyifan": ("文艺范", "node", "26609"),
    "youxi": ("有戏", "node", "25448"),
    "zhiji-xianchang": ("直击现场", "node", "25428"),
    "shelun": ("社论", "node", "25444"),
    "meishuke": ("美数课", "node", "25635"),
    "fanshudang": ("翻书党", "node", "25574"),
    "yulunchang": ("舆论场", "node", "25489"),
    # tophub 的"评论":证据核对前 3 条(马上评、夜读等)的详情页 nodeInfo 都是
    # "澎湃评论"(27224);顶级"评论"频道(-24)是舆论场与澎湃评论混排,与 tophub 不符
    "pengpai-pinglun": ("评论（澎湃评论）", "node", "27224"),
}

type_map: dict[str, str] = {key: label for key, (label, _, _) in _BOARDS.items()}

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "澎湃新闻",
    "description": "澎湃新闻首页要闻、频道（国际、思想、科技、暖闻）与栏目（中南海、社论、上海书评等）列表",
    "link": _WWW + "/",
    "params": {
        "type": {
            "name": "频道 / 栏目",
            "type": type_map,
        },
    },
}

_HEADERS = {
    # Referer 是 WAF 硬门槛(任意非空即可,取页面地址);Content-Type 缺了返回 code=99998
    "Content-Type": "application/json;charset=UTF-8",
    "Accept": "application/json, text/plain, */*",
    "Referer": _WWW + "/",
}

# board_api 口径:thepaper.cn(api 与 www 算一个站)两次真实上游请求至少隔 3 秒
# (3 秒 1 次从未被拦);只对真实发出的上游请求计时,from_cache 不占时限。
_RATE_LIMIT_SECONDS = 3.0
_throttle_lock = asyncio.Lock()
_last_upstream_at = 0.0


async def _polite_delay() -> None:
    """两次真实上游请求之间至少隔 _RATE_LIMIT_SECONDS。"""
    global _last_upstream_at
    async with _throttle_lock:
        wait = _RATE_LIMIT_SECONDS - (time.monotonic() - _last_upstream_at)
        if wait > 0:
            await asyncio.sleep(wait)
        _last_upstream_at = time.monotonic()


def _page_url(board: str) -> str:
    """子榜对应的原站页面(board_api 输出的响应级 link)。"""
    _, kind, ident = _BOARDS[board]
    if kind == "home":
        return _WWW + "/"
    return f"{_WWW}/{'list' if kind == 'node' else 'channel'}_{ident}"


async def _post_json(path: str, body: dict[str, Any], no_cache: bool) -> tuple[dict[str, Any], RequestResult]:
    """POST 一个 contentapi 接口并校验业务壳。

    `nodeCont/*` 与 `channel/*` 用 `code=200` 表示成功;`wwwIndex/recommendNews`
    用 `resultCode=1`(没有 code 字段)。HTML 错误页(腾讯云 WAF 拦截页)JSON 解析
    即失败,与业务错误壳一样按错误抛出,不静默降级为空榜。
    """
    url = f"{_API}/{path}"
    await _polite_delay()
    try:
        result = await post(url=url, body=body, headers=_HEADERS, no_cache=no_cache)
    except ValueError as exc:  # JSONDecodeError:拿到的是 HTML(如 WAF 拦截页)而不是 JSON
        raise RuntimeError(f"ThePaper {path} returned non-JSON (possible WAF block page): {exc}") from exc
    payload = result.data if isinstance(result.data, dict) else {}
    if (
        payload.get("code") not in (200, None)
        or payload.get("resultCode") not in (1, None)
        or not isinstance(payload.get("data"), dict)
    ):
        raise RuntimeError(f"ThePaper {path} returned an error shell: {str(payload)[:200]}")
    return payload["data"], result


def _flatten(value: Any) -> list[dict[str, Any]]:
    """recommendTxt 是分组的二维数组(如 [[头条], [a, b, c]]),recommendImg 是一维数组,统一摊平。"""
    out: list[dict[str, Any]] = []
    for entry in value or []:
        if isinstance(entry, list):
            out += _flatten(entry)
        elif isinstance(entry, dict):
            out.append(entry)
    return out


def _hot(value: Any) -> int | None:
    """点赞数:整数字符串直接取;过万时是 "1.2万" 写法,换算成 12000;空、"-" 留空。"""
    match = re.fullmatch(r"(\d+(?:\.\d+)?)(万?)", str(value or "").strip())
    if not match:
        return None
    return round(float(match.group(1)) * (10000 if match.group(2) else 1))


def _item(row: dict[str, Any]) -> ListItem | None:
    cont_id = str(row.get("contId") or "").strip()
    title = re.sub(r"\s+", " ", str(row.get("name") or "")).strip()
    if not cont_id or not title:
        return None
    node_info = row.get("nodeInfo")
    link = str(row.get("link") or "").strip()
    return ListItem(
        id=cont_id,
        title=title,
        # 页面对有 link 的条目(外链、澎湃早晚报、合集页)直接用 link 作 href,其余是站内详情页
        url=link or f"{_WWW}/newsDetail_forward_{cont_id}",
        mobileUrl=link or f"https://m.thepaper.cn/newsDetail_forward_{cont_id}",
        cover=row.get("pic") or None,
        # 所属栏目名,与 thepaper 路由一致;首页文字头条接口不带 nodeInfo
        author=node_info.get("name") if isinstance(node_info, dict) else None,
        hot=_hot(row.get("praiseTimes")),  # 与 thepaper 路由一致取点赞数
        timestamp=get_time(row.get("pubTimeLong")),  # 毫秒
    )


def _parse_items(rows: list[Any]) -> list[ListItem]:
    """按上游顺序解析条目,按 contId 去重、留先出现的位置(头条区与信息流推荐位可能重复)。"""
    items: list[ListItem] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        item = _item(row)
        if item and item.id not in seen:
            seen.add(item.id)
            items.append(item)
    return items


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    type_param = request.query_params.get("type", "yaowen")
    if type_param not in _BOARDS:
        raise ValueError(f"Unknown board '{type_param}' for route '{ROUTE_NAME}'")
    label, kind, ident = _BOARDS[type_param]
    if kind == "node":
        data, result = await _post_json(
            "nodeCont/getByNodeIdPortal",
            {"nodeId": int(ident), "pageSize": _PAGE_SIZE, "pageNum": 1},
            no_cache,
        )
        rows: list[Any] = data.get("list") or []
    else:
        # 频道页:channel/normalTopInfo;首页:wwwIndex/recommendNews(首页 JS 不带参数)。两者返回结构相同
        if kind == "home":
            top, _ = await _post_json("wwwIndex/recommendNews", {}, no_cache)
        else:
            top, _ = await _post_json("channel/normalTopInfo", {"channelId": ident}, no_cache)
        # 信息流照页面调用:排除头条区已出现的条目、带上钉住的推荐位;首页 channelId 是空串
        flow, result = await _post_json(
            "nodeCont/getByChannelId",
            {
                "channelId": ident,
                "excludeContIds": top.get("excludeContIds") or [],
                "listRecommendIds": top.get("listRecommendIds") or [],
                "pageSize": _PAGE_SIZE,
                "startTime": "",
            },
            no_cache,
        )
        # 输出照页面渲染树:文字头条区在最上面,下面是轮播,再下面是信息流
        rows = _flatten(top.get("recommendTxt")) + _flatten(top.get("recommendImg")) + (flow.get("list") or [])
    items = _parse_items(rows)
    if not items:
        # 错误页 / 业务错误壳之外的空解析同样不静默降级为空榜
        raise RuntimeError(f"ThePaper channels '{type_param}' parsed no items")
    return RouterData(
        **{**ROUTE_META, "link": _page_url(type_param)},  # 响应级 link 用该榜的原站页面
        type=label,
        total=len(items),
        fromCache=result.from_cache,
        updateTime=result.update_time,
        data=items,
    )
