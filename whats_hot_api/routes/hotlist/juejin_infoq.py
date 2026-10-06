from __future__ import annotations

from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.feed import parse_feed
from whats_hot_api.utils.http_client import get, post

ROUTE_NAME = "juejin-infoq"

# 掘金与 InfoQ 中文站（tophub 的 16 个节点；牛客 trending whatshot 已支持，不在本路由）。
# 与既有路由的边界：juejin 路由只有文章热榜（article_rank?type=hot，"3 天内"）和
# sort_type=200 的推荐流，分类 type 走的是另一个接口；infoq 路由是英文站 infoq.com 的
# feed。本路由照 board_api 口径另起：掘金"X本周最热"是分类页 7 天热榜
# （recommend_cate_feed sort_type=7），不是 whatshot 既有 article_rank。
# 声明序第一个是缺省榜（juejin-weekly，全站本周最热），照 board_api 口径。
_BOARDS: dict[str, tuple[str, str, str, int]] = {
    # board: (榜名, 取数方式, 分类键, sort_type)
    "juejin-weekly": ("全站本周最热", "all", "", 7),
    "juejin-newest": ("全站最新", "all", "", 300),
    "juejin-android-weekly": ("Android本周最热", "cate", "android", 7),
    "juejin-ios-weekly": ("iOS本周最热", "cate", "ios", 7),
    "juejin-ai-weekly": ("人工智能本周最热", "cate", "ai", 7),
    "juejin-frontend-weekly": ("前端本周最热", "cate", "frontend", 7),
    "juejin-backend-weekly": ("后端本周最热", "cate", "backend", 7),
    "juejin-freebie-weekly": ("工具资源本周最热", "cate", "freebie", 7),
    "juejin-article-weekly": ("阅读本周最热", "cate", "article", 7),
    # 三个"热门"口径不同（照 tophub 快照条目核对过）：前端热门是 30 天内最热（30），
    # 开发工具热门、阅读热门是分类页缺省推荐流（200，前端叫 popular）
    "juejin-frontend-hot": ("前端热门", "cate", "frontend", 30),
    "juejin-freebie-hot": ("开发工具热门", "cate", "freebie", 200),
    "juejin-article-hot": ("阅读热门", "cate", "article", 200),
    "juejin-booklet": ("小册", "booklet", "", 0),
    "infoq-hot-7d": ("7天热点", "iq-hot", "", 1),
    "infoq-feed": ("InfoQ中国", "iq-feed", "", 0),
    "infoq-recommend": ("推荐", "iq-recommend", "", 0),
}

# 掘金分类 id（GET tag_api/v1/query_category_briefs）与分类页路径
_JJ_CATS: dict[str, tuple[str, str]] = {
    "frontend": ("6809637767543259144", "frontend"),
    "backend": ("6809637769959178254", "backend"),
    "android": ("6809635626879549454", "android"),
    "ios": ("6809635626661445640", "ios"),
    "ai": ("6809637773935378440", "ai"),
    "freebie": ("6809637771511070734", "freebie"),  # 分类名"开发工具"，tophub 叫"工具资源"
    "article": ("6809637772874219534", "article"),  # 分类名"阅读"，分类页地址 /article
}

# 前端 JS 里的 sort 名 -> sort_type 映射（popular:200 / newest:300 /
# weekly_hottest:7 / monthly_hottest:30；本路由用到的四个）
_SORT_NAMES: dict[int, str] = {200: "popular", 300: "newest", 7: "weekly_hottest", 30: "monthly_hottest"}

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "掘金 / InfoQ",
    "description": "掘金首页与分类页的最新、本周最热、30 天最热、推荐流和小册；InfoQ 中文站 7 天热点、首页推荐与官方 RSS。",
    "link": "https://juejin.cn/",
    "params": {
        "type": {
            "name": "榜单",
            "type": {key: value[0] for key, value in _BOARDS.items()},
        },
    },
}

