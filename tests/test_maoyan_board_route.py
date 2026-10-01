from __future__ import annotations

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import maoyan_board
from whats_hot_api.utils.http_client import RequestResult

# 从 evidence/01_board_7.response.body（热映口碑榜）净化：结构保留
# dl.board-wrapper > dd（名次 / 链接 / 片名 / 海报 data-src / 主演 / 上映时间 / 评分）
# + p.update-time + ul.list-pager（口碑榜本没有分页器，这里用 expected 榜的分页结构测 message）
_PRAISE_HTML = """
<html><head><title>热映口碑榜 - 猫眼电影</title></head><body>
<p class="update-time">
        2026-09-30
    </p>
<dl class="board-wrapper">
<dd>
  <i class="board-index board-index-1">1</i>
  <a href="/films/1297" title="肖申克的救赎" class="image-link">
    <img data-src="https://p0.pipi.cn/mediaplus/bigdata_mmdb_mmdbtask/e42958bf.jpg?imageView2/1/w/160/h/220" class="board-img" />
  </a>
  <div class="board-item-main"><div class="board-item-content"><div class="movie-item-info">
    <p class="name"><a href="/films/1297" title="肖申克的救赎">肖申克的救赎</a></p>
    <p class="star">主演：蒂姆·罗宾斯,摩根·弗里曼,鲍勃·冈顿</p>
    <p class="releasetime">上映时间：2026-08-28</p>
  </div><div class="movie-item-number score-num">
    <p class="score"><i class="integer">9.</i><i class="fraction">8</i></p>
  </div></div></div>
</dd>
<dd>
  <i class="board-index board-index-2">2</i>
  <a href="/films/1462628" title="欢迎来龙餐馆" class="image-link">
    <img data-src="https://p0.pipi.cn/mediaplus/friday_image_fe/e429589a.png?imageView2/1/w/160/h/220" class="board-img" />
  </a>
  <div class="board-item-main"><div class="board-item-content"><div class="movie-item-info">
    <p class="name"><a href="/films/1462628" title="欢迎来龙餐馆">欢迎来龙餐馆</a></p>
    <p class="star">主演：沈腾,蒋奇明</p>
    <p class="releasetime">上映时间：2026</p>
  </div><div class="movie-item-number score-num">
    <p class="score"><i class="integer">9.</i><i class="fraction">7</i></p>
  </div></div></div>
</dd>
</dl>
</body></html>
"""

# evidence/02_board_6（最受期待榜）的条目结构：没有 p.score，有想看数（stonefont 加密，
# fixture 里省略）；分页器 5 页
_EXPECTED_HTML = """
<html><body>
<p class="update-time">2026-09-30</p>
<dl class="board-wrapper">
<dd>
  <i class="board-index board-index-1">1</i>
  <a href="/films/7220536" class="image-link">
    <img data-src="https://p0.pipi.cn/mediaplus/friday_image_fe/aaa.jpg?imageView2/1/w/160/h/220" class="board-img" />
  </a>
  <div class="board-item-main"><div class="board-item-content"><div class="movie-item-info">
    <p class="name"><a href="/films/7220536">浪浪山小妖怪</a></p>
    <p class="star">主演：配音</p>
    <p class="releasetime">上映时间：2025-07-08</p>
  </div></div></div>
</dd>
</dl>
<ul class="list-pager"><a class="active">1</a><a href="?offset=10">2</a><a href="?offset=20">3</a>
<a href="?offset=30">4</a><a href="?offset=40">5</a></ul>
</body></html>
"""


def _request(board_type: str) -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/maoyan-board",
        "query_string": f"type={board_type}".encode(),
        "headers": [],
    })


