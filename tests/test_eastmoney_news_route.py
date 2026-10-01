from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import eastmoney_news
from whats_hot_api.utils.http_client import RequestResult

_BEIJING = timezone(timedelta(hours=8))
_UPDATE_TIME = "2026-10-01T00:00:00+00:00"


def _request(board_type: str) -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/eastmoney-news",
        "query_string": f"type={board_type}".encode(),
        "headers": [],
    })


def _ms(text: str) -> int:
    return int(datetime.strptime(text, "%Y-%m-%d %H:%M:%S").replace(tzinfo=_BEIJING).timestamp() * 1000)


def _column_payload() -> dict:
    # 净化自 evidence/02_api_finance-ccjdd.response.body(只取结构与字段)
    return {
        "req_trace": "1790556000000",
        "code": 1,
        "message": "success",
        "data": {
            "page_index": 1,
            "page_size": 20,
            "totle_hits": 2440,
            "list": [
                {
                    "code": "202609283884561151",
                    "np_dst": "CMS",
                    "showTime": "2026-09-28 06:49:08",
                    "title": "美伊对峙7个月 美称本周将继续与伊谈判 伊称尚未放弃外交途径",
                    "mediaName": "央视新闻客户端",
                    "summary": "【美伊对峙7个月…】据美国方面当地时间9月27日消息",
                    "image": "https://np-newspic.dfcfw.com/download/D25100403928794094880_w210h154.jpg",
                    "url": "http://finance.eastmoney.com/news/1351,202609283884561151.html",
                    "uniqueUrl": "http://finance.eastmoney.com/a/202609283884561151.html",
                },
                {
                    "code": "202609213880203046",
                    "np_dst": "CFH",
                    "showTime": "2026-09-21 20:31:12",
                    "title": "9月21日东方财富财经晚报（附新闻联播）",
                    "mediaName": "东方财富网",
                    "summary": "财经晚报摘要",
                    "image": "",
                    "url": "http://caifuhao.eastmoney.com/news/202609213880203046",
                    "uniqueUrl": "",
                },
            ],
        },
    }


@pytest.mark.asyncio
async def test_column_default_board_maps_fields_and_link_rules(monkeypatch):
    captured = {}

    async def fake_get(url, params=None, no_cache=None, **kwargs):
        captured["url"] = url
        captured["params"] = params
        return RequestResult(False, _UPDATE_TIME, _column_payload())

    monkeypatch.setattr(eastmoney_news, "get", fake_get)
    result = await eastmoney_news.handle_route(_request("finance-ccjdd"), no_cache=True)

    assert captured["url"] == "https://np-listapi.eastmoney.com/comm/web/getNewsByColumns"
    params = captured["params"]
    assert params["client"] == "web"
    assert params["biz"] == "web_news_col"
    assert params["column"] == 344  # 默认榜财经导读的栏目号
    assert params["order"] == "1"  # 顺序照接口 order=1
    assert params["page_index"] == "1"
    assert params["page_size"] == 20
    assert params["req_trace"]  # 页面传当前毫秒时间,任意值都行但不能缺

    assert result.type == "财经导读"
    assert result.total == 2
    first = result.data[0]
    assert first.id == "202609283884561151"  # 上游稳定标识 code,不用名次
    assert first.url == "https://finance.eastmoney.com/a/202609283884561151.html"  # 页面链接规则,不用接口旧格式 url
    assert first.cover == "https://np-newspic.dfcfw.com/download/D25100403928794094880_w210h154.jpg"
    assert first.author == "央视新闻客户端"
    assert first.timestamp == _ms("2026-09-28 06:49:08")
    # 财富号文章(np_dst=CFH)照 newslistbefore.js 链到 caifuhao
    assert result.data[1].url == "http://caifuhao.eastmoney.com/news/202609213880203046"


