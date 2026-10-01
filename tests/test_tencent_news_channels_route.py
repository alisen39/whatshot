"""tencent_news_channels 路由测试:fixtures 按证据目录 tmp/board_api/tencent_news_channels
净化(结构与字段一致,内容摘录)。"""

from __future__ import annotations

import asyncio
import re
from datetime import datetime, timedelta, timezone

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import tencent_news_channels
from whats_hot_api.utils.http_client import RequestResult


def _request(board_type: str) -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/tencent-news-channels",
        "query_string": f"type={board_type}".encode(),
        "headers": [],
    })


# 娱乐榜:idlist[0].newslist,首条是说明占位(articletype 560),一条没有 hotEvent,
# 置顶条(hotEvent.is_top)应排最前;timestamp 是 Unix 秒
_ENT_PAYLOAD = {
    "ret": 0,
    "idlist": [
        {
            "newslist": [
                {"id": "TIP2023062717382000", "articletype": "560",
                 "title": "腾讯新闻用户关注的娱乐热点榜，每10分钟更新一次。"},
                {"id": "20260927V0AWXN00", "articletype": "4", "title": "普通条目无置顶",
                 "url": "https://view.inews.qq.com/a/20260927V0AWXN00",
                 "source": "贵圈星娱", "chlname": "贵圈星娱",
                 "time": "2026-09-27 22:13:33", "timestamp": 1790518413,
                 "thumbnails_qqnews": ["https://inews.gtimg.com/om_ls/cover_normal/0"],
                 "hotEvent": {"id": "20260927V0AWXN00", "title": "普通条目短标题",
                              "hotScore": 1000, "is_top": None}},
                {"id": "20260927V0TOP000", "articletype": "4", "title": "置顶条目",
                 "url": "https://view.inews.qq.com/a/20260927V0TOP000",
                 "source": "腾讯音乐", "chlname": "",
                 "time": "2026-09-27 21:00:00", "timestamp": 1790514000,
                 "thumbnails_qqnews": [],
                 "hotEvent": {"id": "20260927V0TOP000", "title": "置顶条目短标题",
                              "hotScore": 1337959, "is_top": 1}},
                {"id": "20260927V0NOEV0", "articletype": "4", "title": "没有 hotEvent 的条目",
                 "url": "https://view.inews.qq.com/a/20260927V0NOEV0"},
            ]
        }
    ],
}


@pytest.mark.asyncio
async def test_ent_rank_filters_and_maps_items(monkeypatch):
    captured = {}

    async def fake_get(url, headers=None, params=None, no_cache=None, **kwargs):
        captured.update({"url": url, "params": params, "headers": headers, "no_cache": no_cache})
        return RequestResult(False, "2026-10-01T00:00:00+00:00", _ENT_PAYLOAD)

    monkeypatch.setattr(tencent_news_channels, "get", fake_get)
    result = await tencent_news_channels.handle_route(_request("ent-rank"), no_cache=True)

    assert captured["url"] == "https://i.news.qq.com/gw/event/pc_hot_ranking_list"
    assert captured["params"]["rank_id"] == "ent"
    assert captured["params"]["page_size"] == "51"
    assert captured["headers"]["Referer"].startswith("https://news.qq.com/")
    assert result.type == "娱乐榜"
    # 说明占位(560)与没有 hotEvent 的条目去掉;置顶在前
    assert [item.id for item in result.data] == ["20260927V0TOP000", "20260927V0AWXN00"]
    top = result.data[0]
    # 标题取条目自身(文章标题),不取 hotEvent.title 短标题
    assert top.title == "置顶条目"
    assert top.url == "https://news.qq.com/rain/a/20260927V0TOP000"
    assert top.mobileUrl == "https://view.inews.qq.com/a/20260927V0TOP000"
    assert top.hot == 1337959
    assert top.author == "腾讯音乐"
    # 空缩略图列表跳过,秒级 timestamp ×1000
    assert top.cover is None
    assert top.timestamp == 1790514000000
    assert result.data[1].cover == "https://inews.gtimg.com/om_ls/cover_normal/0"


@pytest.mark.asyncio
async def test_ent_rank_rejects_business_error(monkeypatch):
    async def fake_get(url, headers=None, params=None, no_cache=None, **kwargs):
        return RequestResult(False, "t", {"ret": 404, "msg": "参数错误"})

    monkeypatch.setattr(tencent_news_channels, "get", fake_get)
    with pytest.raises(RuntimeError, match="ret=404"):
        await tencent_news_channels.handle_route(_request("ent-rank"), no_cache=True)


