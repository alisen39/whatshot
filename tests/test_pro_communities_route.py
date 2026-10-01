"""pro-communities 路由测试：mock 共享 get，fixtures 依 board_api 证据结构净化内联。

证据来源：tmp/board_api/pro_communities/evidence/
（01_muchong_top_dayhot、04_muchong_top_digest、07_maimai_hot_rank、08_jike_topic_ai_explore）。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import pro_communities as route
from whats_hot_api.utils.http_client import RequestResult

_UPDATE_TIME = "2026-10-01T00:00:00+00:00"
_BEIJING = timezone(timedelta(hours=8))


def _request(board_type: str) -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/pro-communities",
            "query_string": f"type={board_type}".encode(),
            "headers": [],
        }
    )


def _fake_get(body, captured: dict | None = None):
    async def handler(url, headers=None, params=None, no_cache=None, **kwargs):
        if captured is not None:
            captured.update({"url": url, "headers": headers, "no_cache": no_cache, "kwargs": kwargs})
        return RequestResult(False, _UPDATE_TIME, body)

    return handler


def _ms(value: str) -> int:
    return int(datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=_BEIJING).timestamp() * 1000)


# ---------------------------------------------------------------- 小木虫


_MUCHONG_PAGE = """
<html><head><title>24小时热榜 - 小木虫</title></head><body>
<table><tbody>
<tr class="forum_list">
 <td class="icn"></td>
 <th class="thread-name">
  <span class="xmc_ft14"><a href="https://muchong.com/f-6-1">休闲灌水</a></span>
  <a href="/t-16812422-1">世上再无好汉歌</a>
 </th>
 <td class="by"><cite><a href="viewpro.php?uid=25229682">孤独的电子</a></cite><span class="xmc_b9">2026-09-26</span></td>
 <td class="num">7/350</td>
 <td class="by"><cite><nobr>2026-09-26 16:51:11</nobr></cite></td>
</tr>
<tr class="forum_list">
 <td class="icn"></td>
 <th class="thread-name">
  <span class="xmc_ft14"><a href="https://muchong.com/f-133-1">虫友互识</a></span>
  <a href="/t-16812795-1">北京诚征男友</a>
  <a href="/t-16812795-2">2</a>
 </th>
 <td class="by"><cite><a>月光风华</a></cite><span class="xmc_b9">2026-9-27</span></td>
 <td class="num">3/150</td>
