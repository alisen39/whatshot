"""caixin_caijing 路由测试:fixtures 按证据目录 tmp/board_api/caixin_caijing 净化(结构与字段一致,内容摘录)。"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import caixin_caijing
from whats_hot_api.utils.http_client import RequestResult

_BEIJING = timezone(timedelta(hours=8))
# 首页响应生成时刻:2026-09-30 20:00 北京时间(测 "MM月DD日 HH:MM" 的年份推断)
_HOME_DATE = "Wed, 30 Sep 2026 12:00:00 GMT"

_SCROLL_PAYLOAD = {
    "code": 0,
    "msg": "success",
    "data": {
        "currentPage": 1,
        "pageSize": 20,
        "totalRecords": 334968,
        "articleList": [
            {"contentId": "102490147", "title": "迪拜航空航班急降沙特无人员死亡 飞行员被指袭击同僚欲造空难",
             "summary": "有报道称，发动袭击的副驾驶来自阿曼。", "author": "文｜财新 路尘", "channel": "132",
             "url": "https://international.caixin.com/2026-09-30/102490147.html",
             "picture": "https://img.caixin.com/2026-09-30/179077070853020.jpg", "time": 1790769598000},
            {"contentId": "102490123", "title": "招商证券总裁落定 副总裁刘波接任",
             "summary": "招商证券总裁落定。", "author": "", "channel": "125",
             "url": "https://finance.caixin.com/2026-09-30/102490123.html", "picture": "", "time": None},
        ],
    },
}

# homeInterface:JSONP,回调包装前有十几个换行(param_matrix 实测)
_SUBJECT_ROWS = [
    {"link": "https://china.caixin.com/2026-09-29/102489757.html", "nid": 102489757,
     "desc": "证监会：进一步优化沪深港通机制", "summ": "进一步优化沪深港通机制。",
     "pict": {"imgs": [{"txt": "", "url": "https://img.caixin.com/2026-09-29/179068664446832_266_177.jpg"}]},
     "edit": {"name": "文｜财新 王晶"}, "time": "2026-09-29 08:00:00"},
    {"link": "https://china.caixin.com/2026-09-28/102489600.html", "nid": 102489600,
     "desc": "", "summ": "", "pict": None, "edit": None, "time": ""},
]
_SUBJECT_JSONP = "\n" * 12 + "cb(" + json.dumps({"datas": _SUBJECT_ROWS, "start": 0, "count": 25}, ensure_ascii=False) + ")"

# 首页三块:头条(左栏 dl + 轮播 dl + 专题入口图 entry02)→ 图片列表头条 li → 新闻主体(dl / 图集 / 广告位)
_HOME_PAGE = """
<html><body>
<!--头条 begin-->
<div class="toutiao_box">
  <div class="left"><div class="demolNews">
    <dl><dt><a href="https://weekly.caixin.com/2026-09-26/102488802.html">最新财新周刊｜绿氢“十五五”新动能</a></dt>
    <dd><span>文｜财新周刊 卢羽桐 09月30日 15:20</span></dd></dl>
  </div></div>
  <div class="middle"><div class="changePic"><div id="zyqh">
    <dl align="center"><span><a href="https://photos.caixin.com/2026-09-22/102487443.html">
    <img src="https://img.caixin.com//2026-09-22/179006156846643.jpg"></a></span>
    <div class="wzdf"><a href="https://photos.caixin.com/2026-09-22/102487443.html">视线｜AI数据中心狂热扩张撞上全美反抗浪潮</a></div></dl>
  </div></div></div>
  <div class="right">
    <div class="entry02"><a href="https://topics.caixin.com/2026/asia-new-vision-forum_2026/">
    <img src="https://img.caixin.com/2026-09-30/topic.jpg"></a></div>
    <dl><dt><a href="https://international.caixin.com/2026-09-30/102490005.html">朝鲜副外相联大自我宣告已为“拥核国家”</a></dt>
    <dd><span>文｜财新 罗子琳 09月30日 16:58</span></dd></dl>
  </div>
</div>
<!-- 图片列表头条 begin -->
<div class="img_list_box"><ul>
  <li><span><a href="https://weekly.caixin.com/2026-09-24/102488599.html">
  <img src="https://img.caixin.com/2026-09-26/179038879387514_300_200.jpg"></a></span>
  <em><a href="https://weekly.caixin.com/2026-09-24/102488599.html">最新封面报道</a></em>
  <p><a href="https://weekly.caixin.com/2026-09-24/102488599.html">汽车大整合“破冰”</a></p></li>
