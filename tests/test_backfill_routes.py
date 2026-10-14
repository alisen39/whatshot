"""Fixture tests for route ``backfill_page`` implementations.

Each route: the first page carries no cursor, the next request carries the
upstream cursor derived from the previous page (boundary-inclusive for time
cursors), and an exhausted upstream yields ``next_cursor=None``.
"""

from __future__ import annotations

import json
from urllib.parse import parse_qs, urlsplit

import pytest

from whats_hot_api.backfill import decode_cursor
from whats_hot_api.routes.hotlist import nbd_eeo, stcn_channels
from whats_hot_api.routes.newsflash import (
    caixin_data,
    cls,
    eastmoney,
    fastbull,
    futunn,
    gelonghui,
    hexun,
    jin10,
    jingji21,
    jrj,
    kr36_quick,
    mktnews,
    sina_finance,
    ths_10jqka,
    wallstreetcn,
    yicai,
)
from whats_hot_api.utils.http_client import RequestResult


class Recorder:
    """Fake ``get``/``post`` returning queued payloads and recording calls."""

    def __init__(self, *payloads):
        self.payloads = list(payloads)
        self.calls: list[dict] = []

    async def __call__(self, **kwargs):
        self.calls.append(kwargs)
        payload = self.payloads.pop(0)
        return RequestResult(False, "2026-10-14T00:00:00+00:00", payload)


def _query(call) -> dict:
    query = {k: v[0] for k, v in parse_qs(urlsplit(call["url"]).query).items()}
    query.update({k: str(v) for k, v in (call.get("params") or {}).items()})
    return query


async def test_sina_finance_pages_by_min_id(monkeypatch):
    feed = lambda ids, min_id: {"result": {"data": {"feed": {  # noqa: E731
        "min_id": min_id,
        "list": [{"id": i, "rich_text": f"内容{i}", "create_time": "2026-10-14 10:00:00"} for i in ids]}}}}
    rec = Recorder(feed([10, 9], 9), feed([], 0))
    monkeypatch.setattr(sina_finance, "get", rec)
    first = await sina_finance.backfill_page("company", {}, None)
    assert [i.id for i in first.data.data] == ["10", "9"] and first.data.kind == "newsflash"
    assert "id" not in rec.calls[0]["params"] and rec.calls[0]["params"]["tag"] == "3"
    last = await sina_finance.backfill_page("company", {}, first.next_cursor)
    assert rec.calls[1]["params"]["id"] == "9" and rec.calls[1]["params"]["type"] == "1"
    assert last.next_cursor is None


async def test_eastmoney_echoes_sort_end(monkeypatch):
    page = lambda codes, sort_end: {"data": {"sortEnd": sort_end, "fastNewsList": [  # noqa: E731
        {"code": c, "title": f"t{c}", "showTime": "2026-10-14 10:00:00"} for c in codes]}}
    rec = Recorder(page(["a"], "S1"), page([], "S2"))
    monkeypatch.setattr(eastmoney, "get", rec)
    first = await eastmoney.backfill_page("all", {}, None)
    assert rec.calls[0]["params"]["sortEnd"] == "" and decode_cursor(first.next_cursor) == {"sortEnd": "S1"}
    last = await eastmoney.backfill_page("all", {}, first.next_cursor)
    assert rec.calls[1]["params"]["sortEnd"] == "S1" and last.next_cursor is None


async def test_jrj_make_date_cursor_keeps_boundary_second(monkeypatch):
    rows = [{"iiId": 2, "title": "a", "makeDate": "2026-10-14 10:00:05"},
            {"iiId": 1, "title": "b", "makeDate": "2026-10-14 10:00:00"}]
    rec = Recorder({"data": {"data": rows}}, {"data": {"data": []}})
    monkeypatch.setattr(jrj, "post", rec)
    first = await jrj.backfill_page("hot", {}, None)
    assert rec.calls[0]["body"] == {}
    # makeDate is exclusive upstream: +1s re-reads items sharing the oldest second.
    assert decode_cursor(first.next_cursor) == {"makeDate": "2026-10-14 10:00:01"}
    last = await jrj.backfill_page("hot", {}, first.next_cursor)
    assert rec.calls[1]["body"] == {"makeDate": "2026-10-14 10:00:01"} and last.next_cursor is None


async def test_jrj_starts_before_until_when_requested(monkeypatch):
    from datetime import UTC, datetime

    rec = Recorder({"data": {"data": []}})
    monkeypatch.setattr(jrj, "post", rec)
    await jrj.backfill_page("hot", {}, None, before=datetime(2026, 10, 13, 16, tzinfo=UTC))
    assert rec.calls[0]["body"] == {"makeDate": "2026-10-14 00:00:00"}


