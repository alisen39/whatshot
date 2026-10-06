from __future__ import annotations

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import juejin_infoq
from whats_hot_api.utils.http_client import RequestResult

# fixtures 依据 tmp/board_api/juejin_infoq/evidence 的 captured_data 净化内联。
_JJ_ARTICLE = {
    "article_id": "7688298824980987919",
    "title": "ValidX 多租户系统的数据验证方案",
    "brief_content": "多租户架构：从共享到隔离的三种模式",
    "cover_image": "",
    "ctime": "1790130509",
    "hot_index": 659,
}
_JJ_AUTHOR = {"user_name": "vipxieliang"}
_IQ_ROW_ARTICLE = {
    "uuid": "qEHi6k5ycwXUiasvfNKH",
    "type": 1,
    "sub_type": 0,
    "source": 1,
    "views": 12887,
    "publish_time": 1790145802416,
    "article_title": "智谱把 ZCode 开源了，然后呢？",
    "article_summary": "一个只有两条 Commit 的开源仓库",
    "article_cover": "https://static001.infoq.cn/resource/image/ab.png",
    "author": [{"nickname": "蔡芳芳"}],
    "no_author": "",
    "translator": None,
}
_IQ_FEED_XML = """<?xml version="1.0" encoding="utf-8"?><rss version="2.0"><channel>
<title>InfoQ</title><link>https://www.infoq.cn</link>
<item><title>谷歌 Kotlin 版 ADK 实现与 Python 版功能对齐</title>
<link>https://www.infoq.cn/article/sQV4EomjPP0J3hM3lyF9?utm_source=rss&amp;utm_medium=article</link>
<description>点击查看原文</description>
<author>作者：Sergio De Simone</author>
<guid>https://www.infoq.cn/article/sQV4EomjPP0J3hM3lyF9?utm_source=rss&amp;utm_medium=article</guid>
<pubDate>Sun, 27 Sep 2026 10:00:00 GMT</pubDate></item>
</channel></rss>"""


def _request(board_type: str | None) -> Request:
    query = f"type={board_type}" if board_type is not None else ""
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/juejin-infoq",
        "query_string": query.encode(),
        "headers": [],
    })


@pytest.mark.asyncio
async def test_default_weekly_posts_all_feed_body(monkeypatch):
    captured = {}

    async def fake_post(url, body=None, headers=None, no_cache=None, **kwargs):
        captured.update({"url": url, "body": body, "headers": headers})
        return RequestResult(True, "2026-10-01T00:00:00+00:00", {
            "err_no": 0,
            "data": [{"item_type": 2, "item_info": {"article_info": _JJ_ARTICLE, "author_user_info": _JJ_AUTHOR}}],
        })

    monkeypatch.setattr(juejin_infoq, "post", fake_post)
    result = await juejin_infoq.handle_route(_request(None), no_cache=True)

    # 首页流：sort_type 必需（weekly_hottest=7），翻页 cursor 第 1 页固定 "0"，一页 20 条
    assert captured["url"] == "https://api.juejin.cn/recommend_api/v1/article/recommend_all_feed"
    assert captured["body"] == {"id_type": 2, "client_type": 2608, "sort_type": 7, "cursor": "0", "limit": 20}
    assert captured["headers"]["Referer"] == "https://juejin.cn/"
    assert result.type == "全站本周最热"
    assert result.fromCache is True
    item = result.data[0]
    assert item.id == "7688298824980987919"
    assert item.url == item.mobileUrl == "https://juejin.cn/post/7688298824980987919"
    assert item.hot == 659
    assert item.author == "vipxieliang"
    # ctime 秒（字符串）归一化为毫秒
    assert item.timestamp == 1790130509000
    # cover_image 为空串归 None
    assert item.cover is None


@pytest.mark.asyncio
async def test_cate_feed_uses_cate_id_and_sort(monkeypatch):
    captured = {}

    async def fake_post(url, body=None, headers=None, no_cache=None, **kwargs):
        captured.update({"url": url, "body": body})
        return RequestResult(False, "t", {"err_no": 0, "data": [{"article_info": _JJ_ARTICLE, "author_user_info": _JJ_AUTHOR}]})

    monkeypatch.setattr(juejin_infoq, "post", fake_post)
    result = await juejin_infoq.handle_route(_request("juejin-frontend-hot"))

    # 分类流直接是文章（无 item_info 一层）；前端热门 = 30 天内最热 sort_type=30
    assert captured["url"] == "https://api.juejin.cn/recommend_api/v1/article/recommend_cate_feed"
    assert captured["body"] == {
        "id_type": 2,
        "sort_type": 30,
        "cate_id": "6809637767543259144",
        "cursor": "0",
        "limit": 20,
    }
    assert result.type == "前端热门"
    assert result.link == "https://juejin.cn/frontend?sort=monthly_hottest"