</ul></div>
<!-- 新闻主体 begin -->
<div class="news_list">
  <dl><dt><img data-src='https://img.caixin.com/2026-09-30/179077070853020_266_177.jpg'></dt>
  <dd><p><a href='https://international.caixin.com/2026-09-30/102490147.html'>迪拜航空航班急降沙特无人员死亡</a></p>
  <span>文｜财新 路尘 09月30日 19:59</span></dd></dl>
  <div class="index-ad-o"><a href="https://ads.caixin.com/xxx"><img src="https://img.caixin.com/ad.jpg"></a></div>
  <div class="news_img_box"><div class="tit"><p><a href="https://photos.caixin.com/2026-09-30/102490100.html">
  图集：现场直击</a></p></div><span>09月30日 11:00</span><ul><img src="https://img.caixin.com/pic1.jpg"></ul></div>
  <dl><dt><img data-src='https://img.caixin.com/dup.jpg'></dt>
  <dd><p><a href='https://weekly.caixin.com/2026-09-26/102488802.html'>最新财新周刊｜绿氢“十五五”新动能</a></p>
  <span>文｜财新周刊 卢羽桐 09月30日 15:20</span></dd></dl>
</div>
</body></html>
"""

_WORLD_PAGE = """
<html><body>
<div class="topNews"><div class="pic"><a href="https://international.caixin.com/2026-09-30/102490005.html">
<img src="https://img.caixin.com/2026-09-30/179075804381771_840_560.jpg"></a></div>
<div class="txt"><h3><a href="https://international.caixin.com/2026-09-30/102490005.html">朝鲜副外相联大自我宣告已为“拥核国家”</a></h3>
<span>2026年09月30日 17:03</span><p>朝鲜外务省同时发布备忘录。</p></div></div>
<div id="container_0"><div id="listArticle">
<div class="boxa"><div class="pic"><a href="https://international.caixin.com/2026-09-30/102490147.html">
<img data-src="https://img.caixin.com/2026-09-30/179077070853020_145_97.jpg"></a></div>
<h4><a href="https://international.caixin.com/2026-09-30/102490147.html">迪拜航空航班急降沙特无人员死亡</a></h4>
<span>文｜财新 路尘 2026年09月30日 19:59</span><p>有报道称，发动袭击的副驾驶来自阿曼。</p></div>
<div class="boxa"><div class="pic"><a href="https://topics.caixin.com/2026-09-29/102489669.html">
<img data-src="https://img.caixin.com/2026-09-29/179067598448376_145_97.jpg"></a></div>
<h4><a href="https://topics.caixin.com/2026-09-29/102489669.html">中国驻新加坡大使曹忠明致辞</a></h4>
<span>2026年09月29日 10:00</span><p>韧性不是不变，而是承压应变。</p></div>
</div></div>
</body></html>
"""

_CAIJING_PAGE = """
<html><body><div class="main_lt"><ul class="list">
<li><div class="wzbt"><a href="http://yuanchuang.caijing.com.cn/2026/0929/5186241.shtml">解禁潮下，谁在卖出GPU四小龙？</a></div>
<div class="time">2026年09月29日</div><div class="author"></div><div class="subtitle"></div></li>
<li><div class="wzbt"><a href="http://yuanchuang.caijing.com.cn/2026/0928/5186100.shtml">京沪率先落实商品房现售制</a></div>
<div class="time"></div><div class="author">记者 张三</div><div class="subtitle">摘要文字</div></li>
</ul></div></body></html>
"""


def _request(board_type: str) -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/caixin-caijing",
        "query_string": f"type={board_type}".encode(),
        "headers": [],
    })


def _page(html: str, date: str = _HOME_DATE, age: str = "0") -> dict:
    """origin_info=True 时共享 get 返回的包装结构。"""
    return {"data": html, "status": 200, "headers": {"date": date, "age": age}}


def _ok(data: Any) -> RequestResult:
    return RequestResult(False, "2026-09-30T12:00:00+00:00", data)


async def test_scroll_board_maps_fields_and_request(monkeypatch):
    captured: dict[str, Any] = {}

    async def fake_get(**kwargs):
        captured.update(kwargs)
        return _ok(dict(_SCROLL_PAYLOAD))

    monkeypatch.setattr(caixin_caijing, "get", fake_get)
    result = await caixin_caijing.handle_route(_request("caixin-latest"), no_cache=True)

    assert captured["url"] == (
        "https://gateway.caixin.com/api/dataplatform/scroll/index?page=1&size=20&date=&channel=0"
    )
    assert captured["headers"]["User-Agent"].startswith("Mozilla/5.0")  # 项目缺省 httpx UA 不用于网关
    assert result.type == "财新网 · 最新文章"
    assert result.total == 2
    first = result.data[0]
    assert first.id == "102490147"  # contentId
    assert first.title == "迪拜航空航班急降沙特无人员死亡 飞行员被指袭击同僚欲造空难"
    assert first.url == "https://international.caixin.com/2026-09-30/102490147.html"
    assert first.author == "财新 路尘"  # 去掉"文｜"
    assert first.timestamp == 1790769598000  # 接口毫秒原样
    second = result.data[1]
    assert second.author is None and second.cover is None and second.timestamp is None


async def test_scroll_rejects_error_shell(monkeypatch):
    async def fake_get(**kwargs):
        return _ok({"code": -1, "msg": "forbidden", "data": {}})

    monkeypatch.setattr(caixin_caijing, "get", fake_get)
    with pytest.raises(RuntimeError, match="unexpected payload"):
        await caixin_caijing.handle_route(_request("caixin-latest"), no_cache=True)


async def test_subject_board_parses_jsonp_and_request(monkeypatch):
    captured: dict[str, Any] = {}

    async def fake_get(**kwargs):
        captured.update(kwargs)
        return _ok(_SUBJECT_JSONP)

    monkeypatch.setattr(caixin_caijing, "get", fake_get)
    result = await caixin_caijing.handle_route(_request("caixin-china"), no_cache=True)

    assert "subject=100300241" in captured["url"]
    assert "type=0" in captured["url"] and "count=25" in captured["url"] and "start=0" in captured["url"]
    assert "picdim=_266_177" in captured["url"]
    assert captured["headers"]["Referer"] == "https://china.caixin.com/news/"
    assert result.type == "财新网 · 政经频道要闻"
    first = result.data[0]
    assert first.id == "102489757"  # nid
    assert first.title == "证监会：进一步优化沪深港通机制"  # 接口 desc 是标题
    assert first.author == "财新 王晶"  # edit.name 清理"文｜"
    assert first.desc == "进一步优化沪深港通机制。"
    assert first.cover == "https://img.caixin.com/2026-09-29/179068664446832_266_177.jpg"
    expected = int(datetime(2026, 9, 29, 8, 0, 0, tzinfo=_BEIJING).timestamp() * 1000)
    assert first.timestamp == expected  # 北京时间 → 毫秒
    assert result.data[1].id == "102489600"


async def test_subject_empty_response_raises_with_ua_hint(monkeypatch):
    async def fake_get(**kwargs):
        return _ok("")  # homeInterface 对 python-httpx 缺省 UA 返回 200 空响应

    monkeypatch.setattr(caixin_caijing, "get", fake_get)
    with pytest.raises(RuntimeError, match="User-Agent"):
        await caixin_caijing.handle_route(_request("caixin-finance"), no_cache=True)


async def test_home_parses_three_blocks_skips_ads_and_dedupes(monkeypatch):
    captured: dict[str, Any] = {}

    async def fake_get(**kwargs):
        captured.update(kwargs)
        return _ok(_page(_HOME_PAGE))

    monkeypatch.setattr(caixin_caijing, "get", fake_get)
    result = await caixin_caijing.handle_route(_request("caixin-home"), no_cache=True)

    assert captured["url"] == "https://www.caixin.com/"
    ids = [item.id for item in result.data]
    # 专题入口图(topics 落地页)与广告位 index-ad-o 不算条目;周刊文章 id 在头条区已出现,去重
    assert "102488802" in ids and ids.count("102488802") == 1
    assert all(item.id != "102487443" or item.title.startswith("视线｜") for item in result.data)  # 轮播条目保留
    assert len([i for i in ids if i == "102488802"]) == 1
    assert "ad" not in " ".join(item.url for item in result.data)

    first = result.data[0]  # 头条区左栏
    assert first.id == "102488802"
    assert first.title == "最新财新周刊｜绿氢“十五五”新动能"
    assert first.author == "财新周刊 卢羽桐"
    expected = int(datetime(2026, 9, 30, 15, 20, tzinfo=_BEIJING).timestamp() * 1000)
    assert first.timestamp == expected  # "09月30日 15:20" 以响应 Date 头补年份
    kicker = next(item for item in result.data if item.id == "102488599")  # 图片列表头条
    assert kicker.title == "汽车大整合“破冰”"  # p a 是标题
    assert kicker.desc == "最新封面报道"  # em 小标进 desc
    assert kicker.timestamp is None  # 图片列表头条没有时间
    carousel = next(item for item in result.data if item.id == "102487443")  # 轮播图集
    assert carousel.cover == "https://img.caixin.com//2026-09-22/179006156846643.jpg"
    assert carousel.timestamp is None and carousel.author is None
    gallery = next(item for item in result.data if item.id == "102490100")  # 新闻主体图集
    assert gallery.title == "图集：现场直击"
    assert gallery.cover == "https://img.caixin.com/pic1.jpg"


async def test_world_parses_topnews_then_boxa(monkeypatch):
    async def fake_get(**kwargs):
        assert kwargs["url"] == "https://international.caixin.com/"
        return _ok(_page(_WORLD_PAGE))

    monkeypatch.setattr(caixin_caijing, "get", fake_get)
    result = await caixin_caijing.handle_route(_request("caixin-world"), no_cache=True)

    assert result.type == "财新网 · 国际新闻世界频道"
    assert result.total == 3
    top = result.data[0]  # 头条区在前
    assert top.id == "102490005"
    assert top.author is None  # 头条区只有时间、没有署名
    assert top.desc == "朝鲜外务省同时发布备忘录。"
    expected = int(datetime(2026, 9, 30, 17, 3, tzinfo=_BEIJING).timestamp() * 1000)
    assert top.timestamp == expected
    second = result.data[1]
    assert second.id == "102490147"
    assert second.author == "财新 路尘"  # span 里时间之前的署名
    assert second.timestamp == int(datetime(2026, 9, 30, 19, 59, tzinfo=_BEIJING).timestamp() * 1000)
    third = result.data[2]
    assert third.id == "102489669"  # topics 频道下的文章页也算条目
    assert third.timestamp == int(datetime(2026, 9, 29, 10, 0, tzinfo=_BEIJING).timestamp() * 1000)


async def test_caijing_selected_maps_fields_keeps_http_url(monkeypatch):
    async def fake_get(**kwargs):
        assert kwargs["url"] == "https://yuanchuang.caijing.com.cn/"
        return _ok(_page(_CAIJING_PAGE))

    monkeypatch.setattr(caixin_caijing, "get", fake_get)
    result = await caixin_caijing.handle_route(_request("caijing-selected"), no_cache=True)

    assert result.type == "财经网 · 财经精选"
    first = result.data[0]
    assert first.id == "5186241"
    assert first.title == "解禁潮下，谁在卖出GPU四小龙？"
    assert first.url == "http://yuanchuang.caijing.com.cn/2026/0929/5186241.shtml"  # 原站 http 照原样
    expected = int(datetime(2026, 9, 29, 0, 0, tzinfo=_BEIJING).timestamp() * 1000)  # 日期 → 北京时间 0 点
    assert first.timestamp == expected
    second = result.data[1]
    assert second.timestamp == int(datetime(2026, 9, 28, 0, 0, tzinfo=_BEIJING).timestamp() * 1000)  # div.time 缺失取链接日期
    assert second.desc == "摘要文字"


async def test_unknown_board_is_rejected():
    with pytest.raises(ValueError, match="Unknown board"):
        await caixin_caijing.handle_route(_request("nonsense"), no_cache=True)


async def test_empty_home_parse_is_an_error(monkeypatch):
    async def fake_get(**kwargs):
        return _ok(_page("<html><body>维护中</body></html>"))

    monkeypatch.setattr(caixin_caijing, "get", fake_get)
    with pytest.raises(RuntimeError, match="news_list|parsed no items"):
        await caixin_caijing.handle_route(_request("caixin-home"), no_cache=True)