async def test_cls_last_time_is_resigned_and_inclusive(monkeypatch):
    rows = [{"id": 5, "type": -1, "content": "x", "ctime": 1791900100},
            {"id": 4, "type": 2, "content": "paid", "ctime": 1791900000}]
    rec = Recorder({"errno": 0, "data": {"roll_data": rows}}, {"errno": 0, "data": {"roll_data": []}})
    monkeypatch.setattr(cls, "get", rec)
    first = await cls.backfill_page("red", {}, None)
    # The paid row is dropped from items but still bounds the cursor.
    assert [i.id for i in first.data.data] == ["5"]
    assert decode_cursor(first.next_cursor) == {"lastTime": 1791900001}
    last = await cls.backfill_page("red", {}, first.next_cursor)
    query = _query(rec.calls[1])
    assert query["last_time"] == "1791900001" and query["category"] == "red"
    assert rec.calls[1]["url"] == cls._signed_url("red", 1791900001)
    assert last.next_cursor is None


async def test_jin10_max_time_is_inclusive(monkeypatch):
    rows = [{"id": "b", "time": "2026-10-14 10:00:05", "data": {"content": "b"}},
            {"id": "a", "time": "2026-10-14 10:00:00", "data": {"content": "a"}}]
    rec = Recorder({"data": rows}, {"data": []})
    monkeypatch.setattr(jin10, "get", rec)
    first = await jin10.backfill_page("hot", {}, None)
    assert decode_cursor(first.next_cursor) == {"maxTime": "2026-10-14 10:00:00"}
    last = await jin10.backfill_page("hot", {}, first.next_cursor)
    assert rec.calls[1]["params"]["max_time"] == "2026-10-14 10:00:00" and last.next_cursor is None


def _fastbull_envelope(rows):
    return {"code": 0, "bodyMessage": json.dumps({"pageDatas": rows})}


async def test_fastbull_flash_timestamp_and_empty_history_page(monkeypatch):
    rows = [{"path": "11", "newsTitle": "a", "releasedDate": 1791900100000},
            {"path": "10", "newsTitle": "b", "releasedDate": 1791900000000}]
    rec = Recorder(_fastbull_envelope(rows), _fastbull_envelope([]))
    monkeypatch.setattr(fastbull, "get", rec)
    first = await fastbull.backfill_page("express", {}, None)
    assert "timestamp" not in rec.calls[0]["params"]
    assert decode_cursor(first.next_cursor) == {"timestamp": 1791900000000}
    last = await fastbull.backfill_page("express", {}, first.next_cursor)
    assert rec.calls[1]["params"]["timestamp"] == "1791900000000"
    assert last.data.data == [] and last.next_cursor is None  # end of window, not an error


async def test_fastbull_news_timestamp_is_exclusive_plus_one(monkeypatch):
    rows = [{"path": "7", "title": "t", "pubTime": 1791900000000, "langId": 1, "showNewsType": 1, "originalStatus": 0}]
    rec = Recorder(_fastbull_envelope(rows), _fastbull_envelope([]))
    monkeypatch.setattr(fastbull, "post", rec)
    first = await fastbull.backfill_page("news", {}, None)
    assert decode_cursor(first.next_cursor) == {"timestamp": 1791900000001}
    await fastbull.backfill_page("news", {}, first.next_cursor)
    assert rec.calls[1]["body"]["timestamp"] == 1791900000001


async def test_kr36_resigns_each_page_with_page_callback(monkeypatch):
    page_html = "<script>window.__GATEWAY_SIGN__='nonce-x'</script>"
    item = {"itemId": 1, "templateMaterial": {"widgetTitle": "t", "widgetContent": "c", "publishTime": 1791900000000}}
    get_rec = Recorder(page_html, page_html)
    post_rec = Recorder(
        {"code": 0, "data": {"itemList": [item], "pageCallback": "CB1"}},
        {"code": 0, "data": {"itemList": [], "pageCallback": "CB2"}},
    )
    monkeypatch.setattr(kr36_quick, "get", get_rec)
    monkeypatch.setattr(kr36_quick, "post", post_rec)
    first = await kr36_quick.backfill_page("quick-macro", {}, None)
    assert decode_cursor(first.next_cursor) == {"pageCallback": "CB1"}
    last = await kr36_quick.backfill_page("quick-macro", {}, first.next_cursor)
    body = json.loads(post_rec.calls[1]["body"])
    assert body["param"]["pageEvent"] == 1 and body["param"]["pageCallback"] == "CB1"
    assert body["param"]["type"] == 4 and body["nonce"] == "nonce-x"
    assert len(get_rec.calls) == 2  # nonce re-read per page
    assert last.next_cursor is None


