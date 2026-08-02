from __future__ import annotations

import json

import pytest
from starlette.requests import Request

from whats_hot_api.models import NewsFlashItem
from whats_hot_api.routes.newsflash import (
    cls,
    eastmoney,
    fastbull,
    futunn,
    gelonghui,
    hexun,
    jingji21,
    jiemian,
    jin10,
    jrj,
    sina_finance,
    ths_10jqka,
    wallstreetcn,
    yicai,
)
from whats_hot_api.utils.http_client import RequestResult


def _request(query_string: bytes = b"") -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/",
        "query_string": query_string,
        "headers": [],
    })


@pytest.mark.asyncio
@pytest.mark.parametrize(("board_type", "path"), (("express", "/cn/express-news"), ("news", "/cn/news")))
async def test_fastbull_native_boards_are_newsflash(monkeypatch, board_type, path):
    async def fake_get(**kwargs):  # noqa: ANN003
        assert kwargs["url"].endswith(path)
        assert kwargs["ttl"] == fastbull.config.NEWSFLASH_CACHE_TTL
        return RequestResult(
            False,
            "fastbull-update",
            '<div class="news-list" data-date="2026-07-30T12:30:00+08:00"><a class="title_name" href="/news/123">【市场】市场消息</a><p class="summary">快讯摘要</p></div>',
        )

    monkeypatch.setattr(fastbull, "get", fake_get)
    result = await fastbull.handle_route(_request(f"type={board_type}".encode()), no_cache=True)

    assert result.kind == "newsflash"
    assert result.type == fastbull.TYPE_MAP[board_type]
    assert isinstance(result.data[0], NewsFlashItem)
    assert result.data[0].title == "市场"
    assert result.data[0].content == "快讯摘要"


@pytest.mark.asyncio
async def test_wallstreetcn_uses_full_newsflash_model(monkeypatch):
    long_body = "华尔街见闻正文" + "很长" * 260

    async def fake_get(**kwargs):  # noqa: ANN003, ARG001
        return RequestResult(
            False,
            "2026-06-29T00:00:00+00:00",
            {
                "data": {
                    "items": [
                        {
                            "id": 3125707,
                            "title": "轻量化AI设备需求激增",
                            "content_text": long_body,
                            "content_more": "",
                            "comment_count": "7",
                            "score": "3",
                            "display_time": "1782668201",
                            "uri": "https://wallstreetcn.com/livenews/3125707",
                            "author": {"display_name": "华尔街见闻"},
                            "symbols": [{"symbol": "AAPL", "name": "Apple"}],
                        }
                    ]
                }
            },
        )

    monkeypatch.setattr(wallstreetcn, "get", fake_get)

    route_data = await wallstreetcn.handle_route(_request())
    item = route_data.data[0]

    assert route_data.kind == "newsflash"
    assert isinstance(item, NewsFlashItem)
    assert len(item.content) > 500
    assert item.contentStatus == "full"
    assert item.metrics == {"commentCount": 7, "score": 3}
    assert item.symbols == [{"symbol": "AAPL", "name": "Apple"}]
    assert "hot" not in item.model_dump()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("board_type", "endpoint", "payload"),
    (
        ("hot", "articles/hot", {"data": {"day_items": [{"id": 9, "title": "热门文章", "content_short": "摘要", "uri": "https://example.com/hot"}]}}),
        ("latest", "information-flow", {"data": {"items": [{"resource": {"id": 10, "title": "最新文章", "content_short": "摘要", "uri": "https://example.com/latest"}}]}}),
    ),
)
async def test_wallstreetcn_native_featured_boards_are_newsflash(monkeypatch, board_type, endpoint, payload):
    async def fake_get(**kwargs):  # noqa: ANN003
        assert endpoint in kwargs["url"]
        return RequestResult(False, "wscn-update", payload)

    monkeypatch.setattr(wallstreetcn, "get", fake_get)
    result = await wallstreetcn.handle_route(_request(f"type={board_type}".encode()), no_cache=True)
    assert result.kind == "newsflash"
    assert result.type == {"hot": "最热", "latest": "最新"}[board_type]
    assert result.data[0].content == "摘要"