# 热问:data.hot_questions,code=0 才是成功;上游没有条目时间
_HOTQ_PAYLOAD = {
    "code": 0,
    "message": "success",
    "data": {
        "hot_questions": [
            {"title": "一技校101名毕业生入职北大做科研助手，这是一种怎样的职业路径？",
             "cms_id": "20260927Q09KTG00",
             "url": "https://new.qq.com/rain/a/20260927Q0BKT400",
             "answer_name": "夏夏回来了",
             "image": "https://inews.gtimg.com/om_ls/hotq_cover/0",
             "main_points": "看到101名技校生入职北大。一开始我以为标题党又来收割情绪了。"},
            {"title": "", "cms_id": "20260927QEMPTY00", "url": "https://new.qq.com/rain/a/x"},
        ],
        "answer": [{"title": "待回答问题"}],
    },
}


@pytest.mark.asyncio
async def test_hot_question_maps_items(monkeypatch):
    async def fake_get(url, headers=None, no_cache=None, **kwargs):
        assert url == "https://i.news.qq.com/web_backend/getHotQuestionList"
        return RequestResult(True, "2026-10-01T01:00:00+00:00", _HOTQ_PAYLOAD)

    monkeypatch.setattr(tencent_news_channels, "get", fake_get)
    result = await tencent_news_channels.handle_route(_request("hot-question"), no_cache=True)

    assert result.type == "热问"
    assert len(result.data) == 1  # 空标题的条目跳过
    item = result.data[0]
    assert item.id == "20260927Q09KTG00"
    assert item.url == "https://new.qq.com/rain/a/20260927Q0BKT400"
    assert item.mobileUrl == item.url
    assert item.author == "夏夏回来了"
    assert item.desc.startswith("看到101名技校生入职北大")
    assert item.hot is None
    assert item.timestamp is None  # 上游没有时间
    assert result.fromCache is True


@pytest.mark.asyncio
async def test_hot_question_rejects_error_shell(monkeypatch):
    async def fake_get(url, headers=None, no_cache=None, **kwargs):
        return RequestResult(False, "t", {"code": 10001, "message": "系统繁忙"})

    monkeypatch.setattr(tencent_news_channels, "get", fake_get)
    with pytest.raises(RuntimeError, match="10001"):
        await tencent_news_channels.handle_route(_request("hot-question"), no_cache=True)


# 谷雨实验室:ret=0 + newslist;articletype 空串 / 标签(123)的条目去掉
_GUYU_PAYLOAD = {
    "ret": 0,
    "newslist": [
        {"id": "20260923V06EAK00", "title": "她不只是费孝通的妻子，更是中国第一位女性社会学学者",
         "articletype": "4", "url": "https://view.inews.qq.com/a/20260923V06EAK00",
         "source": "谷雨实验室", "chlname": "谷雨实验室", "abstract": "学者与妻子的双重身份。",
         "time": "2026-09-23 11:57:08", "timestamp": 1790135828,
         "thumbnails_qqnews": ["https://inews.gtimg.com/om_ls/guyu_cover/0"]},
        {"id": "20260923VTAG0000", "title": "标签条目", "articletype": "123",
         "url": "https://view.inews.qq.com/a/20260923VTAG0000"},
        {"id": "", "title": "没有 id", "articletype": "4",
         "url": "https://view.inews.qq.com/a/none"},
    ],
}


@pytest.mark.asyncio
async def test_guyu_uses_default_tab_and_filters_tags(monkeypatch):
    captured = {}

    async def fake_get(url, headers=None, params=None, no_cache=None, **kwargs):
        captured.update({"url": url, "params": params})
        return RequestResult(False, "t", _GUYU_PAYLOAD)

    monkeypatch.setattr(tencent_news_channels, "get", fake_get)
    result = await tencent_news_channels.handle_route(_request("guyu-lab"), no_cache=True)

    assert captured["url"] == "https://i.news.qq.com/getSubNewsMixedList"
    # 作者页缺省页签"主页"(om_index),guestSuid 是作者 id
    assert captured["params"]["tabId"] == "om_index"
    assert captured["params"]["guestSuid"] == "8QMd3Hta64Advz3Z"
    assert result.type == "谷雨实验室"
    assert len(result.data) == 1
    item = result.data[0]
    assert item.id == "20260923V06EAK00"
    assert item.url == "https://news.qq.com/rain/a/20260923V06EAK00"
    assert item.mobileUrl == "https://view.inews.qq.com/a/20260923V06EAK00"
    assert item.author == "谷雨实验室"
    assert item.desc == "学者与妻子的双重身份。"
    assert item.timestamp == 1790135828000