async def test_opaque_cursor_routes(monkeypatch):
    rec = Recorder({"result": [{"id": 7, "content": "c", "createTimestamp": 1791900000}]}, {"result": []})
    monkeypatch.setattr(gelonghui, "get", rec)
    first = await gelonghui.backfill_page("hot", {}, None)
    await gelonghui.backfill_page("hot", {}, first.next_cursor)
    assert decode_cursor(first.next_cursor) == {"liveId": "7"} and rec.calls[1]["params"]["liveId"] == "7"

    news = {"data": {"data": {"seqMark": "M1", "news": [{"id": 1, "title": "t", "time": 1791900000}]}}}
    rec = Recorder(news, {"data": {"data": {"seqMark": "M2", "news": []}}})
    monkeypatch.setattr(futunn, "get", rec)
    first = await futunn.backfill_page("hot", {}, None)
    last = await futunn.backfill_page("hot", {}, first.next_cursor)
    assert rec.calls[1]["params"]["seqMark"] == "M1" and last.next_cursor is None

    rows = [{"id": "u2", "time": "2026-10-14T10:00:05Z", "data": {"content": "b"}},
            {"id": "u1", "time": "2026-10-14T10:00:00Z", "data": {"content": "a"}}]
    rec = Recorder({"data": rows}, {"data": []})
    monkeypatch.setattr(mktnews, "get", rec)
    first = await mktnews.backfill_page("hot", {}, None)
    last = await mktnews.backfill_page("hot", {}, first.next_cursor)
    assert decode_cursor(first.next_cursor) == {"lastId": "u1"}
    assert rec.calls[1]["params"]["last_id"] == "u1" and last.next_cursor is None


async def test_wallstreetcn_lives_and_latest(monkeypatch):
    lives = {"data": {"items": [{"id": 2, "content_text": "a", "display_time": 1791900100},
                                {"id": 1, "content_text": "b", "display_time": 1791900000}]}}
    rec = Recorder(lives, {"data": {"items": []}})
    monkeypatch.setattr(wallstreetcn, "get", rec)
    first = await wallstreetcn.backfill_page("forex", {}, None)
    await wallstreetcn.backfill_page("forex", {}, first.next_cursor)
    assert rec.calls[1]["params"]["cursor"] == "1791900001"
    assert rec.calls[1]["params"]["channel"] == "forex-channel"

    flow = {"data": {"next_cursor": "NC", "items": [{"resource": {"id": 9, "title": "t", "display_time": 1791900000}}]}}
    rec = Recorder(flow, {"data": {"next_cursor": "", "items": []}})
    monkeypatch.setattr(wallstreetcn, "get", rec)
    first = await wallstreetcn.backfill_page("latest", {}, None)
    last = await wallstreetcn.backfill_page("latest", {}, first.next_cursor)
    assert rec.calls[1]["params"] == {"channel": "global", "accept": "article", "limit": "30",
                                      "cursor": "NC", "action": "upglide"}
    assert last.next_cursor is None


@pytest.mark.parametrize("module", [jingji21, hexun, yicai, caixin_data])
async def test_page_number_routes_advance_and_stop(monkeypatch, module):
    calls: list[dict] = []

    async def fake_list(no_cache, *, page=1):
        calls.append({"page": page, "no_cache": no_cache})
        data = [] if page > 2 else ["x"]
        return {"from_cache": False, "update_time": "t", "data": data}

    monkeypatch.setattr(module, "_get_list", fake_list)
    monkeypatch.setattr(module, "_router_data", lambda list_data: _empty_router(list_data))
    cursor = None
    while True:
        page = await module.backfill_page("hot", {}, cursor)
        if page.next_cursor is None:
            break
        cursor = page.next_cursor
    assert [c["page"] for c in calls] == [1, 2, 3] and all(c["no_cache"] for c in calls)


def _empty_router(list_data):
    from whats_hot_api.models import RouterData

    return RouterData(kind="newsflash", name="x", title="x", type="x", total=0, fromCache=False,
                      updateTime="t", data=[])