@pytest.mark.asyncio
async def test_eastmoney_maps_important_channel_and_symbols(monkeypatch):
    summary = "【轮胎涨价背后的温差与变局】" + "正文" * 260 + "..."

    async def fake_get(**kwargs):  # noqa: ANN003, ARG001
        return RequestResult(
            False,
            "2026-06-29T00:00:00+00:00",
            {
                "data": {
                    "fastNewsList": [
                        {
                            "code": "202606283785634553",
                            "title": "轮胎涨价背后的温差与变局",
                            "summary": summary,
                            "pinglun_Num": "11",
                            "share": "2",
                            "realSort": "1782668700034553",
                            "showTime": "2026-06-29 01:45:00",
                            "stockList": [{"code": "600000", "name": "浦发银行"}],
                        }
                    ]
                }
            },
        )

    monkeypatch.setattr(eastmoney, "get", fake_get)

    route_data = await eastmoney.handle_route(_request(b"type=important"))
    item = route_data.data[0]

    assert route_data.kind == "newsflash"
    assert isinstance(item, NewsFlashItem)
    assert item.isImportant is True
    assert len(item.content) > 500
    assert item.contentStatus == "truncated"
    assert item.metrics["commentCount"] == 11
    assert item.metrics["shareCount"] == 2
    assert item.symbols == [{"code": "600000", "name": "浦发银行"}]


@pytest.mark.asyncio
async def test_sina_finance_uses_docurl_and_focus_metrics(monkeypatch):
    content = "【委内瑞拉强震遇难人数升至1450人】" + "当地时间消息。" * 80

    async def fake_get(**kwargs):  # noqa: ANN003, ARG001
        return RequestResult(
            False,
            "2026-06-29T00:00:00+00:00",
            {
                "result": {
                    "data": {
                        "feed": {
                            "list": [
                                {
                                    "id": "4959090",
                                    "rich_text": content,
                                    "docurl": "https://finance.sina.cn/7x24/detail.d.html",
                                    "is_focus": "1",
                                    "top_value": "10",
                                    "view_num": "5.61万 阅读",
                                    "comment_num": "4",
                                    "like_nums": "9",
                                    "create_time": "2026-06-29 01:45:18",
                                    "tag": [{"name": "国际"}],
                                    "ext": '{"stocks":[{"code":"000001","name":"平安银行"}]}',
                                }
                            ]
                        }
                    }
                }
            },
        )

    monkeypatch.setattr(sina_finance, "get", fake_get)

    route_data = await sina_finance.handle_route(_request())
    item = route_data.data[0]

    assert route_data.kind == "newsflash"
    assert isinstance(item, NewsFlashItem)
    assert item.title == "委内瑞拉强震遇难人数升至1450人"
    assert item.url == "https://finance.sina.cn/7x24/detail.d.html"
    assert item.isImportant is True
    assert item.metrics["viewCount"] == 56100
    assert item.metrics["commentCount"] == 4
    assert item.tags == ["国际"]
    assert item.symbols == [{"code": "000001", "name": "平安银行"}]


@pytest.mark.asyncio
async def test_sina_finance_central_bank_uses_tag_seven(monkeypatch):
    async def fake_get(**kwargs):  # noqa: ANN003
        assert kwargs["params"]["tag"] == "7"
        return RequestResult(
            False,
            "2026-07-16T00:00:00+00:00",
            {
                "result": {
                    "data": {
                        "feed": {
                            "list": [
                                {
                                    "id": "4992226",
                                    "rich_text": "欧洲央行将存款利率维持在2.25%。",
                                    "create_time": "2026-07-16 19:16:45",
                                    "tag": [{"name": "央行"}],
                                }
                            ]
                        }
                    }
                }
            },
        )

    monkeypatch.setattr(sina_finance, "get", fake_get)

    route_data = await sina_finance.handle_route(
        _request(b"type=central-bank")
    )

    assert route_data.kind == "newsflash"
    assert route_data.type == "央行"
    assert route_data.total == 1
    assert route_data.data[0].id == "4992226"
    assert route_data.data[0].tags == ["央行"]


