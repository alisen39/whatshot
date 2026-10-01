from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import exchange_regulator_news
from whats_hot_api.utils.http_client import RequestResult

_BEIJING = timezone(timedelta(hours=8))
_UPDATE_TIME = "2026-10-01T00:00:00+00:00"


def _request(board_type: str) -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/exchange-regulator-news",
        "query_string": f"type={board_type}".encode(),
        "headers": [],
    })


def _ms(text: str, fmt: str = "%Y-%m-%d %H:%M:%S") -> int:
    return int(datetime.strptime(text, fmt).replace(tzinfo=_BEIJING).timestamp() * 1000)


def _sse_html() -> str:
    # 净化自 evidence/01_sse_latest.response.body(新页 sselawsrules2025,div.sse_list_1 dl dd)
    return """
    <html><body><div class="sse_list_1" id="sse_list_1"><dl>
      <dd>
        <span>2026-09-04</span>
        <a href="/lawandrules/sselawsrules2025/bond/review/c/c_20260904_10831327.shtml"
           title="上海证券交易所公司债券发行上市审核规则适用指引第6号——知名成熟发行人优化审核（2026年修订）">内文文字</a>
      </dd>
      <dd>
        <span>2026-07-24</span>
        <a href="https://www.sse.com.cn/lawandrules/sselawsrules2025/bond/listing/assets/c/c_20260724_10826663.shtml">没有 title 属性的条目</a>
      </dd>
    </dl></div></body></html>
    """


@pytest.mark.asyncio
async def test_sse_latest_rules_parses_new_page(monkeypatch):
    async def fake_get(url, params=None, no_cache=None, **kwargs):
        assert url == "https://www.sse.com.cn/lawandrules/sselawsrules2025/latest/"  # 新页,不是 tophub 的旧页
        assert params is None
        return RequestResult(False, _UPDATE_TIME, _sse_html())

    monkeypatch.setattr(exchange_regulator_news, "get", fake_get)
    result = await exchange_regulator_news.handle_route(_request("sse-latest-rules"), no_cache=True)

    assert result.type == "上交所 · 最新规则"
    assert result.total == 2
    first = result.data[0]
    assert first.id == "20260904_10831327"  # 链接里的 c_<日期>_<编号>
    assert first.url == "https://www.sse.com.cn/lawandrules/sselawsrules2025/bond/review/c/c_20260904_10831327.shtml"
    assert first.title == "上海证券交易所公司债券发行上市审核规则适用指引第6号——知名成熟发行人优化审核（2026年修订）"
    assert first.timestamp == _ms("2026-09-04 00:00:00")  # 只有日期,北京时间 0 点
    assert result.data[1].id == "20260724_10826663"  # 绝对链接不再重复拼前缀
    assert result.data[1].title == "没有 title 属性的条目"


def _bse_jsonp() -> str:
    # 净化自 evidence/02_bse_listse.response.body(null([...]) JSONP)
    rows = [
        {
            "htmlUrl": "/important_news/200010667.html",
            "infoId": 200010667,
            "linkUrl": "",
            "metaDescription": "我们将继续支持中小企业创新发展。",
            "publishDate": "2021-09-02 09:08:33",
            "title": "习近平在2021年中国国际服务贸易交易会全球服务贸易峰会上的致辞",
        },
        {
            "htmlUrl": "",
            "infoId": 200029481,
            "linkUrl": "https://www.bse.cn/jggg/200029481.html",
            "metaDescription": "",
            "publishDate": "2026-09-30 18:10:00",
            "title": "关于调整第二届证券发行承销自律委员会委员名单的公告\\n",
        },
    ]
    return "null(" + json.dumps([{"result": True, "data": {"content": rows, "totalElements": 732}}], ensure_ascii=False) + ")"


@pytest.mark.asyncio
async def test_bse_news_posts_listse_form_and_parses_jsonp(monkeypatch):
    captured = {}

    async def fake_post(url, headers=None, body=None, no_cache=None, **kwargs):
        captured["url"] = url
        captured["headers"] = headers
        captured["body"] = body
        assert kwargs.get("response_type") == "text"
        return RequestResult(False, _UPDATE_TIME, _bse_jsonp())

    monkeypatch.setattr(exchange_regulator_news, "post", fake_post)
    result = await exchange_regulator_news.handle_route(_request("bse-news"), no_cache=True)

    assert captured["url"] == "https://www.bse.cn/info/listse.do"
    assert captured["headers"]["Content-Type"] == "application/x-www-form-urlencoded"
    assert captured["headers"]["Referer"] == "https://www.bse.cn/news/important_news.html"
    assert captured["headers"]["User-Agent"].startswith("Mozilla/5.0")  # httpx 缺省 UA 被 WAF 403
    form = parse_qs(captured["body"])
    assert form["nodeIds[]"] == ["1289"]  # 本所动态节点
    assert form["pageSize"] == ["20"]
    assert form["page"] == ["0"]
    assert set(form["needFields[]"]) == {"infoId", "title", "metaDescription", "linkUrl", "htmlUrl", "publishDate"}
    assert "siteId" not in form  # 北交所不带 siteId(股转才带)

    first = result.data[0]
    assert first.id == "200010667"  # infoId;置顶的 2021 年致辞照原站顺序保留
    assert first.url == "https://www.bse.cn/important_news/200010667.html"  # linkUrl 空时用 htmlUrl
    assert first.desc == "我们将继续支持中小企业创新发展。"
    assert first.timestamp == _ms("2021-09-02 09:08:33")
    second = result.data[1]
    assert second.url == "https://www.bse.cn/jggg/200029481.html"  # 有 linkUrl 用 linkUrl
    assert second.title == "关于调整第二届证券发行承销自律委员会委员名单的公告"  # 去掉字面 \n
    assert second.timestamp == _ms("2026-09-30 18:10:00")


