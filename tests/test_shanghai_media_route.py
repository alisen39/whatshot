"""shanghai_media 路由测试:fixtures 按证据目录 tmp/board_api/shanghai_media 净化(结构与字段一致,内容摘录)。"""

from __future__ import annotations

from typing import Any

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import shanghai_media
from whats_hot_api.utils.http_client import RequestResult

# 静态 JSON 的行结构照 evidence/02_newsrank_json、03_morenewslist_json、03_recommandnewslist_json
_RANK_ROW_1 = {
    "summary": "在痛失男团金牌之后的三天内，国乒男队已让日本队拿下男单、男双金牌之梦接连破碎。",
    "subsectionname": "文汇体育",
    "replay": 0,
    "title": "亚运会｜接连击碎日本队夺金梦，不被看好的林诗栋/黄友政拿下国乒最难一金",
    "picurl": "2026/09/27/1200x900_xxjpsec001001_20260927_pepfn1a001.jpg",
    "publishtime": 1790538962000,
    "relatecontentid": "0",
    "id": 1185499,
    "subsectionid": 326,
    "sectionname": "体育",
    "newstype": "0",
}
_RANK_ROW_2 = {
    "summary": "",
    "subsectionname": "纵览",
    "replay": 0,
    "title": "中国移动、中国电信、中国联通，集中叫停！",
    "picurl": "",
    "publishtime": 1790469812000,
    "relatecontentid": "0",
    "id": 1185002,
    "sectionname": "天下",
    "newstype": "0",
}

_RECOMMEND_ROWS = [
    # newstype=0:普通新闻,链接用 id
    {
        "summary": "他仍将是塞尔维亚重大决策背后的“关键人物”。",
        "subsectionname": "世界观",
        "title": "深度 | 辞总统、选总理，武契奇重大“转身”？",
        "picurl": "2026/09/27/l_cb20260927174822427002.jpg",
        "publishtime": 1790511471000,
        "id": 1185217,
        "newstype": "0",
        "relatecontentid": "0",
    },
    # newstype=1(专题):链接用 relatecontentid,详情页 specialDetail.html
    {
        "summary": "上海旅游节半价真香！",
        "subsectionname": "上观智库",
        "title": "花150元在魔都当一天“旅游特种兵”",
        "picurl": "",
        "publishtime": 1790492353000,
        "id": 1185071,
        "newstype": "1",
        "relatecontentid": "54050",
    },
    # newstype=9(未知类型):页面 openDetailByNewsType 没有分支,跳过
    {
        "summary": "",
        "subsectionname": "纵览",
        "title": "未知类型条目",
        "picurl": "",
        "publishtime": 1790492353000,
        "id": 1185999,
        "newstype": "9",
        "relatecontentid": "0",
    },
]

_MORENEWS_ROWS = [
    {
        "summary": "在AI仿真人剧中，观众对“橡胶拳头”的特写镜头习以为常。",
        "subsectionname": "纵深",
        "title": "AI仿真人剧集井喷：演技如何“数字生成”",
        "picurl": "2026/09/27/l_cb20260927214521172058.jpg",
        "publishtime": 1790550560000,
        "id": 1185390,
        "newstype": "0",
    },
    # 与编辑推荐重叠(1185217),应被去掉
    {
        "summary": "他仍将是塞尔维亚重大决策背后的“关键人物”。",
        "subsectionname": "世界观",
        "title": "深度 | 辞总统、选总理，武契奇重大“转身”？",
        "picurl": "",
        "publishtime": 1790511471000,
        "id": 1185217,
        "newstype": "0",
    },
    # 缺标题的行按页面行为跳过
    {
        "summary": "",
        "subsectionname": "纵览",
        "title": "",
        "picurl": "",
        "publishtime": 1790550000000,
        "id": 1185400,
        "newstype": "0",
    },
]


def _request(board_type: str) -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/shanghai-media",
        "query_string": f"type={board_type}".encode(),
        "headers": [],
    })


def _ok(data: Any) -> RequestResult:
    return RequestResult(False, "2026-09-28T00:20:00+00:00", data)


async def test_rank_maps_fields_and_request(monkeypatch):
    captured: dict[str, Any] = {}

    async def fake_get(**kwargs):
        captured.update(kwargs)
        return _ok({"data": {"24": [dict(_RANK_ROW_1), dict(_RANK_ROW_2)], "48": []}})

    monkeypatch.setattr(shanghai_media, "get", fake_get)
    result = await shanghai_media.handle_route(_request("jfdaily-rank-24h"), no_cache=True)

    assert captured["url"] == "https://www.jfdaily.com/staticsg/data/web/common/newsrank.json"
    assert result.name == "shanghai-media"
    assert result.type == "解放日报·今日文章排行（24小时）"
    assert result.total == 2
    first = result.data[0]
    assert first.id == "1185499"  # 稿件号,不是名次
    assert first.title.startswith("亚运会｜接连击碎日本队夺金梦")
    assert first.url == "https://www.jfdaily.com/staticsg/res/html/web/newsDetail.html?id=1185499"
    assert first.cover == "https://images.shobserver.cn/news/690_390/2026/09/27/1200x900_xxjpsec001001_20260927_pepfn1a001.jpg"
    assert first.author == "文汇体育"
    assert first.desc.startswith("在痛失男团金牌之后")
    assert first.timestamp == 1790538962000  # 上游毫秒原样保留
    assert first.hot is None  # 静态数据评论数不可用,不映射
    second = result.data[1]
    assert second.cover is None  # 空 picurl 转 None
    assert second.author == "纵览"