@pytest.mark.asyncio
async def test_cls_prefers_content_and_maps_importance(monkeypatch):
    content = "【普京召开保障国内市场燃料供应的会议】" + "完整正文" * 180

    async def fake_get(**kwargs):  # noqa: ANN003, ARG001
        return RequestResult(
            False,
            "2026-06-29T00:00:00+00:00",
            {
                "data": {
                    "roll_data": [
                        {
                            "id": 2411196,
                            "title": "普京召开保障国内市场燃料供应的会议",
                            "brief": "短摘要",
                            "content": content,
                            "author": "俄罗斯卫星通讯社",
                            "is_ad": "0",
                            "is_top": "1",
                            "bold": "0",
                            "recommend": "0",
                            "level": "A",
                            "reading_num": "16974",
                            "comment_num": "6",
                            "share_num": "8",
                            "ctime": "1782667515",
                            "stock_list": [{"code": "000001", "name": "平安银行"}],
                        }
                    ]
                }
            },
        )

    monkeypatch.setattr(cls, "get", fake_get)

    route_data = await cls.handle_route(_request())
    item = route_data.data[0]

    assert route_data.kind == "newsflash"
    assert isinstance(item, NewsFlashItem)
    assert len(item.content) > 500
    assert item.summary == "短摘要"
    assert item.source == "俄罗斯卫星通讯社"
    assert item.isImportant is True
    assert item.metrics["readingCount"] == 16974
    assert item.metrics["shareCount"] == 8
    assert item.metrics["level"] == "A"
    assert item.symbols == [{"code": "000001", "name": "平安银行"}]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("board_type", "endpoint", "label"),
    (("depth", "/v3/depth/home/assembled/1000", "深度"), ("hot", "/v2/article/hot/list", "热门")),
)
async def test_cls_native_article_boards_are_newsflash(monkeypatch, board_type, endpoint, label):
    async def fake_get(**kwargs):  # noqa: ANN003
        assert endpoint in kwargs["url"]
        payload = {"data": {"depth_list": [{"id": 8, "title": "深度报道", "brief": "摘要", "ctime": 1783330100}]}}
        if board_type == "hot":
            payload = {"data": [{"id": 8, "title": "热门报道", "brief": "摘要", "ctime": 1783330100}]}
        return RequestResult(False, "cls-update", payload)

    monkeypatch.setattr(cls, "get", fake_get)
    request = Request({"type": "http", "method": "GET", "path": "/cls", "query_string": f"type={board_type}".encode(), "headers": []})
    result = await cls.handle_route(request, no_cache=True)
    assert result.kind == "newsflash"
    assert result.type == label
    assert result.data[0].content == "摘要"


@pytest.mark.asyncio
async def test_21jingji_maps_quick_news_payload(monkeypatch):
    content = "南方财经7月6日电，截至目前，南向资金净买入额达170亿港元。"

    async def fake_get(**kwargs):  # noqa: ANN003, ARG001
        return RequestResult(
            False,
            "2026-07-06T07:30:00+00:00",
            json.dumps(
                {
                    "catname": "快报",
                    "list": [
                        {
                            "id": "1092973",
                            "title": "南向资金净买入额达170亿港元",
                            "shortTitle": "",
                            "inputtime": "2026-07-06 15:29",
                            "author": "21快讯",
                            "username": "南财快讯",
                            "content": content,
                            "thumb": "https://example.com/thumb.jpg",
                            "keywords": "南向资金,净买入额,资金流动",
                            "description": "南向资金快讯摘要",
                            "url": "https://m.21jingji.com/timeline/detail.html",
                            "redMark": "1",
                            "important": "0",
                            "warning": "0",
                            "stock_data": [{"code": "00700", "name": "腾讯控股"}],
                            "riskrating": "2",
                            "21ProductID": "2793506",
                            "source": "南方财经",
                        }
                    ],
                },
                ensure_ascii=False,
            ),
        )

    monkeypatch.setattr(jingji21, "get", fake_get)

    route_data = await jingji21.handle_route(_request())
    item = route_data.data[0]

    assert route_data.kind == "newsflash"
    assert route_data.name == "21jingji"
    assert isinstance(item, NewsFlashItem)
    assert item.title == "南向资金净买入额达170亿港元"
    assert item.content == content
    assert item.summary == "南向资金快讯摘要"
    assert item.source == "南方财经"
    assert item.isImportant is True
    assert item.tags == ["南向资金", "净买入额", "资金流动"]
    assert item.images == ["https://example.com/thumb.jpg"]
    assert item.symbols == [{"code": "00700", "name": "腾讯控股"}]
    assert item.metrics["riskRating"] == 2
    assert item.metrics["productId"] == 2793506
    assert item.timestamp is not None
    assert item.url == "https://m.21jingji.com/timeline/detail.html"