@pytest.mark.asyncio
async def test_bse_cc_challenge_js_page_retries_with_cookie_literal(monkeypatch):
    calls: list[dict] = []

    async def fake_post(url, headers=None, body=None, no_cache=None, **kwargs):
        calls.append({"headers": headers})
        if len(calls) == 1:
            # CC 防护跳过 307、直接回 200 的 JS 跳转页(345 字节,C3VK 值是明文字面量)
            return RequestResult(
                False,
                _UPDATE_TIME,
                '<script>var _$daewqwskl=["\\x64\\x6f\\x63\\x75\\x6d\\x65\\x6e\\x74"];'
                'window[_$daewqwskl[0]].cookie="C3VK=a15de1; path=/; max-age=300;";window.open("/", "_self");</script>',
            )
        return RequestResult(False, _UPDATE_TIME, _bse_jsonp())

    monkeypatch.setattr(exchange_regulator_news, "post", fake_post)
    result = await exchange_regulator_news.handle_route(_request("bse-news"), no_cache=True)

    assert len(calls) == 2
    assert calls[1]["headers"]["Cookie"] == "C3VK=a15de1"  # 服务器给定字面值,照写重发
    assert result.total == 2


@pytest.mark.asyncio
async def test_neeq_form_carries_site_id_and_node(monkeypatch):
    captured = {}

    async def fake_post(url, headers=None, body=None, no_cache=None, **kwargs):
        captured["url"] = url
        captured["body"] = body
        return RequestResult(False, _UPDATE_TIME, _bse_jsonp())

    monkeypatch.setattr(exchange_regulator_news, "post", fake_post)
    result = await exchange_regulator_news.handle_route(_request("neeq-news"), no_cache=True)

    assert captured["url"] == "https://www.neeq.com.cn/info/listse.do"
    form = parse_qs(captured["body"])
    assert form["nodeIds[]"] == ["94"]  # 股转动态节点
    assert form["siteId"] == ["1"]  # 页面脚本额外带的字段
    assert result.total == 2  # 解析逻辑与北交所共用


def _cnstock_home_html() -> str:
    filter_ids = ["797580", "604232"]
    return (
        "<html><head><script>var x=1;</script></head><body>"
        '<script id="__NEXT_DATA__" type="application/json">'
        + json.dumps({"props": {"pageProps": {"data": {"filterIdArray": filter_ids}}}})
        + "</script></body></html>"
    )


def _cnstock_waterfall_payload() -> dict:
    return {
        "code": 200,
        "data": {
            "list": [
                {
                    "contId": "797816",
                    "link": "",
                    "name": "英国首相再提重新加入欧盟问题",
                    "pubTime": "1小时前",
                    "pic": "https://image.cnstock.com/image/797816.png",
                    "forwardType": 4,
                    "shareInfo": {
                        "shareUrl": "https://m.cnstock.com/commonDetail/797816",
                        "summary": "据新华社伦敦9月30日电。",
                        "dateInfo": {"year": 2026, "month": "09", "day": "30", "hour": "19", "minute": "21"},
                    },
                    "author": "张枫",
                },
                {
                    "contId": "521957",
                    "name": "专题·四点半观市",
                    "forwardType": 9,
                    "shareInfo": {"summary": "权威、专业、价值 尽在上海证券报客户端", "dateInfo": {"year": 2026, "month": "09", "day": "29", "hour": "15", "minute": "30"}},
                },
                {
                    "contId": "999",
                    "name": "外部栏目卡片",
                    "forwardType": 6,
                    "link": "https://example.com/external",
                    "shareInfo": {},
                },
                {"contId": "1000", "name": "频道导航卡片", "forwardType": 1, "shareInfo": {}},
            ]
        },
    }