_JJ_API = "https://api.juejin.cn"
_JJ_HEADERS = {"Referer": "https://juejin.cn/", "Origin": "https://juejin.cn"}
_JJ_LIMIT = 20  # 掘金前端每页 limit 20
_IQ_API = "https://www.infoq.cn/public/v1"
# InfoQ 两个 JSON 接口必须带 Referer 或 Origin 至少其一，都不带返回 HTTP 451
_IQ_HEADERS = {"Referer": "https://www.infoq.cn/", "Origin": "https://www.infoq.cn"}
_IQ_FEED = "https://www.infoq.cn/feed"
_IQ_FIRST_PAGE = 30  # 热点页、首页推荐流首屏都是 getList(30)
# InfoQ 前端（article-item 组件）按 type 拼链接：1 文章（sub_type=4 是资讯）、
# 8 迷你书、16 演讲、24 视频、60 专题、65 专辑
_IQ_PATHS: dict[int, str] = {1: "article", 8: "minibook", 16: "talk", 24: "video", 60: "theme", 65: "album"}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    board = request.query_params.get("type", "juejin-weekly")
    if board not in _BOARDS:
        raise ValueError(f"Unknown board '{board}' for route '{ROUTE_NAME}'")
    label, mode, cat, sort = _BOARDS[board]
    if mode == "all":
        list_data = await _get_juejin_articles(
            f"{_JJ_API}/recommend_api/v1/article/recommend_all_feed",
            {"id_type": 2, "client_type": 2608, "sort_type": sort, "cursor": "0", "limit": _JJ_LIMIT},
            no_cache,
        )
        link = f"https://juejin.cn/?sort={_SORT_NAMES[sort]}"
    elif mode == "cate":
        cate_id, path = _JJ_CATS[cat]
        list_data = await _get_juejin_articles(
            f"{_JJ_API}/recommend_api/v1/article/recommend_cate_feed",
            {"id_type": 2, "sort_type": sort, "cate_id": cate_id, "cursor": "0", "limit": _JJ_LIMIT},
            no_cache,
        )
        link = f"https://juejin.cn/{path}" + ("" if sort == 200 else f"?sort={_SORT_NAMES[sort]}")
    elif mode == "booklet":
        list_data = await _get_booklets(no_cache)
        link = "https://juejin.cn/course"
    elif mode == "iq-hot":
        list_data = await _get_infoq_json("article/getHotList", {"type": sort, "size": _IQ_FIRST_PAGE}, no_cache)
        link = "https://www.infoq.cn/hotlist?tag=day"
    elif mode == "iq-recommend":
        list_data = await _get_infoq_json("my/recommond", {"size": _IQ_FIRST_PAGE}, no_cache)
        link = "https://www.infoq.cn/"
    else:
        list_data = await _get_infoq_feed(no_cache)
        link = "https://www.infoq.cn/"
    return RouterData(
        **{**ROUTE_META, "link": link},
        type=label,
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


async def _get_juejin_articles(url: str, body: dict, no_cache: bool) -> dict:
    result = await post(url=url, body=body, headers=_JJ_HEADERS, no_cache=no_cache)
    payload = result.data if isinstance(result.data, dict) else {}
    if payload.get("err_no") != 0:
        raise RuntimeError(f"Juejin API returned err_no={payload.get('err_no')} message={payload.get('err_msg')}")
    rows = payload.get("data")
    if not isinstance(rows, list):
        # 壳变形按抓取失败处理,不是调用方类型错
        raise RuntimeError("Juejin feed response data is not a list (feed changed)")  # noqa: TRY004
    items = []
    for row in rows:
        # 首页流每条包一层 item_info（item_type=2 是文章），分类流直接是文章
        info = row.get("item_info") if isinstance(row, dict) and "item_info" in row else row
        if not isinstance(info, dict):
            continue
        article = info.get("article_info") or {}
        article_id = str(article.get("article_id") or "").strip()
        title = str(article.get("title") or "").strip()
        if not article_id or not title:
            continue  # 广告等非文章条目没有 article_info
        link = f"https://juejin.cn/post/{article_id}"
        items.append(
            ListItem(
                id=article_id,
                title=title,
                url=link,
                mobileUrl=link,
                hot=article.get("hot_index"),  # 热榜按 hot_index 降序
                cover=article.get("cover_image") or None,
                author=(info.get("author_user_info") or {}).get("user_name"),
                desc=(str(article.get("brief_content") or "").strip() or None),
                timestamp=article.get("ctime"),  # 秒（字符串），models 统一 ×1000
            )
        )
    if not items:
        raise RuntimeError("Juejin feed returned no items")
    return {"from_cache": result.from_cache, "update_time": result.update_time, "data": items}


async def _get_booklets(no_cache: bool) -> dict:
    # 课程页 juejin.cn/course 缺省和"全部"页签发的就是 sort=10（页面 JS
    # Number(query.sort||10)），tophub 跟的"不带 sort"顺序页面已看不到
    result = await post(
        url=f"{_JJ_API}/booklet_api/v1/booklet/listbycategory",
        body={"category_id": "0", "cursor": "0", "sort": 10, "is_vip": 0, "limit": _JJ_LIMIT},
        headers=_JJ_HEADERS,
        no_cache=no_cache,
    )
    payload = result.data if isinstance(result.data, dict) else {}
    if payload.get("err_no") != 0:
        raise RuntimeError(f"Juejin booklet API returned err_no={payload.get('err_no')} message={payload.get('err_msg')}")
    rows = payload.get("data")
    if not isinstance(rows, list):
        # 壳变形按抓取失败处理,不是调用方类型错
        raise RuntimeError("Juejin booklet response data is not a list (feed changed)")  # noqa: TRY004
    items = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        base = row.get("base_info") or {}
        booklet_id = str(row.get("booklet_id") or base.get("booklet_id") or "").strip()
        title = str(base.get("title") or "").strip()
        if not booklet_id or not title:
            continue
        link = f"https://juejin.cn/book/{booklet_id}"
        items.append(
            ListItem(
                id=booklet_id,
                title=title,
                url=link,
                mobileUrl=link,
                hot=base.get("buy_count"),  # 购买数
                cover=base.get("cover_img") or None,
                author=(row.get("user_info") or {}).get("user_name"),
                desc=(str(base.get("summary") or "").strip() or None),
                # 小册没有单一"发布时间"（ctime 是创建时间，put_on_time 多为批量重新上架日），留空
            )
        )
    if not items:
        raise RuntimeError("Juejin booklet list returned no items")
    return {"from_cache": result.from_cache, "update_time": result.update_time, "data": items}


async def _get_infoq_json(path: str, body: dict, no_cache: bool) -> dict:
    result = await post(url=f"{_IQ_API}/{path}", body=body, headers=_IQ_HEADERS, no_cache=no_cache)
    payload = result.data if isinstance(result.data, dict) else {}
    rows = payload.get("data")
    if payload.get("code") != 0 or not isinstance(rows, list):
        raise RuntimeError(f"InfoQ {path} returned code={payload.get('code')} (feed changed)")
    items = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        item_id = str(row.get("uuid") or row.get("aid") or "").strip()
        title = str(row.get("article_title") or "").strip()
        if not item_id or not title:
            continue
        link = _infoq_url(row, item_id)
        items.append(
            ListItem(
                id=item_id,
                title=title,
                url=link,
                mobileUrl=link,
                hot=row.get("views"),  # 阅读数
                cover=row.get("article_cover") or None,
                author=_infoq_author(row),
                desc=(str(row.get("article_summary") or "").strip() or None),
                timestamp=row.get("publish_time"),  # 毫秒，models 原样保留；无效值归 None
            )
        )
    if not items:
        raise RuntimeError(f"InfoQ {path} returned no items")
    return {"from_cache": result.from_cache, "update_time": result.update_time, "data": items}


def _infoq_url(row: dict, item_id: str) -> str:
    # 照前端 article-item 组件的规则拼链接：source=2 走 xie.infoq.cn；type=1 且
    # sub_type=4 是资讯 news；其余按 type 取路径，未知 type 照文章处理
    if row.get("source") == 2:
        return f"https://xie.infoq.cn/article/{item_id}"
    kind = row.get("type")
    path = "news" if kind == 1 and row.get("sub_type") == 4 else _IQ_PATHS.get(kind if isinstance(kind, int) else 1, "article")
    return f"https://www.infoq.cn/{path}/{item_id}"


def _infoq_author(row: dict) -> str | None:
    def names(key: str) -> list[str]:
        return [
            str(entry["nickname"])
            for entry in row.get(key) or []
            if isinstance(entry, dict) and entry.get("nickname")
        ]

    # 没有署名作者时取 no_author（去掉"作者："前缀），再没有取译者
    author = "、".join(names("author"))
    if author:
        return author
    no_author = str(row.get("no_author") or "").strip()
    if no_author:
        return no_author.removeprefix("作者：").strip() or None
    return "、".join(names("translator")) or None


async def _get_infoq_feed(no_cache: bool) -> dict:
    result = await get(
        url=_IQ_FEED,
        headers={"Accept": "application/rss+xml, application/xml;q=0.9, */*;q=0.8"},
        response_type="text",
        no_cache=no_cache,
    )
    items = parse_feed(result.data)
    if not items:
        raise RuntimeError("InfoQ RSS returned no items")
    return {"from_cache": result.from_cache, "update_time": result.update_time, "data": items}