@pytest.mark.asyncio
async def test_futunn_maps_flash_news_payload(monkeypatch):
    async def fake_get(**kwargs):  # noqa: ANN003, ARG001
        return RequestResult(
            False,
            "2026-07-06T07:40:00+00:00",
            {
                "code": 0,
                "data": {
                    "data": {
                        "news": [
                            {
                                "relatedStocks": [
                                    {"code": "HK.00700", "name": "腾讯控股"}
                                ],
                                "quote": [{"code": "US.AAPL", "name": "苹果"}],
                                "content": "深圳计划入市的商品房项目30个。",
                                "detailUrl": "https://news.futunn.com/flash/20482759",
                                "id": "20482759",
                                "level": 1,
                                "newsType": 2,
                                "newsUniqueId": "flash:20482759",
                                "pic": "https://newsimg.futunn.com/flash_pic.png/big",
                                "time": "1783323124",
                                "title": "深圳三季度30个楼盘将入市",
                                "newsContentType": 1,
                                "sourceId": "684",
                                "isAutoTranslated": 0,
                            }
                        ]
                    }
                },
            },
        )

    monkeypatch.setattr(futunn, "get", fake_get)

    route_data = await futunn.handle_route(_request())
    item = route_data.data[0]

    assert route_data.kind == "newsflash"
    assert route_data.name == "futunn"
    assert isinstance(item, NewsFlashItem)
    assert item.id == "flash:20482759"
    assert item.title == "深圳三季度30个楼盘将入市"
    assert item.content == "深圳计划入市的商品房项目30个。"
    assert item.source == "富途牛牛"
    assert item.isImportant is True
    assert item.images == ["https://newsimg.futunn.com/flash_pic.png/big"]
    assert item.symbols == [
        {"code": "HK.00700", "name": "腾讯控股"},
        {"code": "US.AAPL", "name": "苹果"},
    ]
    assert item.metrics["level"] == 1
    assert item.metrics["newsType"] == 2
    assert item.metrics["sourceId"] == 684
    assert item.timestamp is not None
    assert item.url == "https://news.futunn.com/flash/20482759"


@pytest.mark.asyncio
async def test_gelonghui_maps_live_payload(monkeypatch):
    async def fake_get(**kwargs):  # noqa: ANN003, ARG001
        return RequestResult(
            False,
            "2026-07-06T07:50:00+00:00",
            {
                "statusCode": 200,
                "result": [
                    {
                        "id": 2538303,
                        "title": "",
                        "createTimestamp": 1783323230,
                        "count": {
                            "read": 12,
                            "comment": 3,
                            "favorite": 2,
                            "like": 7,
                            "share": 1,
                        },
                        "content": "【研报掘金】东方证券维持洽洽食品买入评级。",
                        "relatedStocks": [
                            {
                                "market": "SZ",
                                "code": "002557",
                                "name": "洽洽食品",
                                "canClick": True,
                            }
                        ],
                        "pictures": [{"url": "https://example.com/live.jpg"}],
                        "source": {"name": "格隆汇研究"},
                        "level": 1,
                        "route": "https://www.gelonghui.com/live/2538303",
                    }
                ],
            },
        )

    monkeypatch.setattr(gelonghui, "get", fake_get)

    route_data = await gelonghui.handle_route(_request())
    item = route_data.data[0]

    assert route_data.kind == "newsflash"
    assert route_data.name == "gelonghui"
    assert isinstance(item, NewsFlashItem)
    assert item.title == "研报掘金"
    assert item.content == "【研报掘金】东方证券维持洽洽食品买入评级。"
    assert item.source == "格隆汇研究"
    assert item.isImportant is True
    assert item.images == ["https://example.com/live.jpg"]
    assert item.symbols == [
        {"market": "SZ", "code": "002557", "name": "洽洽食品", "canClick": True}
    ]
    assert item.metrics["readCount"] == 12
    assert item.metrics["commentCount"] == 3
    assert item.metrics["likeCount"] == 7
    assert item.metrics["shareCount"] == 1
    assert item.timestamp is not None
    assert item.url == "https://www.gelonghui.com/live/2538303"