@pytest.mark.asyncio
async def test_cnstock_waterfall_chain_and_card_rules(monkeypatch):
    captured = {}

    async def fake_get(url, params=None, no_cache=None, **kwargs):
        assert url == "https://www.cnstock.com/"
        return RequestResult(False, _UPDATE_TIME, _cnstock_home_html())

    async def fake_post(url, headers=None, body=None, no_cache=None, **kwargs):
        captured[url] = (headers, body)
        if url.endswith("/indexChannels"):
            return RequestResult(False, _UPDATE_TIME, {"code": 200, "data": {"filterIdArray": ["700001"]}})
        assert url.endswith("/waterfallPage")
        return RequestResult(False, _UPDATE_TIME, _cnstock_waterfall_payload())

    monkeypatch.setattr(exchange_regulator_news, "get", fake_get)
    monkeypatch.setattr(exchange_regulator_news, "post", fake_post)
    result = await exchange_regulator_news.handle_route(_request("cnstock-latest"), no_cache=True)

    channel_headers, channel_body = captured["https://api.cnstock.com/www/index/indexChannels"]
    assert channel_headers["cnstock-client-type"] == "01"  # 缺了返回 code=10304 未登录
    assert channel_body == {}
    _wf_headers, wf_body = captured["https://api.cnstock.com/www/index/waterfallPage"]
    assert wf_body == {"filterIdArray": ["797580", "604232", "700001"], "pageNum": 1}  # 首页 + 频道两段拼接(频道排序)

    assert result.total == 3  # 频道/标签导航卡片(ft=1)不是条目
    first = result.data[0]
    assert first.id == "797816"
    assert first.url == "https://www.cnstock.com/commonDetail/797816"  # forwardType=4 链接规则
    assert first.mobileUrl == "https://m.cnstock.com/commonDetail/797816"
    assert first.author == "张枫"
    assert first.timestamp == _ms("2026-09-30 19:21", "%Y-%m-%d %H:%M")  # dateInfo,不用 pubTime 相对时间
    second = result.data[1]
    assert second.url == "https://www.cnstock.com/topicDetail/521957"  # 专题卡照信息流保留
    assert second.desc is None  # 客户端宣传语不是摘要
    third = result.data[2]
    assert third.url == "https://example.com/external"  # ft=6 外链直接用 link


def _cs_guide() -> str:
    return "//20260930\nvar PAGE_INDEX_MAP9=PAGE_INDEX_MAP = {\"1\":\"mi4_sub_articles_20260930.js\"};"


def _cs_day_file() -> str:
    rows = [
        {"title": f"财经要闻第{i}条", "url": f"https://www.cs.com.cn/xwzx/01/2026/09/30/detail_20260930100426{i:02d}.html",
         "pub_date": "2026-09-30 20:25", "isTop": 0, "miSummary": "", "pubAuthor": "新华社", "miCover43": "", "miCover169": ""}
        for i in range(15)
    ]
    # 金牛座外链与一条重复 url:重复的跳过,首屏仍是 15 条
    rows[0]["url"] = "https://jnzstatic.cs.com.cn/zzb/htmlInfo/134477.html"
    rows.append(dict(rows[1]))
    head = "//20260930\nvar MI4_PAGE_ARTICLE = "
    return head + json.dumps(rows, ensure_ascii=False) + ";"


@pytest.mark.asyncio
async def test_cs_finance_reads_top_guide_and_day_files(monkeypatch):
    urls: list[str] = []

    async def fake_get(url, params=None, no_cache=None, **kwargs):
        urls.append(url)
        if url.endswith("mi4_sub_articles_top.js"):
            return RequestResult(False, _UPDATE_TIME, "//20260930\nvar MI4_PAGE_ARTICLE = [];")
        if url.endswith("mi4_page_articles_guide.js"):
            return RequestResult(False, _UPDATE_TIME, _cs_guide())
        assert url.endswith("mi4_sub_articles_20260930.js")
        return RequestResult(False, _UPDATE_TIME, _cs_day_file())

    monkeypatch.setattr(exchange_regulator_news, "get", fake_get)
    result = await exchange_regulator_news.handle_route(_request("cs-finance"), no_cache=True)

    assert urls == [
        "https://www.cs.com.cn/js/9/mi4_sub_articles_top.js",
        "https://www.cs.com.cn/js/9/mi4_page_articles_guide.js",
        "https://www.cs.com.cn/js/9/mi4_sub_articles_20260930.js",
    ]
    assert result.total == 15  # 首屏 15 条(simpleLoadMore count:15)
    assert result.data[0].id == "jnz-134477"  # 金牛座外链加 jnz- 前缀,两套编号不混
    assert result.data[1].id == "2026093010042601"  # 站内 detail_<id>.html
    assert result.data[1].timestamp == _ms("2026-09-30 20:25", "%Y-%m-%d %H:%M")
    assert len({item.url for item in result.data}) == 15  # 重复 url 已跳过


