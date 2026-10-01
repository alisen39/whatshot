from __future__ import annotations

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import gov_cn_news
from whats_hot_api.utils.http_client import RequestResult


def _request(board_type: str) -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/gov-cn-news",
        "query_string": f"type={board_type}".encode(),
        "headers": [],
    })


def _row(title: str, url: str, date: str, sub_title: str = "") -> dict:
    return {"TITLE": title, "SUB_TITLE": sub_title, "URL": url, "DOCRELPUBTIME": date}


# 结构取自 board_api/gov_cn_news 证据 captured_data(标题净化):字段 TITLE/SUB_TITLE/URL/DOCRELPUBTIME,
# 视频条目链到 tv.cctv.com,发布时间只有日期
_ROWS = [
    _row(
        "要闻标题一:凝聚共同发展的强大合力",
        "https://www.gov.cn/yaowen/liebiao/202609/content_7082183.htm",
        "2026-09-27",
    ),
    _row(
        "要闻标题二:在中美关系发展史上写下浓墨重彩的一笔",
        "https://www.gov.cn/yaowen/liebiao/202609/content_7082182.htm",
        "2026-09-27",
    ),
    _row(
        "【视频】时政微观察",
        "https://tv.cctv.com/2026/09/26/VIDE1234567890.shtml",
        "2026-09-26",
    ),
]


@pytest.mark.asyncio
async def test_default_board_maps_fields(monkeypatch):
    captured = {}

    async def fake_get(url, no_cache=None, **kwargs):
        captured.update({"url": url, "no_cache": no_cache})
        return RequestResult(False, "2026-10-01T00:00:00+00:00", list(_ROWS))

    monkeypatch.setattr(gov_cn_news, "get", fake_get)
    result = await gov_cn_news.handle_route(_request("hot"), no_cache=True)

    # 数据源是列表页自己加载的 YAOWENLIEBIAO.json,不是列表页 HTML
    assert captured["url"] == "https://www.gov.cn/yaowen/liebiao/YAOWENLIEBIAO.json"
    assert captured["no_cache"] is True
    assert result.name == "gov-cn-news"
    assert result.title == "中国政府网"
    assert result.type == "要闻最新"
    first = result.data[0]
    # id/url/mobileUrl 三者同为文章 URL(URL 全文唯一)
    assert first.id == "https://www.gov.cn/yaowen/liebiao/202609/content_7082183.htm"
    assert first.url == first.id
    assert first.mobileUrl == first.id
    assert first.title == "要闻标题一:凝聚共同发展的强大合力"
    # DOCRELPUBTIME 只有日期 → 当天 00:00 北京时间的毫秒
    assert first.timestamp == 1790438400000
    # 【视频】条目(tv.cctv.com)照常输出,且不同日期归到各自当天
    assert result.data[2].url.startswith("https://tv.cctv.com/")
    assert result.data[2].timestamp == 1790352000000


@pytest.mark.asyncio
async def test_caps_first_page_and_skips_broken_rows(monkeypatch):
    rows = [_row(f"要闻标题{i}", f"https://www.gov.cn/yaowen/liebiao/202609/content_{i}.htm", "2026-09-27")
            for i in range(25)]
    # 列表页每页 20 条(sPageSize=20);坏行(缺标题/非 URL)不计入
    rows.append(_row("", "https://www.gov.cn/yaowen/liebiao/202609/content_x.htm", "2026-09-27"))
    rows.append(_row("没有链接", "javascript:void(0)", "2026-09-27"))
    rows.append({"TITLE": "不是字典的字段也算", "URL": "https://www.gov.cn/x.htm"})

    async def fake_get(url, no_cache=None, **kwargs):
        return RequestResult(False, "t", rows)

    monkeypatch.setattr(gov_cn_news, "get", fake_get)
    result = await gov_cn_news.handle_route(_request("hot"))
    assert result.total == 20
    assert len(result.data) == 20
    assert all(item.url.startswith("https://www.gov.cn/") for item in result.data)


@pytest.mark.asyncio
async def test_whitespace_and_sub_title_are_normalized(monkeypatch):
    rows = [_row("  多  空格\n标题 ", "https://www.gov.cn/yaowen/liebiao/202609/content_1.htm",
                 "2026-09-27", sub_title="副标题内容")]

    async def fake_get(url, no_cache=None, **kwargs):
        return RequestResult(False, "t", rows)

    monkeypatch.setattr(gov_cn_news, "get", fake_get)
    result = await gov_cn_news.handle_route(_request("hot"))
    assert result.data[0].title == "多 空格 标题"
    assert result.data[0].desc == "副标题内容"


@pytest.mark.asyncio
async def test_bad_or_missing_date_yields_null_timestamp(monkeypatch):
    rows = [
        _row("无日期", "https://www.gov.cn/yaowen/liebiao/202609/content_1.htm", ""),
        _row("坏日期", "https://www.gov.cn/yaowen/liebiao/202609/content_2.htm", "not-a-date"),
        {"TITLE": "缺字段", "URL": "https://www.gov.cn/yaowen/liebiao/202609/content_3.htm"},
    ]

    async def fake_get(url, no_cache=None, **kwargs):
        return RequestResult(False, "t", rows)

    monkeypatch.setattr(gov_cn_news, "get", fake_get)
    result = await gov_cn_news.handle_route(_request("hot"))
    assert all(item.timestamp is None for item in result.data)


@pytest.mark.asyncio
async def test_empty_or_shape_changed_feed_is_an_error(monkeypatch):
    async def fake_get(url, no_cache=None, **kwargs):
        return RequestResult(False, "t", [])

    monkeypatch.setattr(gov_cn_news, "get", fake_get)
    with pytest.raises(RuntimeError, match="no rows"):
        await gov_cn_news.handle_route(_request("hot"))

    async def fake_get_dict(url, no_cache=None, **kwargs):
        # 文件地址改动后常见返回:HTML 错误页/对象壳,不是行数组
        return RequestResult(False, "t", {"error": "moved"})

    monkeypatch.setattr(gov_cn_news, "get", fake_get_dict)
    with pytest.raises(RuntimeError, match="no rows"):
        await gov_cn_news.handle_route(_request("hot"))

    async def fake_get_unparsable(url, no_cache=None, **kwargs):
        return RequestResult(False, "t", [{"TITLE": "", "URL": "https://www.gov.cn/a.htm"}])

    monkeypatch.setattr(gov_cn_news, "get", fake_get_unparsable)
    with pytest.raises(RuntimeError, match="no parsable items"):
        await gov_cn_news.handle_route(_request("hot"))


@pytest.mark.asyncio
async def test_unknown_type_is_rejected(monkeypatch):
    async def fake_get(url, no_cache=None, **kwargs):
        raise AssertionError("should not fetch for unknown type")

    monkeypatch.setattr(gov_cn_news, "get", fake_get)
    with pytest.raises(ValueError, match="Unknown board"):
        await gov_cn_news.handle_route(_request("nope"))