@pytest.mark.asyncio
async def test_hexun_maps_jsonp_global_news_payload(monkeypatch):
    payload = {
        "totalNumber": 813056,
        "totalPage": 100,
        "currentPage": 1,
        "result": [
            {
                "abstract": "腾讯混元Hy3正式发布。相较preview版本，Hy3表现更强...",
                "author": "王治强",
                "entitytime": "2026-07-06 15:32",
                "entityurl": "http://stock.hexun.com/2026-07-06/224542430.html",
                "id": 224542430,
                "keyword": "Hy,腾讯,preview,发布,业务",
                "mediaid": 4465,
                "medianame": "证券时报",
                "newsmatchpic": "http://i4.hexun.com/2014-11-27/170856677.jpg",
                "title": "腾讯混元Hy3正式发布",
            }
        ],
    }

    async def fake_get(**kwargs):  # noqa: ANN003, ARG001
        return RequestResult(
            False,
            "2026-07-06T08:00:00+00:00",
            f"whats_hot_hexun({json.dumps(payload, ensure_ascii=False)})",
        )

    monkeypatch.setattr(hexun, "get", fake_get)

    route_data = await hexun.handle_route(_request())
    item = route_data.data[0]

    assert route_data.kind == "newsflash"
    assert route_data.name == "hexun"
    assert isinstance(item, NewsFlashItem)
    assert item.id == "224542430"
    assert item.title == "腾讯混元Hy3正式发布"
    assert item.contentStatus == "truncated"
    assert item.summary == "腾讯混元Hy3正式发布。相较preview版本，Hy3表现更强..."
    assert item.source == "证券时报"
    assert item.tags == ["Hy", "腾讯", "preview", "发布", "业务"]
    assert item.images == ["http://i4.hexun.com/2014-11-27/170856677.jpg"]
    assert item.metrics["mediaId"] == 4465
    assert item.metrics["totalPage"] == 100
    assert item.metrics["totalNumber"] == 813056
    assert item.timestamp is not None
    assert item.url == "http://stock.hexun.com/2026-07-06/224542430.html"


@pytest.mark.asyncio
async def test_jiemian_maps_and_sorts_flash_payload(monkeypatch):
    async def fake_get(**kwargs):  # noqa: ANN003, ARG001
        assert kwargs["cache_key"].endswith("window=latest")
        return RequestResult(
            False,
            "2026-07-06T08:10:00+00:00",
            {
                "code": "0",
                "message": "suss",
                "result": [
                    {
                        "id": "older",
                        "publishtime": "1783322000",
                        "title": "较早快讯",
                        "summary": "较早正文",
                        "weights": "C",
                    },
                    {
                        "id": "14708143",
                        "publishtime": "1783322789",
                        "title": "首届全球人工智能治理对话在日内瓦举行",
                        "summary": "当地时间7月6日，首届全球人工智能治理对话举行。",
                        "weights": "A",
                        "is_make_img": "1",
                        "img_urls": ["https://example.com/ai.jpg"],
                        "edit_cms": 0,
                        "blackwhite": "0",
                    },
                ],
            },
        )

    monkeypatch.setattr(jiemian, "get", fake_get)

    route_data = await jiemian.handle_route(_request())
    item = route_data.data[0]

    assert route_data.kind == "newsflash"
    assert route_data.name == "jiemian"
    assert isinstance(item, NewsFlashItem)
    assert item.id == "14708143"
    assert item.title == "首届全球人工智能治理对话在日内瓦举行"
    assert item.summary == "当地时间7月6日，首届全球人工智能治理对话举行。"
    assert item.source == "界面新闻"
    assert item.isImportant is True
    assert item.images == ["https://example.com/ai.jpg"]
    assert item.metrics["weight"] == "A"
    assert item.metrics["isMakeImg"] == 1
    assert item.timestamp is not None
    assert item.url == "https://www.jiemian.com/article/14708143.html"