def _chinamoney_payload() -> dict:
    return {
        "head": {"rep_code": "200", "rep_message": ""},
        "records": [
            {
                "contentId": "3420412",
                "title": "2026年9月20日全国银行间同业拆借中心受权公布贷款市场报价利率（LPR）公告",
                "releaseDate": "2026-09-20",
                "url": None,
                "draftPath": "/chinese/rdgz/20260920/3420412.html",
            },
            {
                "contentId": "3420001",
                "title": "带绝对链接的公告",
                "releaseDate": "2026-09-19",
                "url": "https://www.chinamoney.com.cn/chinese/rdgz/20260919/3420001.html",
                "draftPath": None,
            },
        ],
    }


@pytest.mark.asyncio
async def test_chinamoney_lpr_posts_channel_and_maps_records(monkeypatch):
    captured = {}

    async def fake_post(url, headers=None, body=None, no_cache=None, **kwargs):
        captured["url"] = url
        captured["body"] = body
        captured["headers"] = headers
        return RequestResult(False, _UPDATE_TIME, _chinamoney_payload())

    monkeypatch.setattr(exchange_regulator_news, "post", fake_post)
    result = await exchange_regulator_news.handle_route(_request("chinamoney-lpr"), no_cache=True)

    assert captured["url"] == "https://www.chinamoney.com.cn/ags/ms/cm-s-notice-query/contentsinshorttime"
    assert parse_qs(captured["body"]) == {"pageNo": ["1"], "pageSize": ["15"], "channelId": ["3686"]}  # bklprmkn2
    assert captured["headers"]["Referer"] == "https://www.chinamoney.com.cn/chinese/bklpr/"

    first = result.data[0]
    assert first.id == "3420412"  # contentId
    assert first.url == "https://www.chinamoney.com.cn/chinese/rdgz/20260920/3420412.html"  # draftPath,不带 #cp= 锚点
    assert first.timestamp == _ms("2026-09-20 00:00:00")
    assert result.data[1].url == "https://www.chinamoney.com.cn/chinese/rdgz/20260919/3420001.html"  # 有 url 用 url


@pytest.mark.asyncio
async def test_chinamoney_business_error_is_rejected(monkeypatch):
    async def fake_post(url, headers=None, body=None, no_cache=None, **kwargs):
        # 去掉 channelId 时的业务错误壳
        return RequestResult(False, _UPDATE_TIME, {"head": {"rep_code": "400", "rep_message": "channelId required"}, "records": []})

    monkeypatch.setattr(exchange_regulator_news, "post", fake_post)
    with pytest.raises(RuntimeError, match="rep_code"):
        await exchange_regulator_news.handle_route(_request("chinamoney-fx"), no_cache=True)


def _nifd_html() -> str:
    # 净化自 evidence/07_nifd_weekly.response.body(旧版研究列表页,服务端渲染)
    return """
    <html><body>
    <div class="qr-main-item qr-main-item-change">
      <h4 class="ellipsis"><a href="/SeriesReport/Details/5106">金融风险周报 2026年第39期 </a></h4>
      <span style="float:right;color:#606060">[2026年09月28日]</span>
    </div>
    <div class="qr-main-item qr-main-item-change">
      <h4 class="ellipsis"><a href="/SeriesReport/Details/5102">金融风险周报（2026年第38期） </a></h4>
      <span>[2026年09月22日]</span>
    </div>
    </body></html>
    """


@pytest.mark.asyncio
async def test_nifd_weekly_parses_research_list(monkeypatch):
    async def fake_get(url, params=None, no_cache=None, **kwargs):
        assert url == "http://www.nifd.cn/Research?categoryGuid=7a6a826d-b525-42aa-b550-4236e524227f"
        return RequestResult(False, _UPDATE_TIME, _nifd_html())

    monkeypatch.setattr(exchange_regulator_news, "get", fake_get)
    result = await exchange_regulator_news.handle_route(_request("nifd-weekly"), no_cache=True)

    assert result.type == "国家金融与发展实验室 · 周报（金融风险周报）"
    first = result.data[0]
    assert first.id == "5106"  # /Details/<id>
    assert first.url == "http://www.nifd.cn/SeriesReport/Details/5106"
    assert first.title == "金融风险周报 2026年第39期"  # 原站正式标题,不是 tophub 截的摘要前 24 字
    assert first.timestamp == _ms("2026-09-28 00:00:00")  # [2026年09月28日] → 北京时间 0 点
    assert result.data[1].id == "5102"


@pytest.mark.asyncio
async def test_unknown_board_type_is_rejected():
    with pytest.raises(ValueError, match="Unknown board"):
        await exchange_regulator_news.handle_route(_request("no-such-site"), no_cache=True)
