from __future__ import annotations

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import szse_rules
from whats_hot_api.utils.http_client import RequestResult


def _request(board_type: str) -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/szse-rules",
        "query_string": f"type={board_type}".encode(),
        "headers": [],
    })


# 结构取自 board_api/szse_rules 证据 captured_data(标题净化):字段 id/doctitle/doccontent/
# docpuburl/docpubtime,docpuburl 是 http://,docpubtime 已是毫秒
_DOC = {
    "id": "622687",
    "doctitle": "关于发布《深圳证券交易所公司债券发行上市审核业务指引第3号——优化审核安排(2026年修订)》的通知",
    "doccontent": " 深证上〔2026〕1227号 各市场参与人: 为进一步提升交易所债券市场服务实体经济质效,加大对优质企业融资支持力度……",
    "docpuburl": "http://www.szse.cn/lawrules/rule/bond/bonds/list/t20260904_622687.html",
    "docpubtime": 1788485054000,
}


@pytest.mark.asyncio
async def test_posts_page_first_form_and_maps_fields(monkeypatch):
    captured = {}

    async def fake_post(url, headers=None, body=None, no_cache=None, **kwargs):
        captured.update({"url": url, "headers": headers, "body": body, "no_cache": no_cache})
        return RequestResult(False, "2026-10-01T00:00:00+00:00",
                             {"totalSize": 256, "pageSize": 20, "currentPage": 1, "data": [dict(_DOC)]})

    monkeypatch.setattr(szse_rules, "post", fake_post)
    result = await szse_rules.handle_route(_request("hot"), no_cache=True)

    assert captured["url"] == "https://www.szse.cn/api/search/content"
    # 接口是 x-www-form-urlencoded 表单;JSON 体或 text/plain 返回 400(推翻性验证)
    assert captured["headers"]["Content-Type"] == "application/x-www-form-urlencoded"
    # 与页面 articleList.js 的表单一致:keyword 必须存在(可为空串),channelCode[] 决定栏目
    assert captured["body"] == (
        "keyword=&time=0&range=title&channelCode%5B%5D=szserulesAllRulesBuss"
        "&currentPage=1&pageSize=20&scope=0"
    )
    assert captured["no_cache"] is True
    assert result.name == "szse-rules"
    assert result.title == "深圳证券交易所"
    assert result.type == "全部业务规则"
    item = result.data[0]
    assert item.id == "622687"  # 文档号,与详情页文件名 t20260904_622687.html 一致
    assert item.title == _DOC["doctitle"]
    assert item.url == _DOC["docpuburl"]  # http:// 原样输出
    assert item.mobileUrl == _DOC["docpuburl"]
    assert item.desc == _DOC["doccontent"].strip()
    assert item.timestamp == 1788485054000  # docpubtime 已是毫秒,原样保留


@pytest.mark.asyncio
async def test_strips_html_tags_from_title_and_desc(monkeypatch):
    doc = {
        "id": "630001",
        "doctitle": "关于发布<em>交易</em>规则的通知",
        "doccontent": " <em>深证上</em>〔2026〕1号 各市场参与人:",
        "docpuburl": "http://www.szse.cn/lawrules/rule/t20261001_630001.html",
        "docpubtime": 1790918400000,
    }

    async def fake_post(url, headers=None, body=None, no_cache=None, **kwargs):
        return RequestResult(False, "t", {"totalSize": 1, "data": [doc]})

    monkeypatch.setattr(szse_rules, "post", fake_post)
    result = await szse_rules.handle_route(_request("hot"))
    # 页面 replaceTitle 同款:搜索高亮 <em> 一律剥掉
    assert result.data[0].title == "关于发布交易规则的通知"
    assert result.data[0].desc == "深证上〔2026〕1号 各市场参与人:"


@pytest.mark.asyncio
async def test_skips_rows_missing_required_fields(monkeypatch):
    docs = [
        {"id": "1", "doctitle": "缺链接", "docpubtime": 1788485054000},
        {"id": "", "doctitle": "缺文档号", "docpuburl": "http://www.szse.cn/a.html"},
        {"id": "3", "doctitle": "", "docpuburl": "http://www.szse.cn/b.html"},
        dict(_DOC),
    ]

    async def fake_post(url, headers=None, body=None, no_cache=None, **kwargs):
        return RequestResult(False, "t", {"totalSize": 4, "data": docs})

    monkeypatch.setattr(szse_rules, "post", fake_post)
    result = await szse_rules.handle_route(_request("hot"))
    assert [item.id for item in result.data] == ["622687"]


@pytest.mark.asyncio
async def test_business_error_shell_is_an_error(monkeypatch):
    async def fake_post(url, headers=None, body=None, no_cache=None, **kwargs):
        # keyword 缺失等场景服务端返回 400 + {"code":"400","msg":"null"}
        return RequestResult(False, "t", {"code": "400", "msg": "null"})

    monkeypatch.setattr(szse_rules, "post", fake_post)
    with pytest.raises(RuntimeError, match=r"code=400"):
        await szse_rules.handle_route(_request("hot"))


@pytest.mark.asyncio
async def test_empty_data_or_shape_change_is_an_error(monkeypatch):
    async def fake_post_empty(url, headers=None, body=None, no_cache=None, **kwargs):
        return RequestResult(False, "t", {"totalSize": 0, "pageSize": 20, "currentPage": 1, "data": []})

    monkeypatch.setattr(szse_rules, "post", fake_post_empty)
    with pytest.raises(RuntimeError, match="no parsable items"):
        await szse_rules.handle_route(_request("hot"))

    async def fake_post_html(url, headers=None, body=None, no_cache=None, **kwargs):
        # 接口路径失效后常见返回:HTML 错误页按 200 下发
        return RequestResult(False, "t", "<html><body>moved</body></html>")

    monkeypatch.setattr(szse_rules, "post", fake_post_html)
    with pytest.raises(RuntimeError, match="no data list"):
        await szse_rules.handle_route(_request("hot"))


@pytest.mark.asyncio
async def test_unknown_type_is_rejected(monkeypatch):
    async def fake_post(url, headers=None, body=None, no_cache=None, **kwargs):
        raise AssertionError("should not fetch for unknown type")

    monkeypatch.setattr(szse_rules, "post", fake_post)
    with pytest.raises(ValueError, match="Unknown board"):
        await szse_rules.handle_route(_request("latest"))
