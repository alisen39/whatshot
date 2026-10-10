"""IMDb 官方榜单（7 个子榜），数据走 IMDb GraphQL 接口。

board_api（tmp/board_api/imdb_charts）已验证的结论，本模块忠实移植：
- ``www.imdb.com/chart/*`` 前面有 AWS WAF（202 + ``x-amzn-waf-action: challenge`` 的 JS
  质询页），纯 HTTP 拿不到数据；数据源改用 IMDb 官方 GraphQL 接口，无 WAF、无签名、
  无 cookie，唯一硬性要求是 ``x-imdb-client-name`` 非空（缺了或为空返回 awselb 403）。
- 六个评分 / 热度榜是 ``chartTitles(chart: {chartType: ...})``，一次请求取全量；
  票房榜是 ``boxOfficeWeekendChart``，美国最近一个完整周末的前 10 名（接口没有日期参数）。
- 标题语言由 ``x-imdb-user-country`` 决定（DE 德语、TW 繁体中文；``x-imdb-user-language``
  不影响标题，推翻性验证更正）。固定 US 输出英文原名，与 tophub 展示一致。
- ``hot``：评分榜（top/toptv/top-english/bottom）取投票人数（评分是小数，写进 desc）；
  票房榜取周末票房（美元）；moviemeter/tvmeter 接口只给名次不给数值，留空。
- ``timestamp`` 留空：上映日期不是榜单条目的发布时间，且 2001-09 以前的毫秒值会被
  公共模型误当秒再乘 1000（Top 250 有 146 部）。
- 严格拒绝错误壳：GraphQL ``errors``、条数与接口声明 ``total`` 不符（如扩榜）、空列表
  都直接报错，不静默截断。
"""
from __future__ import annotations

from typing import Any

from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.http_client import post

ROUTE_NAME = "imdb-charts"

_API = "https://caching.graphql.imdb.com/"
_HEADERS = {
    "content-type": "application/json",
    # 必需：缺了或为空字符串时 awselb 直接 403；实测任意非空值都行。
    # 用 IMDb 网页前端的客户端名（公开资料里的值）。
    "x-imdb-client-name": "imdb-web-next-localized",
    # 标题语言由 x-imdb-user-country 决定；固定 US 输出英文原名。不要删掉这个头，
    # 否则换出口国家时可能拿到本地化标题。
    "x-imdb-user-language": "en-US",
    "x-imdb-user-country": "US",
}

# 子榜 → (中文名, GraphQL ChartTitleType 枚举, 一次取全的条数, 对应 IMDb 网页)。
# 声明序第一个是默认榜；条数取接口返回的 total，返回条数不符时报错而不是静默截断。
_BOARDS: dict[str, tuple[str, str, int, str]] = {
    "top": ("Top 250 电影", "TOP_RATED_MOVIES", 250, "https://www.imdb.com/chart/top/"),
    "toptv": ("Top 250 剧集", "TOP_RATED_TV_SHOWS", 250, "https://www.imdb.com/chart/toptv/"),
    "top-english": (
        "最受好评的英语电影",
        "TOP_RATED_ENGLISH_MOVIES",
        250,
        "https://www.imdb.com/chart/top-english-movies/",
    ),
    "boxoffice": ("最高票房（美国）", "", 10, "https://www.imdb.com/chart/boxoffice/"),
    "bottom": ("烂片榜 Bottom 100", "LOWEST_RATED_MOVIES", 100, "https://www.imdb.com/chart/bottom/"),
    "moviemeter": ("热门电影 MOVIEmeter", "MOST_POPULAR_MOVIES", 100, "https://www.imdb.com/chart/moviemeter/"),
    "tvmeter": ("热门剧集 TVmeter", "MOST_POPULAR_TV_SHOWS", 100, "https://www.imdb.com/chart/tvmeter/"),
}

type_map: dict[str, str] = {key: label for key, (label, _, _, _) in _BOARDS.items()}

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "IMDb",
    "description": "IMDb 官方榜单：Top 250 电影 / 剧集、最受好评的英语电影、美国周末票房、烂片榜、热门电影 / 剧集",
    "link": "https://www.imdb.com/chart/top/",
    "params": {"type": {"name": "榜单", "type": type_map}},
}