@pytest.mark.asyncio
async def test_jin10_maps_nested_flash_payload(monkeypatch):
    async def fake_get(**kwargs):  # noqa: ANN003, ARG001
        assert kwargs["headers"]["x-app-id"] == "bVBF4FyRTn5NJF5n"
        return RequestResult(
            False,
            "2026-07-06T08:20:00+00:00",
            {
                "status": 200,
                "message": "OK",
                "data": [
                    {
                        "id": "20260706153706577800",
                        "time": "2026-07-06 15:37:06",
                        "type": 0,
                        "data": {
                            "pic": "https://example.com/jin10.jpg",
                            "title": "",
                            "source": "",
                            "content": "【有研粉材：股东询价转让定价101.06元/股】金十数据快讯正文。",
                            "source_link": "",
                        },
                        "important": 1,
                        "tags": [{"name": "A股"}],
                        "channel": [3, 4, 5],
                        "remark": [
                            {
                                "id": 78227603,
                                "type": "quotes",
                                "title": "有研粉材",
                                "symbol": "688456.SH",
                            }
                        ],
                        "extras": {"ad": False},
                        "voice_status": "ready",
                    }
                ],
            },
        )

    monkeypatch.setattr(jin10, "get", fake_get)

    route_data = await jin10.handle_route(_request())
    item = route_data.data[0]

    assert route_data.kind == "newsflash"
    assert route_data.name == "jin10"
    assert isinstance(item, NewsFlashItem)
    assert item.id == "20260706153706577800"
    assert item.title == "有研粉材：股东询价转让定价101.06元/股"
    assert item.source == "金十数据"
    assert item.isImportant is True
    assert item.tags == ["A股"]
    assert item.images == ["https://example.com/jin10.jpg"]
    assert item.symbols == [
        {
            "id": 78227603,
            "type": "quotes",
            "title": "有研粉材",
            "symbol": "688456.SH",
        }
    ]
    assert item.metrics["flashType"] == 0
    assert item.metrics["flashTypeLabel"] == "快讯"
    assert item.metrics["channels"] == [3, 4, 5]
    assert item.metrics["voiceStatus"] == "ready"
    assert item.timestamp is not None
    assert item.url == "https://flash.jin10.com/detail/20260706153706577800"


@pytest.mark.asyncio
async def test_jrj_posts_and_maps_news_flash_payload(monkeypatch):
    async def fake_post(**kwargs):  # noqa: ANN003
        assert kwargs["body"] == {}
        assert kwargs["headers"]["Content-Type"] == "application/json"
        return RequestResult(
            False,
            "2026-07-06T08:30:00+00:00",
            {
                "code": 20000,
                "data": {
                    "data": [
                        {
                            "iiId": 57713738,
                            "title": "美湖股份：聘任陆顺刚为公司董事会秘书",
                            "makeDate": "2026-07-06 15:40:19",
                            "pcInfoUrl": "https://24h.jrj.com.cn/2026/07/06154057713738.shtml",
                            "infoUrl": "https://apppage.jrj.com.cn/news/24h/detail.shtml",
                            "minfoUrl": "https://m.jrj.com.cn/madapter/24h/2026/07/06154057713738.shtml",
                            "channelNum": "003",
                            "infoCls": "001001",
                            "imgUrl": "https://example.com/jrj.jpg",
                            "paperMediaSource": "智通财经",
                            "detail": "美湖股份公告称，公司聘任陆顺刚为董事会秘书。",
                            "readNum": "12",
                            "stockList": [
                                {
                                    "stockId": "1603319",
                                    "stockCode": "603319",
                                    "stockName": "美湖股份",
                                    "stockType": "1",
                                }
                            ],
                            "isRed": 1,
                            "hotValue": "88",
                            "summary": "任命公告摘要",
                            "imageUrls": ["https://example.com/jrj-2.jpg"],
                        }
                    ]
                },
            },
        )

    monkeypatch.setattr(jrj, "post", fake_post)

    route_data = await jrj.handle_route(_request())
    item = route_data.data[0]

    assert route_data.kind == "newsflash"
    assert route_data.name == "jrj"
    assert isinstance(item, NewsFlashItem)
    assert item.id == "57713738"
    assert item.title == "美湖股份：聘任陆顺刚为公司董事会秘书"
    assert item.summary == "任命公告摘要"
    assert item.source == "智通财经"
    assert item.isImportant is True
    assert item.images == [
        "https://example.com/jrj.jpg",
        "https://example.com/jrj-2.jpg",
    ]
    assert item.symbols == [
        {
            "stockId": "1603319",
            "stockCode": "603319",
            "stockName": "美湖股份",
            "stockType": "1",
        }
    ]
    assert item.metrics["readCount"] == 12
    assert item.metrics["hotValue"] == 88
    assert item.timestamp is not None
    assert item.url == "https://24h.jrj.com.cn/2026/07/06154057713738.shtml"
    assert item.mobileUrl == "https://m.jrj.com.cn/madapter/24h/2026/07/06154057713738.shtml"