@pytest.mark.asyncio
async def test_column_error_shell_is_rejected(monkeypatch):
    async def fake_get(url, params=None, no_cache=None, **kwargs):
        # 去掉 req_trace 时的业务错误壳(实测 code=0)
        return RequestResult(False, _UPDATE_TIME, {"code": 0, "message": "Required String parameter 'req_trace' is not present"})

    monkeypatch.setattr(eastmoney_news, "get", fake_get)
    with pytest.raises(RuntimeError, match="code=0"):
        await eastmoney_news.handle_route(_request("finance-cywjh"), no_cache=True)


@pytest.mark.asyncio
async def test_click_rank_parses_server_rendered_box(monkeypatch):
    html = """
    <html><body>
    <div class="Wydj clearfix"><div class="tabList"><ul class="h28 fn">
      <li><span class="no">1</span> <a target="_blank" href="/a/202609273884428846.html">假期要闻汇总：中美达成八点成果共识</a></li>
      <li><span class="no">2</span> <a target="_blank" href="https://finance.eastmoney.com/a/202609273884486243.html">9月27日晚间沪深上市公司重大事项公告最新快递</a></li>
    </ul></div></div>
    </body></html>
    """

    async def fake_get(url, params=None, no_cache=None, **kwargs):
        assert url == "https://finance.eastmoney.com/a/ccjdd.html"  # 资讯榜取财经栏目页右栏
        assert params is None
        return RequestResult(False, _UPDATE_TIME, html)

    monkeypatch.setattr(eastmoney_news, "get", fake_get)
    result = await eastmoney_news.handle_route(_request("finance-rank"), no_cache=True)

    assert result.total == 2
    first = result.data[0]
    assert first.id == "202609273884428846"  # 链接里的 code
    assert first.url == "https://finance.eastmoney.com/a/202609273884428846.html"  # 相对链接已拼全
    assert first.title == "假期要闻汇总：中美达成八点成果共识"
    assert first.timestamp is None  # 页面不给时间
    assert result.data[1].id == "202609273884486243"


@pytest.mark.asyncio
async def test_click_rank_missing_box_is_an_error(monkeypatch):
    async def fake_get(url, params=None, no_cache=None, **kwargs):
        return RequestResult(False, _UPDATE_TIME, "<html><body>其它页面</body></html>")

    monkeypatch.setattr(eastmoney_news, "get", fake_get)
    with pytest.raises(RuntimeError, match="div.Wydj"):
        await eastmoney_news.handle_route(_request("finance-rank"), no_cache=True)


@pytest.mark.asyncio
async def test_guba_hot_maps_click_count_and_link_rules(monkeypatch):
    payload = {
        "re": [
            {
                "post_id": 1777851260,
                "post_title": "明天开盘！证监会首次处罚操纵次新股",
                "post_source_id": "20260927172355665614490",
                "post_click_count": 102267,
                "post_publish_time": "2026-09-27 17:23:55",
                "post_abstract": "",
                "post_content": "正文第一段" + "x" * 300,
                "post_pic_url": ["https://gbimg.eastmoney.com/pic.jpg"],
                "post_user": {"user_nickname": "国际投行研究报告"},
                "post_guba": {"stockbar_code": ""},
            },
            {
                "post_id": 1777000001,
                "post_title": "普通股吧帖子",
                "post_source_id": "",
                "post_click_count": 55,
                "post_publish_time": "2026-09-26 09:00:00",
                "post_abstract": "摘要",
                "post_guba": {"stockbar_code": "600519"},
            },
        ],
        "count": 50,
        "rc": 1,
        "me": "操作成功",
    }

    async def fake_get(url, params=None, no_cache=None, **kwargs):
        assert url == "https://gbapi.eastmoney.com/operation/api/HotRanking/List"
        # plat/version/product 缺任一个返回"系统繁忙[0000x]"
        assert params == {"pageSize": "50", "condition": "", "plat": "Web", "version": "2022", "product": "Guba"}
        return RequestResult(False, _UPDATE_TIME, payload)

    monkeypatch.setattr(eastmoney_news, "get", fake_get)
    result = await eastmoney_news.handle_route(_request("guba-hot"), no_cache=True)

    first = result.data[0]
    assert first.id == "1777851260"  # post_id
    assert first.url == "https://caifuhao.eastmoney.com/news/20260927172355665614490"  # 组件链接写法
    assert first.hot == 102267  # post_click_count
    assert first.author == "国际投行研究报告"
    assert first.cover == "https://gbimg.eastmoney.com/pic.jpg"
    assert len(first.desc) == 200  # 没有摘要时取正文前 200 字
    assert first.timestamp == _ms("2026-09-27 17:23:55")
    # 没有财富号 id 的普通帖子退回股吧帖子页
    assert result.data[1].url == "https://guba.eastmoney.com/news,600519,1777000001.html"
    assert result.data[1].desc == "摘要"