# 按评分排的榜：hot 取投票人数；热度榜按 MOVIEmeter 名次排，接口不给名次背后的数值。
_RATING_CHARTS = {"top", "toptv", "top-english", "bottom"}

# GraphQL 查询语句（board_api 手写并逐字段实测；网页前端用的是 persisted query，
# 没有浏览器抓不到，IMDb 改字段时这里会收到 400 GRAPHQL_VALIDATION_FAILED）。
_TITLE_FIELDS = """
  id
  titleText { text }
  titleType { id }
  releaseYear { year endYear }
  runtime { seconds }
  certificate { rating }
  ratingsSummary { aggregateRating voteCount }
  primaryImage { url }
  plot { plotText { plainText } }
"""
_CHART_QUERY = (
    "query ImdbChart($chartType: ChartTitleType!, $first: Int!) {\n"
    "  chartTitles(first: $first, chart: {chartType: $chartType}) {\n"
    "    total\n"
    "    pageInfo { hasNextPage }\n"
    "    edges { currentRank node { "
    + _TITLE_FIELDS +
    " } }\n"
    "  }\n"
    "}"
)
_BOXOFFICE_QUERY = (
    "query ImdbBoxOffice {\n"
    "  boxOfficeWeekendChart(limit: 10) {\n"
    "    weekendStartDate\n"
    "    weekendEndDate\n"
    "    entries {\n"
    "      weekendGross { total { amount currency } }\n"
    "      title { "
    + _TITLE_FIELDS +
    " lifetimeGross(boxOfficeArea: DOMESTIC) { total { amount currency } } }\n"
    "    }\n"
    "  }\n"
    "}"
)


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    path_type = request.query_params.get("type", "top")
    if path_type not in _BOARDS:
        raise ValueError(f"Unknown board '{path_type}' for route '{ROUTE_NAME}'")
    label, _, _, link = _BOARDS[path_type]
    if path_type == "boxoffice":
        rows = await _fetch_boxoffice(no_cache)
    else:
        rows = await _fetch_chart(path_type, no_cache)
    return RouterData(
        **{**ROUTE_META, "link": link},
        type=label,
        total=len(rows["data"]),
        fromCache=rows["from_cache"],
        updateTime=rows["update_time"],
        data=rows["data"],
        message=rows.get("message"),
    )


async def _graphql(
    query: str, variables: dict[str, Any], path_type: str, no_cache: bool
) -> tuple[dict, bool, str]:
    """POST 一条 GraphQL 查询并校验响应壳；WAF 页 / errors 一律报错。

    返回 ``(data, fromCache, updateTime)``。
    """
    try:
        result = await post(
            url=_API,
            headers=_HEADERS,
            body={"query": query, "variables": variables},
            no_cache=no_cache,
            cache_key=f"{ROUTE_NAME}:{path_type}",
        )
    except ValueError as exc:  # JSONDecodeError：拿到的是 HTML（如 WAF 质询页）而不是 JSON
        raise RuntimeError(f"IMDb GraphQL response is not JSON (possible AWS WAF challenge page): {exc}") from exc
    payload = result.data
    if not isinstance(payload, dict):
        raise RuntimeError("IMDb GraphQL response is not a JSON object (error shell or WAF page)")  # noqa: TRY004
    # 校验失败等错误壳：{"errors": [...]}，可能没有 data 键
    if payload.get("errors"):
        messages = [str(error.get("message")) for error in payload["errors"][:3] if isinstance(error, dict)]
        raise RuntimeError(f"IMDb GraphQL returned errors: {messages}")
    if "data" not in payload:
        raise RuntimeError("IMDb GraphQL response has no 'data' key (error shell or WAF page)")
    return payload.get("data") or {}, result.from_cache, result.update_time


async def _fetch_chart(path_type: str, no_cache: bool) -> dict:
    _, chart_type, size, _ = _BOARDS[path_type]
    data, from_cache, update_time = await _graphql(
        _CHART_QUERY, {"chartType": chart_type, "first": size}, path_type, no_cache
    )
    chart = data.get("chartTitles") or {}
    edges = chart.get("edges") or []
    if not edges:
        raise RuntimeError(f"IMDb chart {chart_type} returned no edges")
    # 榜单条数变了（如扩成 Top 500）时直接报错，不静默截断。
    if (chart.get("pageInfo") or {}).get("hasNextPage") or len(edges) != chart.get("total"):
        raise RuntimeError(
            f"IMDb chart {chart_type} returned {len(edges)} edges but total={chart.get('total')}; adjust requested size"
        )
    items: list[ListItem] = []
    for edge in sorted(edges, key=lambda item: item.get("currentRank") or 0):
        node = edge.get("node") or {}
        votes = (node.get("ratingsSummary") or {}).get("voteCount")
        items.append(_item(node, votes if path_type in _RATING_CHARTS else None, rank=edge.get("currentRank")))
    return {"from_cache": from_cache, "update_time": update_time, "data": items}