@pytest.mark.asyncio
async def test_freebie_hot_uses_popular_sort_and_bare_link(monkeypatch):
    async def fake_post(url, body=None, headers=None, no_cache=None, **kwargs):
        assert body["sort_type"] == 200
        assert body["cate_id"] == "6809637771511070734"
        return RequestResult(False, "t", {"err_no": 0, "data": [{"article_info": _JJ_ARTICLE, "author_user_info": _JJ_AUTHOR}]})

    monkeypatch.setattr(juejin_infoq, "post", fake_post)
    result = await juejin_infoq.handle_route(_request("juejin-freebie-hot"))
    # 分类缺省推荐流页面上没有 sort 参数
    assert result.link == "https://juejin.cn/freebie"
    assert result.type == "开发工具热门"


@pytest.mark.asyncio
async def test_non_article_rows_are_skipped(monkeypatch):
    async def fake_post(url, body=None, headers=None, no_cache=None, **kwargs):
        return RequestResult(False, "t", {
            "err_no": 0,
            "data": [
                {"item_type": 1, "item_info": {"item_type": 1}},  # 广告等非文章条目
                "not-a-dict",
                {"article_info": _JJ_ARTICLE, "author_user_info": _JJ_AUTHOR},
            ],
        })

    monkeypatch.setattr(juejin_infoq, "post", fake_post)
    result = await juejin_infoq.handle_route(_request("juejin-newest"))
    assert result.type == "全站最新"
    assert result.total == 1
    assert result.data[0].id == "7688298824980987919"


@pytest.mark.asyncio
async def test_booklet_posts_course_default_sort10(monkeypatch):
    captured = {}

    async def fake_post(url, body=None, headers=None, no_cache=None, **kwargs):
        captured.update({"url": url, "body": body})
        return RequestResult(False, "t", {
            "err_no": 0,
            "data": [{
                "booklet_id": "7657050404161355803",
                "base_info": {"title": "实战：手把手做一个 Mini Code Agent", "summary": "从零实现",
                              "cover_img": "https://p1-jj.byteimg.com/cover.png", "buy_count": 120},
                "user_info": {"user_name": "掘金作者"},
            }],
        })

    monkeypatch.setattr(juejin_infoq, "post", fake_post)
    result = await juejin_infoq.handle_route(_request("juejin-booklet"))

    # 课程页缺省与"全部"页签发的就是 sort=10
    assert captured["url"] == "https://api.juejin.cn/booklet_api/v1/booklet/listbycategory"
    assert captured["body"] == {"category_id": "0", "cursor": "0", "sort": 10, "is_vip": 0, "limit": 20}
    item = result.data[0]
    assert item.id == "7657050404161355803"
    assert item.url == "https://juejin.cn/book/7657050404161355803"
    assert item.hot == 120  # 购买数
    assert item.author == "掘金作者"
    # 小册没有单一"发布时间"，留空
    assert item.timestamp is None


