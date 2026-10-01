from __future__ import annotations

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import cls_depth
from whats_hot_api.utils.http_client import RequestResult

UPDATE_TIME = "2026-09-28T00:03:00+00:00"


def _request(board_type: str | None = None) -> Request:
    query = f"type={board_type}" if board_type else ""
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/cls-depth",
        "query_string": query.encode(),
        "headers": [],
    })


def _article(item_id: int, ctime: int, **overrides: object) -> dict:
    row = {
        "id": item_id,
        "title": f"文章{item_id}",
        "brief": f"摘要{item_id}",
        "ctime": ctime,
        "ctype": 0,
        "author": "",
        "img": "",
        "external_link": "",
        "reading_num": 0,
        "image": "",
        "source": "",
    }
    row.update(overrides)
    return row


def _payload(top: list[dict], depth: list[dict]) -> dict:
    return {"errno": 0, "msg": None, "data": {"top_article": top, "depth_list": depth}}


def _mock_get(payload: object, captured: dict | None = None):
    async def fake_get(url, no_cache=None, response_type=None, **kwargs):
        if captured is not None:
            captured.update({"url": url, "kwargs": kwargs, "no_cache": no_cache})
        return RequestResult(False, UPDATE_TIME, payload)

    return fake_get


@pytest.mark.asyncio
async def test_default_headline_board_url_and_signature(monkeypatch):
    # 签名只覆盖 app/os/sv 三个参数;该 sign 与 board_api 证据里 13 个频道请求共用
    captured: dict = {}
    monkeypatch.setattr(
        cls_depth, "get", _mock_get(_payload([_article(1, 1790550000)], []), captured)
    )
    result = await cls_depth.handle_route(_request(), no_cache=True)

    assert captured["url"] == (
        "https://www.cls.cn/v3/depth/home/assembled/1000"
        "?app=CailianpressWeb&os=web&sv=8.7.9&sign=b02d8f7bc4c45eeb3e86904203597da2"
    )
    # 实测接口不需要任何请求头(httpx 缺省 UA 同样返回数据),路由不带 UA/Referer
    assert "headers" not in captured["kwargs"]
    assert captured["no_cache"] is True
    assert result.name == "cls-depth"
    assert result.type == "头条"
    assert result.total == 1
    assert result.fromCache is False
    assert result.updateTime == UPDATE_TIME


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("board", "channel"),
    sorted(cls_depth._CHANNELS.items(), key=lambda pair: pair[1][0]),
)
async def test_every_board_targets_its_channel_id(monkeypatch, board, channel):
    channel_id, label = channel
    captured: dict = {}
    monkeypatch.setattr(
        cls_depth, "get", _mock_get(_payload([], [_article(7, 1790500000)]), captured)
    )
    result = await cls_depth.handle_route(_request(board), no_cache=True)

    # 签名不含频道 id,13 个频道共用同一个 sign(证据 curl 亦如此)
    assert captured["url"].startswith(
        f"https://www.cls.cn/v3/depth/home/assembled/{channel_id}?"
    )
    assert captured["url"].endswith("&sign=b02d8f7bc4c45eeb3e86904203597da2")
    assert result.type == label


@pytest.mark.asyncio
async def test_pinned_block_first_and_page_order_preserved(monkeypatch):
    # 置顶区块接口顺序不是 ctime 倒序(2、3 条互换);头条频道 depth_list 是编辑顺序,
    # 相邻条目时间交错——路由必须原样输出,不得按时间重排
    top = [
        _article(2406655, 1782198770, title="投教置顶一"),
        _article(2348427, 1776568310, title="投教置顶二"),
        _article(2352116, 1776846677, title="投教置顶三"),
        _article(2180256, 1761311572, title="投教置顶四"),
    ]
    depth = [
        _article(2493485, 1790503939, title="列表一"),
        _article(2493489, 1790505575, title="列表二"),
        _article(2493451, 1790498276, title="列表三"),
        _article(2493440, 1790496770, title="列表四"),
    ]
    monkeypatch.setattr(cls_depth, "get", _mock_get(_payload(top, depth)))
    result = await cls_depth.handle_route(_request("headline"), no_cache=True)

    assert [item.id for item in result.data] == [
        "2406655", "2348427", "2352116", "2180256",
        "2493485", "2493489", "2493451", "2493440",
    ]
    # 输出时间不单调递减,证明没有做 ctime 排序
    stamps = [item.timestamp for item in result.data if item.timestamp]
    assert stamps != sorted(stamps, reverse=True)
    assert result.total == 8


