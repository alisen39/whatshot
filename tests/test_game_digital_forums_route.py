from __future__ import annotations

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import game_digital_forums
from whats_hot_api.utils.http_client import RequestResult


def _request(board_type: str) -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/game-digital-forums",
        "query_string": f"type={board_type}".encode(),
        "headers": [],
    })


_DISCUZ_PAGE = """<html><body>
<tbody id="stickthread_100"><tr>
<td class="by"><cite><a>置顶作者</a></cite><em><span title="2026-9-30 08:00">半小时前</span></em></td>
<th><a href="thread-100-1-1.html" class="xst">置顶帖标题</a></th>
<td class="num"><em>500</em></td></tr></tbody>
<tbody id="normalthread_101"><tr>
<td class="by"><cite><a>作者一</a></cite><em>2026-9-30 07:50</em></td>
<th><a href="thread-101-1-1.html" class="xst">普通帖标题</a></th>
<td class="num"><em>1,234</em></td></tr></tbody>
</body></html>"""


@pytest.mark.asyncio
async def test_discuz_board_parses_pinned_first_and_fields(monkeypatch):
    captured = {}

    async def fake_get(url, no_cache=None, **kwargs):
        captured["url"] = url
        return RequestResult(False, "2026-10-01T00:00:00+00:00", _DISCUZ_PAGE)

    monkeypatch.setattr(game_digital_forums, "get", fake_get)
    result = await game_digital_forums.handle_route(_request("s1-anime"), no_cache=True)

    assert "fid=6" in captured["url"] and "filter=author" in captured["url"]
    assert result.type.startswith("Stage1st")
    assert [i.id for i in result.data] == ["100", "101"]  # 置顶在前
    first, second = result.data
    assert first.desc == "置顶"
    assert first.hot == 500
    assert first.timestamp is not None
    assert second.hot == 1234  # 千分位兼容
    assert second.author == "作者一"
    assert second.url == "https://stage1st.com/2b/thread-101-1-1.html"


RSS_SAMPLE = (
    "<?xml version=\"1.0\"?><rss><channel>"
    "<item><guid>https://stage1st.com/2b/thread-2290788-1-1.html</guid>"
    "<title>全站最新帖</title><link>https://stage1st.com/2b/thread-2290788-1-1.html</link></item>"
    "</channel></rss>"
)


@pytest.mark.asyncio
async def test_s1_latest_uses_tid_as_id(monkeypatch):
    async def fake_get(url, headers=None, no_cache=None, **kwargs):
        return RequestResult(False, "t", RSS_SAMPLE)

    monkeypatch.setattr(game_digital_forums, "get", fake_get)
    result = await game_digital_forums.handle_route(_request("s1-latest"), no_cache=True)

    assert result.data[0].id == "2290788"  # 从链接提取 tid 作 id


@pytest.mark.asyncio
async def test_s1_latest_empty_rss_is_an_error(monkeypatch):
    async def fake_get(url, headers=None, no_cache=None, **kwargs):
        return RequestResult(False, "t", "<html>不是 RSS</html>")

    monkeypatch.setattr(game_digital_forums, "get", fake_get)
    with pytest.raises(RuntimeError, match="did not return RSS"):
        await game_digital_forums.handle_route(_request("s1-latest"), no_cache=True)


_FLYERT_PAGE = """<html><body><tbody id="normalthread_4868908"><tr>
<td><span class="comiis_common"><em><a>飞客讨论</a></em><a href="forum.php?mod=viewthread&amp;tid=4868908">飞客热帖标题</a></span></td>
<div class="cl"><span class="y"><a>最后回复人</a></span><span class="y"><em>350</em><em>20</em></span><span class="y"><a>发帖人</a><span title="2026-9-30">昨天 22:55</span></span></div>
</tr></tbody></body></html>"""


@pytest.mark.asyncio
async def test_flyert_guide_maps_fields(monkeypatch):
    async def fake_get(url, no_cache=None, **kwargs):
        return RequestResult(False, "t", _FLYERT_PAGE)

    monkeypatch.setattr(game_digital_forums, "get", fake_get)
    result = await game_digital_forums.handle_route(_request("flyert-hot"), no_cache=True)

    item = result.data[0]
    assert item.id == "4868908"
    assert item.title == "飞客热帖标题"
    assert item.hot == 350  # 查看/回复数中的第一个
    assert item.desc == "飞客讨论"
    assert item.timestamp is not None  # 悬停 title 当天 0 点(北京时间)


@pytest.mark.asyncio
async def test_unknown_board_is_rejected():
    with pytest.raises(ValueError, match="Unknown board"):
        await game_digital_forums.handle_route(_request("nga-xxx"), no_cache=True)