async def _fetch_boxoffice(no_cache: bool) -> dict:
    data, from_cache, update_time = await _graphql(_BOXOFFICE_QUERY, {}, "boxoffice", no_cache)
    chart = data.get("boxOfficeWeekendChart") or {}
    entries = chart.get("entries") or []
    if not entries:
        raise RuntimeError("IMDb boxOfficeWeekendChart returned no entries")
    items: list[ListItem] = []
    for entry in entries:
        node = entry.get("title") or {}
        weekend = ((entry.get("weekendGross") or {}).get("total") or {}).get("amount")
        lifetime = ((node.get("lifetimeGross") or {}).get("total") or {}).get("amount")
        items.append(
            _item(
                node,
                weekend,
                [
                    f"周末票房 {_money(weekend)}" if weekend else None,
                    f"累计 {_money(lifetime)}" if lifetime else None,
                ],
            )
        )
    weekend_range = f"{chart.get('weekendStartDate')} ~ {chart.get('weekendEndDate')}"
    return {
        "from_cache": from_cache,
        "update_time": update_time,
        "data": items,
        "message": f"美国周末票房：{weekend_range}",
    }


def _years(node: dict[str, Any]) -> str | None:
    release = node.get("releaseYear") or {}
    year, end = release.get("year"), release.get("endYear")
    if not year:
        return None
    if (node.get("titleType") or {}).get("id") in {"tvSeries", "tvMiniSeries"}:
        return f"{year}–{end}" if end and end != year else (f"{year}" if end else f"{year}–")
    return str(year)


def _runtime(node: dict[str, Any]) -> str | None:
    seconds = (node.get("runtime") or {}).get("seconds")
    if not seconds:
        return None
    hours, minutes = divmod(round(seconds / 60), 60)
    return f"{hours}h {minutes}m" if hours and minutes else (f"{hours}h" if hours else f"{minutes}m")


def _money(amount: Any) -> str | None:
    return f"${amount:,}" if isinstance(amount, int) else None


def _item(node: dict[str, Any], hot: Any, extra: list[str | None] | None = None, rank: Any = None) -> ListItem:
    title_id = str(node.get("id") or "").strip()
    if not title_id:
        raise RuntimeError("IMDb GraphQL node is missing its tconst id")
    url = f"https://www.imdb.com/title/{title_id}/"
    rating = (node.get("ratingsSummary") or {}).get("aggregateRating")
    votes = (node.get("ratingsSummary") or {}).get("voteCount")
    parts = [
        *(extra or []),
        f"评分 {float(rating):.1f}（{votes:,} 人评分）" if rating and votes else None,
        _years(node),
        _runtime(node),
        (node.get("certificate") or {}).get("rating"),
        (((node.get("plot") or {}).get("plotText")) or {}).get("plainText"),
    ]
    desc = " · ".join(part for part in parts if part) or None
    # 分级标记(R/PG-13 等)是条目唯一的原生标识,desc 里已有一份
    certificate = str((node.get("certificate") or {}).get("rating") or "").strip()
    seconds = (node.get("runtime") or {}).get("seconds")
    return ListItem(
        id=title_id,
        title=((node.get("titleText") or {}).get("text") or "").strip() or title_id,
        url=url,
        mobileUrl=url,
        hot=hot,
        cover=(node.get("primaryImage") or {}).get("url"),
        badges=[{"text": certificate}] if certificate else [],
        metrics={"votes": votes} if isinstance(votes, int) and not isinstance(votes, bool) and votes > 0 else None,
        durationSeconds=seconds if isinstance(seconds, int) and not isinstance(seconds, bool) and seconds > 0 else None,
        sourceRank=rank if isinstance(rank, int) and not isinstance(rank, bool) and rank > 0 else None,
        desc=desc,
    )