@pytest.mark.asyncio
async def test_guba_error_shell_is_rejected(monkeypatch):
    async def fake_get(url, params=None, no_cache=None, **kwargs):
        # 去掉 plat 时的业务错误壳(实测 rc=0 系统繁忙[00002])
        return RequestResult(False, _UPDATE_TIME, {"re": [], "count": 0, "rc": 0, "me": "系统繁忙, 请稍后再试[00002]"})

    monkeypatch.setattr(eastmoney_news, "get", fake_get)
    with pytest.raises(RuntimeError, match="rc=0"):
        await eastmoney_news.handle_route(_request("guba-hot"), no_cache=True)


@pytest.mark.asyncio
async def test_strategy_reports_map_infocode_and_range(monkeypatch):
    captured = {}

    async def fake_get(url, params=None, no_cache=None, **kwargs):
        captured["url"] = url
        captured["params"] = params
        return RequestResult(False, _UPDATE_TIME, {
            "hits": 8317,
            "size": 50,
            "data": [
                {
                    "title": "投资策略周报：会晤后，重盈利、寻张力",
                    "orgSName": "开源证券",
                    "researcher": "韦冀星,简宇涵",
                    "publishDate": "2026-09-27 00:00:00.000",
                    "encodeUrl": "/UP/gYXm9i8m/GPRkSi8sUE72JorpKOZMGfxah/msrU=",
                    "infoCode": "AP202609271829939278",
                },
            ],
        })

    monkeypatch.setattr(eastmoney_news, "get", fake_get)
    result = await eastmoney_news.handle_route(_request("data-strategy"), no_cache=True)

    assert captured["url"] == "https://reportapi.eastmoney.com/report/dg"
    params = captured["params"]
    assert params["qType"] == "2"  # 2=策略报告(3 宏观研究、4 券商晨会)
    assert params["pageSize"] == "50"
    assert params["pageNo"] == "1"
    # 近 2 年:endTime 是今天(北京时间),beginTime 是两年前
    assert params["endTime"] == datetime.now(_BEIJING).date().isoformat()
    assert params["beginTime"] == datetime.now(_BEIJING).date().replace(
        year=datetime.now(_BEIJING).year - 2
    ).isoformat()

    item = result.data[0]
    assert item.id == "AP202609271829939278"  # infoCode(dg 独有;jg 只有 encodeUrl)
    assert item.url == "https://data.eastmoney.com/report/zw_strategy.jshtml?encodeUrl=/UP/gYXm9i8m/GPRkSi8sUE72JorpKOZMGfxah/msrU="
    assert item.author == "开源证券 韦冀星、简宇涵"
    assert item.timestamp == _ms("2026-09-27 00:00:00")  # 只有日期,取当天 0 点,毫秒


@pytest.mark.asyncio
async def test_unknown_board_type_is_rejected():
    with pytest.raises(ValueError, match="Unknown board"):
        await eastmoney_news.handle_route(_request("no-such-board"), no_cache=True)