async def test_page_number_source_requests_use_the_page(monkeypatch):
    rec = Recorder("{}")
    monkeypatch.setattr(jingji21, "get", rec)
    await jingji21._get_list(True, page=4)
    assert rec.calls[0]["params"] == {"page": "4"}


async def test_ths_news_columns_use_index_pages(monkeypatch):
    rec = Recorder("<html></html>", {"data": {"list": []}})
    monkeypatch.setattr(ths_10jqka, "get", rec)
    page = await ths_10jqka.backfill_page("global", {}, '{"page":3}')
    assert rec.calls[0]["url"].endswith("/index_3.shtml") and page.next_cursor is None
    await ths_10jqka.backfill_page("quick", {}, '{"page":2}')
    assert rec.calls[1]["params"]["page"] == "2"
    with pytest.raises(ValueError):
        await ths_10jqka.backfill_page("hot-stock", {}, None)


async def test_nbd_and_eeo_page_urls(monkeypatch):
    seen: list[str] = []

    async def fake_get(**kwargs):
        seen.append(kwargs["url"])
        if "getMoreArticle" in kwargs["url"]:
            return RequestResult(False, "t", {"code": 200, "data": []})
        raise RuntimeError("stop after recording the request")

    monkeypatch.setattr(nbd_eeo, "get", fake_get)
    with pytest.raises(RuntimeError):
        await nbd_eeo.backfill_page("nbd-news", {}, '{"page":4}')
    assert seen[-1].endswith("/page/4/")
    page = await nbd_eeo.backfill_page("eeo-business", {}, '{"page":3}')
    assert "page=2&" in seen[-1] and page.next_cursor is None and len(seen) == 2  # no channel page fetch


async def test_stcn_paged_list_carries_response_cursor(monkeypatch):
    fragment = '<li><div class="tt"><a href="/article/detail/1.html">标题</a></div><div class="info"><span>10-14 09:00</span></div></li>'
    rec = Recorder(
        {"data": {"state": 1, "data": fragment, "page_time": 2, "last_time": 1791900000},
         "headers": {"date": "Tue, 14 Oct 2026 02:00:00 GMT"}},
        {"data": {"state": 1, "data": "", "page_time": 3, "last_time": 1791800000}, "headers": {}},
    )
    monkeypatch.setattr(stcn_channels, "get", rec)
    first = await stcn_channels.backfill_page("yw", {}, None)
    assert rec.calls[0]["params"] == {"type": "yw", "page_time": "1"}
    assert decode_cursor(first.next_cursor) == {"pageTime": 2, "lastTime": 1791900001}
    last = await stcn_channels.backfill_page("yw", {}, first.next_cursor)
    assert rec.calls[1]["params"] == {"type": "yw", "page_time": "2", "last_time": "1791900001"}
    assert last.next_cursor is None
    with pytest.raises(ValueError):
        await stcn_channels.backfill_page("kx-rank", {}, None)


async def test_history_end_pages_finish_cleanly(monkeypatch):
    rec = Recorder({"data": {"state": 0, "msg": "x", "data": None}, "headers": {}})
    monkeypatch.setattr(stcn_channels, "get", rec)
    page = await stcn_channels.backfill_page("yw", {}, '{"pageTime":9,"lastTime":1}')
    assert page.data.data == [] and page.next_cursor is None
    rec.payloads.append({"data": {"state": 0, "data": None}, "headers": {}})
    with pytest.raises(RuntimeError):  # the first page failing is a real error
        await stcn_channels.backfill_page("yw", {}, None)

    seen: list[str] = []

    async def fake_get(**kwargs):
        seen.append(kwargs["url"])
        return RequestResult(False, "t", "<html><body></body></html>")

    monkeypatch.setattr(nbd_eeo, "get", fake_get)
    page = await nbd_eeo.backfill_page("nbd-news", {}, '{"page":51}')
    assert page.next_cursor is None and len(seen) == 1