@pytest.mark.asyncio
async def test_field_mapping_pinned_and_list_items(monkeypatch):
    top = [
        {
            "id": 2493599,
            "title": " <b>置顶</b>标题&nbsp;一 ",
            "brief": "摘要<br/>第一行&nbsp;第二行",
            "ctime": 1790550000,
            "ctype": 0,
            "author": "财联社 张鑫",
            "img": "https://image.cls.cn/images/20260928/top.jpg",
            "external_link": "",
            "reading_num": 8888,
        },
    ]
    depth = [
        {
            "id": 2493485,
            "title": "列表标题",
            "brief": "①第一点\n②第二点",
            "ctime": 1790503939,
            "source": "财联社",
            "image": "https://image.cls.cn/img/vcg/cover.jpeg",
            "external_link": "",
            "reading_num": 261660,
        },
    ]
    monkeypatch.setattr(cls_depth, "get", _mock_get(_payload(top, depth)))
    result = await cls_depth.handle_route(_request("a-share"), no_cache=True)

    pinned, listed = result.data
    # 置顶区块:cover←img、author←author;列表:cover←image、author←source
    assert pinned.id == "2493599"
    assert pinned.title == "置顶标题 一"
    assert pinned.url == "https://www.cls.cn/detail/2493599"
    assert pinned.hot == 8888
    assert pinned.cover == "https://image.cls.cn/images/20260928/top.jpg"
    assert pinned.author == "财联社 张鑫"
    assert pinned.desc == "摘要第一行 第二行"
    assert pinned.timestamp == 1790550000000  # 秒 → 毫秒
    assert listed.id == "2493485"
    assert listed.url == "https://www.cls.cn/detail/2493485"
    assert listed.hot == 261660
    assert listed.cover == "https://image.cls.cn/img/vcg/cover.jpeg"
    assert listed.author == "财联社"
    assert listed.desc == "①第一点 ②第二点"  # 换行合并为单个空格
    assert listed.timestamp == 1790503939000


@pytest.mark.asyncio
async def test_ctype_prefix_and_external_link_rules(monkeypatch):
    top = [
        _article(100, 1790000001, ctype=1, title="专题置顶"),
        _article(200, 1790000002, ctype=2, title="话题置顶"),
        _article(300, 1790000003, ctype=0, title="普通置顶",
                 external_link="https://example.com/external"),
    ]
    depth = [
        # 列表条目不走 ctype 链接规则;ctype=1 也仍是文章详情页
        _article(400, 1790000004, ctype=1, title="列表专题"),
        _article(500, 1790000005, title="列表外链",
                 external_link="https://example.com/list-external"),
    ]
    monkeypatch.setattr(cls_depth, "get", _mock_get(_payload(top, depth)))
    result = await cls_depth.handle_route(_request("company"), no_cache=True)

    assert [(item.id, item.url) for item in result.data] == [
        ("subject-100", "https://www.cls.cn/subject/100"),
        ("topic-200", "https://www.cls.cn/topic/200"),
        ("300", "https://example.com/external"),
        ("400", "https://www.cls.cn/detail/400"),
        ("500", "https://example.com/list-external"),
    ]


@pytest.mark.asyncio
async def test_dedupe_by_url_keeps_pinned_occurrence(monkeypatch):
    top = [_article(2493334, 1790462419, title="置顶兼列表")]
    depth = [
        _article(2493334, 1790462419, title="置顶兼列表"),
        _article(2493625, 1790510000, title="仅列表"),
    ]
    monkeypatch.setattr(cls_depth, "get", _mock_get(_payload(top, depth)))
    result = await cls_depth.handle_route(_request("global"), no_cache=True)

    # 同一文章同时出现在置顶与列表时只留置顶位置的那条
    assert [item.id for item in result.data] == ["2493334", "2493625"]
    assert result.total == 2


@pytest.mark.asyncio
async def test_error_shell_and_empty_parse_are_rejected(monkeypatch):
    monkeypatch.setattr(
        cls_depth,
        "get",
        _mock_get({"errno": 10012, "msg": "签名错误", "data": None}),
    )
    with pytest.raises(RuntimeError, match="10012"):
        await cls_depth.handle_route(_request("headline"), no_cache=True)

    # errno=0 但两块都是空 → 空解析,同样报错,不静默降级为空榜
    monkeypatch.setattr(
        cls_depth, "get", _mock_get({"errno": 0, "msg": None, "data": {}})
    )
    with pytest.raises(RuntimeError, match="no items"):
        await cls_depth.handle_route(_request("headline"), no_cache=True)


@pytest.mark.asyncio
async def test_unknown_board_is_rejected(monkeypatch):
    with pytest.raises(ValueError, match="Unknown board 'bogus'"):
        await cls_depth.handle_route(_request("bogus"), no_cache=True)


def test_meta_declares_all_boards_with_headline_default():
    # 声明序第一个是默认榜(registry defaultPathType 取第一个 type 值)
    values = list(cls_depth.ROUTE_META["params"]["type"]["type"])
    assert values[0] == "headline"
    assert len(values) == 13
    assert set(values) == set(cls_depth._CHANNELS)