@pytest.mark.asyncio
async def test_praise_board_maps_fields_and_score(monkeypatch):
    captured = {}

    async def fake_get(url, headers=None, params=None, no_cache=None, **kwargs):
        captured.update({"url": url, "headers": headers, "no_cache": no_cache})
        return RequestResult(False, "2026-10-01T00:00:00+00:00", _PRAISE_HTML)

    monkeypatch.setattr(maoyan_board, "get", fake_get)
    result = await maoyan_board.handle_route(_request("praise"), no_cache=True)

    assert captured["url"] == "https://www.maoyan.com/board/7"
    # probe.log：python-httpx 缺省 UA 被 403，必须带浏览器 UA
    assert "Mozilla/5.0" in captured["headers"]["User-Agent"]

    assert result.type == "热映口碑榜"
    assert result.total == 2
    assert result.fromCache is False
    item = result.data[0]
    assert item.id == "1297"
    assert item.title == "肖申克的救赎"
    assert item.url == "https://www.maoyan.com/films/1297"
    assert item.mobileUrl == "https://m.maoyan.com/asgard/movie/1297"
    assert item.cover == "https://p0.pipi.cn/mediaplus/bigdata_mmdb_mmdbtask/e42958bf.jpg?imageView2/1/w/160/h/220"
    assert item.desc == "评分 9.8 · 主演：蒂姆·罗宾斯,摩根·弗里曼,鲍勃·冈顿 · 上映时间：2026-08-28"
    # 上映日期按北京时间 0 点换算成毫秒
    assert item.timestamp == 1787846400000
    # 票房 / 想看数是 stonefont 加密，不破解，hot 留空
    assert item.hot is None
    assert "榜单日期 2026-09-30" in (result.message or "")


@pytest.mark.asyncio
async def test_release_date_only_year_is_empty_and_pager_noted(monkeypatch):
    async def fake_get(url, headers=None, params=None, no_cache=None, **kwargs):
        assert url == "https://www.maoyan.com/board/6"
        return RequestResult(True, "t", _EXPECTED_HTML)

    monkeypatch.setattr(maoyan_board, "get", fake_get)
    result = await maoyan_board.handle_route(_request("expected"), no_cache=False)

    item = result.data[0]
    # 最受期待榜没有 p.score，desc 不含评分
    assert item.desc == "主演：配音 · 上映时间：2025-07-08"
    assert item.timestamp == 1751904000000  # 2025-07-08 北京时间 0 点
    assert result.fromCache is True
    # 分页器 5 页写进 message，需要全榜时由调用方按 ?offset=10…40 翻页
    assert "分页器共 5 页（?offset=10…40）" in (result.message or "")


@pytest.mark.asyncio
async def test_verify_page_without_board_wrapper_is_an_error(monkeypatch):
    """频繁请求会跳 verify.maoyan.com 验证页；解析不到 board-wrapper 直接报错，不绕过。"""

    async def fake_get(url, headers=None, params=None, no_cache=None, **kwargs):
        return RequestResult(False, "t", "<html><body>请完成安全验证</body></html>")

    monkeypatch.setattr(maoyan_board, "get", fake_get)
    with pytest.raises(RuntimeError, match="no board-wrapper"):
        await maoyan_board.handle_route(_request("top100"), no_cache=True)


@pytest.mark.asyncio
async def test_unknown_type_is_rejected(monkeypatch):
    async def fake_get(url, headers=None, params=None, no_cache=None, **kwargs):
        raise AssertionError("unknown type must not hit upstream")

    monkeypatch.setattr(maoyan_board, "get", fake_get)
    # 北美票房榜 board/2 停更（2018-07-16），不在本路由
    with pytest.raises(ValueError, match="Unknown board"):
        await maoyan_board.handle_route(_request("us-box-office"), no_cache=True)


@pytest.mark.asyncio
async def test_duplicate_movie_ids_keep_first_and_rank_gap_noted(monkeypatch):
    dup = _PRAISE_HTML.replace('href="/films/1462628" title="欢迎来龙餐馆"', 'href="/films/1297" title="欢迎来龙餐馆"')
    dup = dup.replace('board-index-2">2<', 'board-index-2">5<')

    async def fake_get(url, headers=None, params=None, no_cache=None, **kwargs):
        return RequestResult(False, "t", dup)

    monkeypatch.setattr(maoyan_board, "get", fake_get)
    result = await maoyan_board.handle_route(_request("praise"), no_cache=True)
    # 按影片 id 去重，保留首次出现的名次
    assert [item.id for item in result.data] == ["1297"]
    assert "页面名次不连续" in (result.message or "")