def _tech_row(item_id: str, title: str, publish_time: str, cover: str | None, channel: str,
              desc: str = "", articletype: str = "0") -> dict:
    row = {"id": item_id, "title": title, "articletype": articletype,
           "publish_time": publish_time, "desc": desc,
           "media_info": {"chl_name": channel}}
    if cover:
        row["pic_info"] = {"big_img": [f"https://inews.gtimg.com/om_ls/{cover}"],
                           "small_img": [f"https://inews.gtimg.com/news_ls/{cover}"]}
    return row


# 科技频道:articletype 525 的热点精选卡片 sub_item 进顶部模块,其余进信息流,按 id 去重
_TECH_PAYLOAD = {
    "code": 0,
    "data": [
        {"id": "20240124A062NM00", "title": "热点精选", "articletype": "525",
         "sub_item": [
             {"id": "20240124A062NM00", "short_title": "特斯拉机器人周产量或已达数百台",
              "title": "9月28日科技早报｜特斯拉机器人周产量或已达数百台",
              "publish_time": "2026-09-28 07:04:30", "desc": "",
              "pic_info": {"big_img": ["https://inews.gtimg.com/om_ls/zao bao/0"], "small_img": []},
              "media_info": {"chl_name": "腾讯科技"},
              "link_info": {"url": "https://new.qq.com/rain/a/20240124A062NM00"}},
             {"id": "20260927V0NOCOV00", "short_title": "没有封面的条目",
              "title": "没有封面的条目", "publish_time": "2026-09-28 07:00:00",
              "media_info": {}},
         ]},
        _tech_row("20260927A06N0X00", "亚洲首富张一鸣，87亿抄底房地产", "2026-09-27 12:49:25",
                  "a06n0x00/0", "首席商业评论", desc="以下文章来源于首席品牌评论"),
        _tech_row("20260927A06N0X00", "重复条目", "2026-09-27 12:49:25", "dup/0", "首席商业评论"),
    ],
}


@pytest.mark.asyncio
async def test_tech_feed_posts_page_body_and_merges_hot_module(monkeypatch):
    captured = {}

    async def fake_post(url, body=None, headers=None, no_cache=None, cache_key=None, **kwargs):
        captured.update({"url": url, "body": body, "headers": headers, "cache_key": cache_key})
        return RequestResult(False, "t", _TECH_PAYLOAD)

    monkeypatch.setattr(tencent_news_channels, "post", fake_post)
    result = await tencent_news_channels.handle_route(_request("tech-feed"), no_cache=True)

    assert captured["url"] == "https://i.news.qq.com/web_feed/getPCList"
    assert captured["body"]["channel_id"] == "news_news_tech"
    assert captured["body"]["item_count"] == 12
    assert captured["body"]["base_req"] == {"from": "pc"}
    # qimei36 = device_id,随机 36 位小写字母数字
    qimei = captured["body"]["qimei36"]
    assert qimei == captured["body"]["device_id"]
    assert re.fullmatch(r"[a-z0-9]{36}", qimei)
    # 请求体带随机 qimei36,缓存键必须固定才能命中
    assert captured["cache_key"] == "tencent-news-channels:tech-feed"

    assert result.type == "科技频道"
    # 顶部模块在前,信息流在后,重复 id 只留一次,没有封面的条目不输出
    assert [item.id for item in result.data] == ["20240124A062NM00", "20260927A06N0X00"]
    top = result.data[0]
    # 标题 short_title 优先;链接拼 adChannelId=tech
    assert top.title == "特斯拉机器人周产量或已达数百台"
    assert top.url == "https://news.qq.com/rain/a/20240124A062NM00?adChannelId=tech"
    assert top.mobileUrl == "https://new.qq.com/rain/a/20240124A062NM00"
    assert top.author == "腾讯科技"
    # 北京时间 publish_time → 毫秒
    _bj = timezone(timedelta(hours=8))
    assert top.timestamp == int(datetime(2026, 9, 28, 7, 4, 30, tzinfo=_bj).timestamp()) * 1000
    assert result.data[1].desc == "以下文章来源于首席品牌评论"


@pytest.mark.asyncio
async def test_tech_feed_rejects_error_shell(monkeypatch):
    async def fake_post(url, body=None, headers=None, no_cache=None, cache_key=None, **kwargs):
        return RequestResult(False, "t", {"code": 99998, "desc": "系统繁忙"})

    monkeypatch.setattr(tencent_news_channels, "post", fake_post)
    with pytest.raises(RuntimeError, match="99998"):
        await tencent_news_channels.handle_route(_request("tech-feed"), no_cache=True)


def test_unknown_board_is_rejected():
    with pytest.raises(ValueError, match="Unknown board"):
        asyncio.run(tencent_news_channels.handle_route(_request("not-a-board")))