async def test_latest_dedupes_recommend_and_maps_url(monkeypatch):
    calls: list[str] = []

    async def fake_get(**kwargs):
        calls.append(kwargs["url"])
        if kwargs["url"].endswith("recommandnewslist.json"):
            return _ok({"data": [dict(_RECOMMEND_ROWS[0])]})
        return _ok({"data": [dict(row) for row in _MORENEWS_ROWS]})

    monkeypatch.setattr(shanghai_media, "get", fake_get)
    result = await shanghai_media.handle_route(_request("shobserver-latest"), no_cache=True)

    # 证据口径:"最新"要先取编辑推荐去重,共 2 个请求
    assert [url.rsplit("/", 1)[-1] for url in calls] == ["recommandnewslist.json", "morenewslist.json"]
    assert result.type == "上观新闻·最新"
    assert result.total == 1  # 重叠的 1185217 与缺标题行都去掉
    first = result.data[0]
    assert first.id == "1185390"
    assert first.url == "https://www.shobserver.com/staticsg/res/html/web/newsDetail.html?id=1185390&sid=11"
    assert first.timestamp == 1790550560000


async def test_recommend_builds_url_by_newstype(monkeypatch):
    async def fake_get(**kwargs):
        return _ok({"data": [dict(row) for row in _RECOMMEND_ROWS]})

    monkeypatch.setattr(shanghai_media, "get", fake_get)
    result = await shanghai_media.handle_route(_request("shobserver-recommend"), no_cache=True)

    assert result.type == "上观新闻·编辑推荐"
    assert result.total == 2  # newstype=9 的行没有详情页分支,跳过
    first = result.data[0]
    assert first.url == "https://www.shobserver.com/staticsg/res/html/web/newsDetail.html?id=1185217&sid=11"
    special = result.data[1]
    # newstype=1 专题走 specialDetail.html 且用 relatecontentid
    assert special.url == "https://www.shobserver.com/staticsg/res/html/web/specialDetail.html?id=54050&sid=11"
    assert special.id == "1185071"


async def test_error_shell_is_rejected(monkeypatch):
    async def fake_get(**kwargs):
        return _ok({"errno": 404, "message": "not found"})

    monkeypatch.setattr(shanghai_media, "get", fake_get)
    with pytest.raises(RuntimeError, match="no data list"):
        await shanghai_media.handle_route(_request("shobserver-recommend"), no_cache=True)


async def test_rank_missing_hour_list_is_rejected(monkeypatch):
    async def fake_get(**kwargs):
        return _ok({"data": {"48": []}})

    monkeypatch.setattr(shanghai_media, "get", fake_get)
    with pytest.raises(RuntimeError, match="24-hour list"):
        await shanghai_media.handle_route(_request("jfdaily-rank-24h"), no_cache=True)


async def test_empty_parse_is_an_error_not_empty_board(monkeypatch):
    async def fake_get(**kwargs):
        return _ok({"data": []})

    monkeypatch.setattr(shanghai_media, "get", fake_get)
    with pytest.raises(RuntimeError, match="parsed no items"):
        await shanghai_media.handle_route(_request("shobserver-recommend"), no_cache=True)


async def test_unknown_board_is_rejected():
    with pytest.raises(ValueError, match="Unknown board"):
        await shanghai_media.handle_route(_request("nonsense"), no_cache=True)


async def test_default_board_is_first_declared(monkeypatch):
    async def fake_get(**kwargs):
        if kwargs["url"].endswith("recommandnewslist.json"):
            return _ok({"data": [dict(_RECOMMEND_ROWS[0])]})
        return _ok({"data": [dict(row) for row in _MORENEWS_ROWS]})

    monkeypatch.setattr(shanghai_media, "get", fake_get)
    request = Request({
        "type": "http",
        "method": "GET",
        "path": "/shanghai-media",
        "query_string": b"",
        "headers": [],
    })
    result = await shanghai_media.handle_route(request, no_cache=False)
    # 声明序第一个 shobserver-latest 是默认榜
    assert result.type == "上观新闻·最新"
    assert next(iter(shanghai_media.type_map)) == "shobserver-latest"