@pytest.mark.asyncio
async def test_ths_10jqka_maps_global_news_payload(monkeypatch):
    async def fake_get(**kwargs):  # noqa: ANN003, ARG001
        return RequestResult(
            False,
            "2026-07-06T08:40:00+00:00",
            {
                "code": 0,
                "msg": "成功",
                "data": {
                    "list": [
                        {
                            "id": "4657559",
                            "seq": "677973642",
                            "title": "宝地矿业：预计2026年上半年净利润同比增长",
                            "digest": "宝地矿业公告，预计2026年半年度净利润同比增加。",
                            "url": "https://news.10jqka.com.cn/20260706/c677973642.shtml",
                            "appUrl": "https://news.10jqka.com.cn/m677973642/",
                            "color": "2",
                            "tag": "公告,A股",
                            "tags": [
                                {"id": "34843", "name": "公告"},
                                {"id": "21103", "name": "A股"},
                            ],
                            "rtime": "1783323622",
                            "source": "",
                            "picUrl": "https://example.com/ths.jpg",
                            "nature": "0",
                            "stock": [
                                {
                                    "name": "宝地矿业",
                                    "stockCode": "601121",
                                    "stockMarket": "17",
                                }
                            ],
                            "import": "3",
                            "tagInfo": [
                                {"id": "50000426", "name": "半年报", "score": "0.71"}
                            ],
                        }
                    ]
                },
            },
        )

    monkeypatch.setattr(ths_10jqka, "get", fake_get)

    route_data = await ths_10jqka.handle_route(_request())
    item = route_data.data[0]

    assert route_data.kind == "newsflash"
    assert route_data.name == "ths-10jqka"
    assert isinstance(item, NewsFlashItem)
    assert item.id == "4657559"
    assert item.title == "宝地矿业：预计2026年上半年净利润同比增长"
    assert item.source == "同花顺"
    assert item.isImportant is True
    assert item.tags == ["公告", "A股", "半年报"]
    assert item.images == ["https://example.com/ths.jpg"]
    assert item.symbols == [
        {"name": "宝地矿业", "stockCode": "601121", "stockMarket": "17"}
    ]
    assert item.metrics["seq"] == 677973642
    assert item.metrics["importance"] == 3
    assert item.metrics["topicTags"] == ["半年报"]
    assert item.timestamp is not None
    assert item.url == "https://news.10jqka.com.cn/20260706/c677973642.shtml"
    assert item.mobileUrl == "https://news.10jqka.com.cn/m677973642/"


@pytest.mark.asyncio
async def test_yicai_maps_quick_news_payload(monkeypatch):
    async def fake_get(**kwargs):  # noqa: ANN003, ARG001
        return RequestResult(
            False,
            "2026-07-06T08:50:00+00:00",
            [
                {
                    "CountVotes": 4,
                    "CreateDate": "2026-07-06T15:43:48",
                    "IsImportant": True,
                    "LiveContent": "<b>据证券时报</b>，人工智能产业链持续发展。",
                    "LiveID": 103261965,
                    "LiveImages": "https://example.com/1.jpg,https://example.com/2.jpg",
                    "LiveTitle": "东吴证券总裁薛臻：聚焦人工智能核心赛道",
                    "LiveWeight": 5,
                    "NewsHot": 9,
                    "ShareUrl": "https://m.yicai.com/brief/103261965.html",
                    "VideoID": 0,
                    "VideoThumb": "https://example.com/video.jpg",
                    "topics": "人工智能,证券",
                    "url": "/brief/103261965.html",
                    "id": 103261965,
                    "important": True,
                    "istop": False,
                }
            ],
        )

    monkeypatch.setattr(yicai, "get", fake_get)

    route_data = await yicai.handle_route(_request())
    item = route_data.data[0]

    assert route_data.kind == "newsflash"
    assert route_data.name == "yicai"
    assert isinstance(item, NewsFlashItem)
    assert item.id == "103261965"
    assert item.title == "东吴证券总裁薛臻：聚焦人工智能核心赛道"
    assert item.content == "据证券时报，人工智能产业链持续发展。"
    assert item.source == "第一财经"
    assert item.isImportant is True
    assert item.tags == ["人工智能", "证券"]
    assert item.images == [
        "https://example.com/1.jpg",
        "https://example.com/2.jpg",
        "https://example.com/video.jpg",
    ]
    assert item.metrics["liveWeight"] == 5
    assert item.metrics["newsHot"] == 9
    assert item.metrics["countVotes"] == 4
    assert item.timestamp is not None
    assert item.url == "https://www.yicai.com/brief/103261965.html"
    assert item.mobileUrl == "https://m.yicai.com/brief/103261965.html"