async def test_p3_cursor_routes(monkeypatch):
    from whats_hot_api.routes.hotlist import cls_depth
    from whats_hot_api.routes.newsflash import telegram_osint, xuangubao

    rows = [{"id": 2, "title": "a", "published_at": 1791900100}, {"id": 1, "title": "b", "published_at": 1791900000}]
    rec = Recorder({"data": {"items": rows}}, {"data": {"items": []}})
    monkeypatch.setattr(xuangubao, "get", rec)
    first = await xuangubao.backfill_page("hot", {}, None)
    last = await xuangubao.backfill_page("hot", {}, first.next_cursor)
    assert rec.calls[1]["params"]["cursor"] == "1791900000" and last.next_cursor is None  # inclusive upstream

    html = ('<div class="tgme_widget_message" data-post="cig/105"><div class="tgme_widget_message_text">hello</div>'
            '<time datetime="2026-10-14T00:00:00+00:00"></time></div>'
            '<div class="tgme_widget_message" data-post="cig/101"><div class="tgme_widget_message_text">older</div>'
            '<time datetime="2026-10-13T00:00:00+00:00"></time></div>')
    rec = Recorder(html)
    monkeypatch.setattr(telegram_osint, "get", rec)
    page = await telegram_osint.backfill_page("cig", {}, '{"before":"200"}')
    assert rec.calls[0]["params"] == {"before": "200"} and decode_cursor(page.next_cursor) == {"before": "101"}

    assembled = {"errno": 0, "data": {"top_article": [{"id": 9, "title": "pinned", "ctime": 1700000000}],
                                      "depth_list": [{"id": 8, "title": "x", "ctime": 1791900100}]}}
    rec = Recorder(assembled, {"errno": 0, "data": []})
    monkeypatch.setattr(cls_depth, "get", rec)
    first = await cls_depth.backfill_page("a-share", {}, None)
    # Pinned rows are listed but never move the cursor; the list bound is exclusive.
    assert decode_cursor(first.next_cursor) == {"lastTime": 1791900101}
    last = await cls_depth.backfill_page("a-share", {}, first.next_cursor)
    assert "/v3/depth/list/" in rec.calls[1]["url"] and "last_time=1791900101" in rec.calls[1]["url"]
    assert last.next_cursor is None


async def test_p3_page_routes_build_page_requests(monkeypatch):
    from whats_hot_api.routes.hotlist import (
        caixin_caijing,
        exchange_regulator_news,
        netease_news_channels,
        szse_rules,
        yicai_21jingji,
    )
    from whats_hot_api.routes.newsflash import qbitai_embodied, techcrunch_robotics, who_outbreaks

    for module, path_type in ((techcrunch_robotics, "robotics"), (qbitai_embodied, "hot")):
        rec = Recorder("<rss></rss>")
        monkeypatch.setattr(module, "get", rec)
        page = await module.backfill_page(path_type, {}, '{"page":3}')
        assert rec.calls[0]["url"].endswith("?paged=3") and page.next_cursor is None  # past the end ends cleanly

    rec = Recorder({"value": []})
    monkeypatch.setattr(who_outbreaks, "get", rec)
    page = await who_outbreaks.backfill_page("hot", {}, '{"skip":100}')
    assert rec.calls[0]["params"]["$skip"] == "100" and page.next_cursor is None

    rec = Recorder({"code": "200", "data": []})
    monkeypatch.setattr(szse_rules, "post", rec)
    await szse_rules.backfill_page("hot", {}, '{"page":4}')
    assert "currentPage=4" in rec.calls[0]["body"]

    rec = Recorder({"code": 0, "data": {"articleList": []}})
    monkeypatch.setattr(caixin_caijing, "get", rec)
    await caixin_caijing.backfill_page("caixin-latest", {}, '{"page":3}')
    assert "page=3&" in rec.calls[0]["url"]

    rec = Recorder({"head": {"rep_code": "200"}, "records": []})
    monkeypatch.setattr(exchange_regulator_news, "post", rec)
    page = await exchange_regulator_news.backfill_page("chinamoney-bb", {}, '{"page":2}')
    assert "pageNo=2" in rec.calls[0]["body"] and page.next_cursor is None

    rec = Recorder('artiList({"T1":[]})')
    monkeypatch.setattr(netease_news_channels, "TOUCH_PAGES", {"exclusive-cz": ("p", "T1", "money")})
    monkeypatch.setattr(netease_news_channels, "get", rec)
    page = await netease_news_channels.backfill_page("exclusive-cz", {}, '{"page":3}')
    assert rec.calls[0]["url"].endswith("/T1/40-20.html") and page.next_cursor is None

    async def token(no_cache):
        return "tok"

    rec = Recorder([])
    monkeypatch.setattr(yicai_21jingji, "_get_m21_token", token)
    monkeypatch.setattr(yicai_21jingji, "get", rec)
    page = await yicai_21jingji.backfill_page("21jingji-health", {}, '{"page":5}')
    assert rec.calls[0]["url"].endswith("&type=json&page=5") and page.next_cursor is None
    with pytest.raises(ValueError):
        await yicai_21jingji.backfill_page("yicai-headline", {}, None)