@pytest.mark.asyncio
async def test_infoq_hot_7d_body_headers_and_url_rules(monkeypatch):
    captured = {}

    async def fake_post(url, body=None, headers=None, no_cache=None, **kwargs):
        captured.update({"url": url, "body": body, "headers": headers})
        return RequestResult(False, "t", {
            "code": 0,
            "data": [
                _IQ_ROW_ARTICLE,
                {**_IQ_ROW_ARTICLE, "uuid": "newsUuid1", "sub_type": 4},  # type=1 且 sub_type=4 → /news/
                {**_IQ_ROW_ARTICLE, "uuid": "xieUuid1", "source": 2},  # source=2 → xie.infoq.cn
                {**_IQ_ROW_ARTICLE, "uuid": "videoUuid1", "type": 24},  # 视频 → /video/
                {**_IQ_ROW_ARTICLE, "uuid": "noauth1", "author": [], "no_author": "作者：佚名"},
                {**_IQ_ROW_ARTICLE, "uuid": "trans1", "author": [], "no_author": "", "translator": [{"nickname": "译者甲"}]},
            ],
        })

    monkeypatch.setattr(juejin_infoq, "post", fake_post)
    result = await juejin_infoq.handle_route(_request("infoq-hot-7d"))

    # 热点页"7天"页签：type=1、首屏 size=30；Referer/Origin 至少其一，都不带是 HTTP 451
    assert captured["url"] == "https://www.infoq.cn/public/v1/article/getHotList"
    assert captured["body"] == {"type": 1, "size": 30}
    assert captured["headers"]["Referer"] == "https://www.infoq.cn/"
    assert result.type == "7天热点"
    assert result.link == "https://www.infoq.cn/hotlist?tag=day"
    items = result.data
    assert items[0].url == "https://www.infoq.cn/article/qEHi6k5ycwXUiasvfNKH"
    assert items[1].url == "https://www.infoq.cn/news/newsUuid1"
    assert items[2].url == "https://xie.infoq.cn/article/xieUuid1"
    assert items[3].url == "https://www.infoq.cn/video/videoUuid1"
    # 作者兜底链：author[].nickname -> no_author 去"作者：" -> translator[].nickname
    assert items[0].author == "蔡芳芳"
    assert items[4].author == "佚名"
    assert items[5].author == "译者甲"
    # publish_time 毫秒原样保留
    assert items[0].timestamp == 1790145802416
    assert items[0].hot == 12887


@pytest.mark.asyncio
async def test_infoq_recommend_posts_misspelled_recommond(monkeypatch):
    async def fake_post(url, body=None, headers=None, no_cache=None, **kwargs):
        # 接口名就是 recommond（拼对的 my/recommend 反而 404）
        assert url == "https://www.infoq.cn/public/v1/my/recommond"
        assert body == {"size": 30}
        return RequestResult(False, "t", {"code": 0, "data": [_IQ_ROW_ARTICLE]})

    monkeypatch.setattr(juejin_infoq, "post", fake_post)
    result = await juejin_infoq.handle_route(_request("infoq-recommend"))
    assert result.type == "推荐"
    assert result.link == "https://www.infoq.cn/"


@pytest.mark.asyncio
async def test_infoq_feed_parses_rss(monkeypatch):
    async def fake_get(url, headers=None, no_cache=None, response_type="text", **kwargs):
        assert url == "https://www.infoq.cn/feed"
        assert response_type == "text"
        return RequestResult(False, "t", _IQ_FEED_XML)

    monkeypatch.setattr(juejin_infoq, "get", fake_get)
    result = await juejin_infoq.handle_route(_request("infoq-feed"))
    item = result.data[0]
    assert result.type == "InfoQ中国"
    # RSS 的 guid 带 utm，原样作 id
    assert item.id.endswith("?utm_source=rss&utm_medium=article")
    assert item.timestamp == 1790503200000


@pytest.mark.asyncio
async def test_business_error_shells_raise(monkeypatch):
    async def fake_post(url, body=None, headers=None, no_cache=None, **kwargs):
        if "juejin" in url:
            return RequestResult(False, "t", {"err_no": 130001, "err_msg": "内部错误"})
        return RequestResult(False, "t", {"code": 451, "data": None})

    monkeypatch.setattr(juejin_infoq, "post", fake_post)
    with pytest.raises(RuntimeError, match="err_no=130001"):
        await juejin_infoq.handle_route(_request("juejin-weekly"))
    with pytest.raises(RuntimeError, match="code=451"):
        await juejin_infoq.handle_route(_request("infoq-hot-7d"))


@pytest.mark.asyncio
async def test_empty_lists_raise(monkeypatch):
    async def fake_post(url, body=None, headers=None, no_cache=None, **kwargs):
        return RequestResult(False, "t", {"err_no": 0, "data": []})

    monkeypatch.setattr(juejin_infoq, "post", fake_post)
    with pytest.raises(RuntimeError, match="no items"):
        await juejin_infoq.handle_route(_request("juejin-ios-weekly"))


def test_unknown_board_is_rejected():
    import asyncio

    with pytest.raises(ValueError, match="Unknown board"):
        asyncio.run(juejin_infoq.handle_route(_request("article_rank")))