</tr>
</tbody></table>
<a href="/t-11622561-1">清除COOKIES</a>
</body></html>
"""


@pytest.mark.asyncio
async def test_muchong_dayhot_maps_rows(monkeypatch):
    captured: dict = {}
    monkeypatch.setattr(route, "get", _fake_get(_MUCHONG_PAGE.encode("gbk"), captured))
    result = await route.handle_route(_request("muchong-dayhot"), no_cache=True)

    assert captured["url"] == "https://muchong.com/top-dayhot-1"
    assert captured["kwargs"]["response_type"] == "arraybuffer"  # GBK 页面自己解码
    first, second = result.data
    assert first.id == "16812422"
    assert first.title == "世上再无好汉歌"
    assert first.url == "https://muchong.com/t-16812422-1"
    assert first.hot == 7  # 「回复/查看」取回复数（查看数恒为回复数 × 50，不是浏览量）
    assert first.author == "孤独的电子"
    assert first.desc == "休闲灌水"
    assert first.timestamp == _ms("2026-09-26")  # 页面只到日，北京时间当天 0 点
    # 分页链接（/t-<tid>-2 文字是页码）不算标题；未补零日期同样解析
    assert second.id == "16812795"
    assert second.title == "北京诚征男友"
    assert second.timestamp == _ms("2026-09-27")


@pytest.mark.asyncio
async def test_muchong_wrong_board_page_is_rejected(monkeypatch):
    # 排行榜 URL 对不上的榜会渲染出别的页；页面里没有「散金热榜」字样按改版报错
    monkeypatch.setattr(route, "get", _fake_get(_MUCHONG_PAGE.encode("gbk")))
    with pytest.raises(RuntimeError, match="散金热榜"):
        await route.handle_route(_request("muchong-scredit"), no_cache=True)


# ---------------------------------------------------------------- 脉脉


def _next_page(props: dict) -> str:
    import json

    return (
        '<!DOCTYPE html><html><head><script id="__NEXT_DATA__" type="application/json">'
        + json.dumps({"props": {"pageProps": props}}, ensure_ascii=False)
        + "</script></head><body></body></html>"
    )


@pytest.mark.asyncio
async def test_maimai_hot_maps_topics(monkeypatch):
    captured: dict = {}
    props = {
        "topics": [
            {"id": "nEqkkV9X", "type": 9, "name": "OpenAI再次暂停其最强模型训练", "view_count": 1049,
             "icon": "https://i9.taou.com/maimai/p/27373/1526_53_914RyDspxGoExsxz",
             "hot_type_card": {"text": "热议", "color": "", "hot_type": 2}},
            {"id": "abc123", "type": None, "name": "无角标话题", "view_count": None,
             "icon": None, "hot_type_card": {"text": "", "color": "", "hot_type": 0}},
        ]
    }
    monkeypatch.setattr(route, "get", _fake_get(_next_page(props), captured))
    result = await route.handle_route(_request("maimai-hot"), no_cache=True)

    assert captured["url"] == "https://maimai.cn/n/content/hot-rank/topic"
    first, second = result.data
    assert first.id == "nEqkkV9X"
    assert first.title == "OpenAI再次暂停其最强模型训练"
    assert first.url == "https://maimai.cn/n/content/global-topic?circle_type=9&topic_id=nEqkkV9X"
    assert first.hot == 1049
    assert first.cover == "https://i9.taou.com/maimai/p/27373/1526_53_914RyDspxGoExsxz"
    assert first.desc == "热议"  # hot_type_card 角标文字
    assert first.timestamp is None  # 数据里没有时间
    assert second.url.endswith("circle_type=9&topic_id=abc123")  # type 缺省按 9
    assert second.desc is None
    assert second.timestamp is None


@pytest.mark.asyncio
async def test_maimai_missing_next_data_is_rejected(monkeypatch):
    monkeypatch.setattr(route, "get", _fake_get("<html>改版了</html>"))
    with pytest.raises(RuntimeError, match="__NEXT_DATA__"):
        await route.handle_route(_request("maimai-hot"), no_cache=True)


# ---------------------------------------------------------------- 即刻


@pytest.mark.asyncio
async def test_jike_maps_posts_with_title_from_content(monkeypatch):
    captured: dict = {}
    props = {
        "topic": {"id": "63579abb6724cc583b9bba9a", "name": "AI探索站"},
        "posts": [
            {"id": "6ab69e93141b85b2926a94eb", "content": "第一行是标题\n第二行正文", "type": "ORIGINAL_POST",
             "likeCount": 46, "createdAt": "2026-09-25T16:17:23.420Z",
             "user": {"screenName": "郦橙锦妖Vanessa"}, "pictures": []},
            {"id": "bbbb", "content": "长" * 90, "type": "REPOST", "likeCount": 3,
             "createdAt": "2026-09-24T08:00:00.000Z", "user": None,
             "pictures": [{"picUrl": "https://i9.taou.com/pic.jpg"}]},
        ],
    }
    monkeypatch.setattr(route, "get", _fake_get(_next_page(props), captured))
    result = await route.handle_route(_request("jike-ai-explore"), no_cache=True)

    assert captured["url"] == "https://m.okjike.com/topics/63579abb6724cc583b9bba9a"
    first, second = result.data
    assert first.id == "6ab69e93141b85b2926a94eb"
    assert first.title == "第一行是标题"  # 帖子没有标题，取正文第一行
    assert first.url == "https://m.okjike.com/originalPosts/6ab69e93141b85b2926a94eb"
    assert first.hot == 46  # likeCount
    assert first.author == "郦橙锦妖Vanessa"
    expected = int(datetime(2026, 9, 25, 16, 17, 23, 420000, tzinfo=UTC).timestamp() * 1000)
    assert first.timestamp == expected  # createdAt ISO → 毫秒
    assert second.url == "https://m.okjike.com/reposts/bbbb"  # REPOST → reposts 路径
    assert second.title == "长" * 80 + "…"  # 超 80 字截断
    assert second.cover == "https://i9.taou.com/pic.jpg"
    assert second.author is None


@pytest.mark.asyncio
async def test_jike_empty_content_post_is_skipped(monkeypatch):
    props = {"topic": {"id": "x"}, "posts": [
        {"id": "has-content", "content": "正文", "likeCount": 1, "createdAt": "2026-09-24T08:00:00.000Z"},
        {"id": "no-content", "content": "", "likeCount": 2},
    ]}
    monkeypatch.setattr(route, "get", _fake_get(_next_page(props)))
    result = await route.handle_route(_request("jike-pm-daily"), no_cache=True)
    assert [item.id for item in result.data] == ["has-content"]


# ---------------------------------------------------------------- 入口


@pytest.mark.asyncio
async def test_unknown_board_is_rejected():
    with pytest.raises(ValueError, match="Unknown board 'dxy-hot'"):
        await route.handle_route(_request("dxy-hot"), no_cache=True)


def test_type_map_declares_all_boards():
    assert len(route._TYPE_MAP) == 9
    assert next(iter(route._TYPE_MAP)) == "muchong-dayhot"  # 声明序第一个是默认榜
    assert set(route._TYPE_MAP) == set(route._MUCHONG) | set(route._JIKE) | {"maimai-hot"}
    assert route.ROUTE_META["params"]["type"]["type"] is route._TYPE_MAP
