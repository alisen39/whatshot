"""security-communities 路由测试：mock 共享 get，fixtures 依 board_api 证据结构净化内联。

证据来源：tmp/board_api/security_communities/evidence/
（01_52pojie_home、02_52pojie_ranklist、03_52pojie_forum2、07_xz_ajax_recommend、
20_xz_feed_0930、10_freebuf_api_latest、14_secrss_api_articles）。
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timezone

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import security_communities as route
from whats_hot_api.utils.http_client import RequestResult

_UPDATE_TIME = "2026-10-01T00:00:00+00:00"
_BEIJING = timezone(__import__("datetime").timedelta(hours=8))


def _request(board_type: str) -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/security-communities",
            "query_string": f"type={board_type}".encode(),
            "headers": [],
        }
    )


def _fake_get(body, captured: dict | None = None):
    async def handler(url, headers=None, params=None, no_cache=None, **kwargs):
        if captured is not None:
            captured.update({"url": url, "headers": headers, "params": params, "no_cache": no_cache, "kwargs": kwargs})
        return RequestResult(False, _UPDATE_TIME, body)

    return handler


def _ms(value: str) -> int:
    return int(datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=_BEIJING).timestamp() * 1000)


# ---------------------------------------------------------------- 吾爱破解


_POJIE_TOPLIST = """
<table cellspacing="0" cellpadding="0" width="100%" class="toplist_7ree">
 <tr class="toptitle_7ree">
  <td><a href="forum.php?mod=guide&amp;view=newthread"><strong>新鲜出炉（更多）</strong></a></td>
  <td><a href="forum.php?mod=guide&amp;view=hot"><strong>人气热门（更多 New~）</strong></a></td>
 </tr>
 <tr class="fl_row">
  <td><div class="threadline_7ree"><a href="thread-2130001-1-1.html" tips="<strong>新鲜出炉标题</strong><br>版块：『精品软件区』<br>作者：甲<br>时间：2026-09-28 07:50:30<br>">新鲜出炉标题</a></div></td>
  <td>
   <div class="threadline_7ree"><a href="thread-2129531-1-1.html" tips="<strong>抖音.B站视频无水印高清画质下载器 v1.3.0</strong><br>版块：『精品软件区』<br>作者：快乐哈哈<br>时间：2026-09-26 08:22:10<br>">抖音.B站视频无水印高清画质下载器 …</a></div>
   <div class="threadline_7ree"><a href="thread-2129500-1-1.html">短标题</a></div>
  </td>
 </tr>
</table>
"""


@pytest.mark.asyncio
async def test_52pojie_hot_maps_toplist_column_and_tips(monkeypatch):
    captured: dict = {}
    monkeypatch.setattr(route, "get", _fake_get(_POJIE_TOPLIST, captured))
    result = await route.handle_route(_request("52pojie-hot"), no_cache=True)

    assert captured["url"] == "https://www.52pojie.cn/"
    assert captured["kwargs"]["response_type"] == "arraybuffer"  # GBK 页面自己解码
    assert captured["no_cache"] is True
    first = result.data[0]
    assert first.id == "2129531"
    assert first.title == "抖音.B站视频无水印高清画质下载器 v1.3.0"  # 完整标题取 tips 的 <strong>
    assert first.url == "https://www.52pojie.cn/thread-2129531-1-1.html"
    assert first.author == "快乐哈哈"
    assert first.desc == "『精品软件区』"
    assert first.hot is None  # 首页人气热门列不显示数字
    assert first.timestamp == _ms("2026-09-26 08:22:10")
    assert len(result.data) == 2  # 只取「人气热门」列，新鲜出炉列不算


_POJIE_RANKLIST = """
<div class="tl">
<table cellspacing="0" cellpadding="0">
<tr class="th"><th>标题</th><td>热度</td></tr>
<tr>
 <th><a href="forum.php?mod=viewthread&amp;tid=2130111&amp;extra=">稻壳阅读器DocBox 2.10.10 高清打印不糊修复版</a></th>
 <td class="frm"><a>『原创发布区』</a></td>
 <td class="by"><cite><a href="space-uid-1.html">作者乙</a></cite><em><span title="2026-9-30 09:10">5&nbsp;小时前</span></em></td>
 <td><a>127</a></td>
</tr>
</table>
</div>
"""


@pytest.mark.asyncio
async def test_52pojie_today_heats_maps_ranklist(monkeypatch):
    captured: dict = {}
    monkeypatch.setattr(route, "get", _fake_get(_POJIE_RANKLIST, captured))
    result = await route.handle_route(_request("52pojie-today-heats"), no_cache=True)

    assert captured["url"].endswith("misc.php?mod=ranklist&type=thread&view=heats&orderby=today")
    item = result.data[0]
    assert item.id == "2130111"  # tid，不是名次
    assert item.url == "https://www.52pojie.cn/thread-2130111-1-1.html"  # viewthread 链接统一成 thread- 形式
    assert item.hot == 127  # 排行「热度」列
    assert item.author == "作者乙"
    assert item.desc == "『原创发布区』"
    assert item.timestamp == _ms("2026-09-30 09:10:00")  # 相对显示取 span[title] 里的完整时间


_POJIE_FORUM = """
<tbody id="stickthread_2099000">
 <tr>
  <th><a href="forum.php?mod=viewthread&amp;tid=2099000&amp;extra=" class="xst">【公告】精品软件区版规完整版</a></th>
  <td class="by"><cite><a>管理组</a></cite><em><span title="2024-1-02 10:00">2024-1-02</span></em></td>
  <td class="num"><em>88321</em></td>
 </tr>
</tbody>
<tbody id="normalthread_2130200">
 <tr>
  <th><a href="thread-2130200-1-1.html" class="xst">7-zip-crypto 压缩软件 v26.03 加密算法增强版</a></th>
  <td class="by"><cite><a>作者丙</a></cite><em>2026-9-30 08:30</em></td>
  <td class="num"><em>1520</em></td>
 </tr>
</tbody>
"""


@pytest.mark.asyncio
async def test_52pojie_forum_threadlist_keeps_sticky_order(monkeypatch):
    captured: dict = {}
    monkeypatch.setattr(route, "get", _fake_get(_POJIE_FORUM, captured))
    result = await route.handle_route(_request("52pojie-software"), no_cache=True)

    assert captured["url"].endswith("forum.php?mod=forumdisplay&fid=16&filter=author&orderby=dateline")
    assert [item.id for item in result.data] == ["2099000", "2130200"]  # 置顶在前，照页面顺序
    assert result.data[0].desc == "置顶"
    assert result.data[0].hot == 88321  # 版块页 hot 取查看数
    assert result.data[0].timestamp == _ms("2024-01-02 10:00:00")
    assert result.data[1].desc is None
    assert result.data[1].timestamp == _ms("2026-09-30 08:30:00")


@pytest.mark.asyncio
async def test_52pojie_waf_slider_page_is_rejected_without_retry(monkeypatch):
    # 分析阶段拿到的 wzws 滑块页：引用 /wzws-waf-cgi/jquery.js、div.slidercaptcha（结构照证据，无 cookie）
    slider = '<html><head><script src="/wzws-waf-cgi/jquery.js"></script></head><body><div class="slidercaptcha">请完成安全验证!</div></body></html>'
    monkeypatch.setattr(route, "get", _fake_get(slider.encode("utf-8")))
    with pytest.raises(RuntimeError, match="WAF slider"):
        await route.handle_route(_request("52pojie-hot"), no_cache=True)


@pytest.mark.asyncio
async def test_52pojie_missing_toplist_column_is_an_error(monkeypatch):
    html = '<table class="toplist_7ree"><tr class="toptitle_7ree"><td><strong>新鲜出炉（更多）</strong></td></tr><tr class="fl_row"><td></td></tr></table>'
    monkeypatch.setattr(route, "get", _fake_get(html))
    with pytest.raises(RuntimeError, match="人气热门"):
        await route.handle_route(_request("52pojie-hot"), no_cache=True)


# ---------------------------------------------------------------- 先知社区


_XZ_FEED = """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
    <title>先知安全技术社区</title>
    <updated>2026-09-30T14:18:27+00:00</updated>
    <entry>
        <title>从 ZCode Trust Folder Bypass 0day 漏洞看 Coding Agent 的 Trust Folder 安全问题</title>
        <link href="https://xz.aliyun.com/news/92897" rel="alternate"></link>
        <published>2026-09-29 06:52:18</published>
        <updated>2026-09-30 14:17:57</updated>
        <id>https://xz.aliyun.com/news/92897</id>
        <summary type="html">算是一个 ZCode 都 0day</summary>
    </entry>
    <entry>
        <title>编码斜杠击穿 Go 路由器</title>
        <link href="https://xz.aliyun.com/news/92894" rel="alternate"></link>
        <published>2026-09-28 07:24:17</published>
        <id>https://xz.aliyun.com/news/92894</id>
        <summary type="html">ServeMux 双视图解析</summary>
    </entry>
</feed>
"""


@pytest.mark.asyncio
async def test_xz_latest_keeps_feed_order_and_utc_time(monkeypatch):
    captured: dict = {}
    monkeypatch.setattr(route, "get", _fake_get(_XZ_FEED, captured))
    result = await route.handle_route(_request("xz-latest"), no_cache=True)

    assert captured["url"] == "https://xz.aliyun.com/feed"
    # feed 按 id 倒序，与发布时间序不同（92894 发布更早但在第 2 位），照 feed 原顺序输出
    assert [item.id for item in result.data] == ["92897", "92894"]
    first = result.data[0]
    assert first.url == "https://xz.aliyun.com/news/92897"
    assert first.desc == "算是一个 ZCode 都 0day"
    assert first.hot is None and first.author is None  # feed 没有 hot / author
    # published 是不带时区的 UTC：2026-09-29 06:52:18 UTC
    utc = datetime(2026, 9, 29, 6, 52, 18, tzinfo=UTC)
    assert first.timestamp == int(utc.timestamp() * 1000)


_XZ_RECOMMEND_FRAGMENT = """
<div class="news_item">
  <div class="news_img"><a href="https://xz.aliyun.com/news/92860">
    <img alt="封面" src="https://xz.aliyun.com/api/v2/files/abc?w=217"></a></div>
  <div class="news_word">
    <a class="news_title" href="https://xz.aliyun.com/news/92860">三条超线性路径与一个参数上限</a>
    <p>地址解析层中存在三条相互独立的超线性性能路径。</p>
    <div class="news_bm">
      <a class="cates_span" href="https://xz.aliyun.com/news?cate_id=2">漏洞分析</a>
      <a class="user-info" href="https://xz.aliyun.com/users/129140"><span>北斗</span><span>发表于 山东</span></a>
      · 2422浏览 · 2026-09-20 03:08
    </div>
  </div>
</div>
"""


@pytest.mark.asyncio
async def test_xz_recommend_parses_ajax_fragment(monkeypatch):
    captured: dict = {}
    envelope = json.dumps({"status": True, "after": 1, "data": _XZ_RECOMMEND_FRAGMENT, "count": 5}, ensure_ascii=False)
    monkeypatch.setattr(route, "get", _fake_get(envelope, captured))
    result = await route.handle_route(_request("xz-recommend"), no_cache=True)

    assert captured["url"] == "https://xz.aliyun.com/news"
    assert captured["params"] == {"isAjax": "true", "type": "recommend"}
    assert captured["headers"]["X-Requested-With"] == "XMLHttpRequest"  # 缺了返回整页 HTML
    item = result.data[0]
    assert item.id == "92860"
    assert item.title == "三条超线性路径与一个参数上限"
    assert item.author == "北斗"  # user-info 的第一个 span 是昵称（第二个是"发表于 山东"）
    assert item.hot == 2422  # 「N浏览」
    assert item.cover == "https://xz.aliyun.com/api/v2/files/abc?w=217"
    assert item.desc == "地址解析层中存在三条相互独立的超线性性能路径。"
    # 片段时间与 feed 一样是不带时区的 UTC
    utc = datetime(2026, 9, 20, 3, 8, tzinfo=UTC)
    assert item.timestamp == int(utc.timestamp() * 1000)


@pytest.mark.asyncio
async def test_xz_ajax_without_xhr_returns_full_page_and_is_rejected(monkeypatch):
    # 缺 X-Requested-With 时返回的是整页 HTML（44268 字节），不是 JSON 信封
    monkeypatch.setattr(route, "get", _fake_get("<!DOCTYPE html><html><body>整页</body></html>"))
    with pytest.raises(RuntimeError, match="did not return JSON"):
        await route.handle_route(_request("xz-recommend"), no_cache=True)


# ---------------------------------------------------------------- FreeBuf


_FREEBUF_PAYLOAD = {
    "code": 200,
    "msg": "成功",
    "data": {
        "count": 26937,
        "list": [
            {
                "ID": "502450",
                "post_title": "当 Agent 成为入口：AI Agent 系统攻击面深度测绘",
                "url": "/articles/ai-security/502450.html",
                "post_date": "2026-09-28 08:00:00",
                "read_count": 3413,
                "nickname": "kkkkkkkkk12",
                "username": "kkkkkkkkk12",
                "content": "本文将以一个典型的企业 AI 客服 Agent 为目标。",
                "post_image": "https://image.3001.net/images/20260922/a.png",
            }
        ],
    },
}


@pytest.mark.asyncio
async def test_freebuf_weekly_hot_uses_type2_day7(monkeypatch):
    captured: dict = {}
    monkeypatch.setattr(route, "get", _fake_get(json.dumps(_FREEBUF_PAYLOAD, ensure_ascii=False), captured))
    result = await route.handle_route(_request("freebuf-weekly-hot"), no_cache=True)

    assert captured["url"] == "https://www.freebuf.com/fapi/frontend/home/article"
    assert captured["params"]["type"] == 2
    assert captured["params"]["day"] == 7  # 热榜 7 天窗口
    assert captured["params"]["category"] == "精选"
    assert captured["headers"]["User-Agent"].startswith("Mozilla/5.0")  # 程序 UA 会被阿里云 WAF 拦
    assert captured["headers"]["Referer"] == "https://www.freebuf.com/"
    item = result.data[0]
    assert item.id == "502450"
    assert item.title == "当 Agent 成为入口：AI Agent 系统攻击面深度测绘"
    assert item.url == "https://www.freebuf.com/articles/ai-security/502450.html"  # 相对路径拼域名
    assert item.hot == 3413
    assert item.author == "kkkkkkkkk12"
    assert item.timestamp == _ms("2026-09-28 08:00:00")


@pytest.mark.asyncio
async def test_freebuf_waf_challenge_and_business_error_are_rejected(monkeypatch):
    waf_page = '<!doctype html><meta name="aliyun_waf_aa" content="ff9267a8a12c601c6ae545d5ca4a7fb4">'
    monkeypatch.setattr(route, "get", _fake_get(waf_page))
    with pytest.raises(RuntimeError, match="aliyun WAF"):
        await route.handle_route(_request("freebuf-latest"), no_cache=True)

    monkeypatch.setattr(route, "get", _fake_get(json.dumps({"code": 401, "msg": "unauthorized"})))
    with pytest.raises(RuntimeError, match="code=401"):
        await route.handle_route(_request("freebuf-latest"), no_cache=True)


# ---------------------------------------------------------------- 安全内参


_SECRSS_PAYLOAD = {
    "code": "10000",
    "msg": "操作成功",
    "data": [
        {
            "id": 94320,
            "title": "赢得以色列情报精英青睐的神秘网络武器公司Dataflow",
            "author": "黑鸟",
            "published_at": "2026-09-26 23:51:09",
            "hit_num": 912,
            "summary": "Dataflow 由一名年轻黑客在意大利创立。",
            "thumb_image_url": "https://s.secrss.com/anquanneican/ab.jpg!m",
        }
    ],
}


@pytest.mark.asyncio
async def test_secrss_maps_first_screen_articles(monkeypatch):
    captured: dict = {}
    monkeypatch.setattr(route, "get", _fake_get(json.dumps(_SECRSS_PAYLOAD, ensure_ascii=False), captured))
    result = await route.handle_route(_request("secrss-latest"), no_cache=True)

    assert captured["url"] == "https://www.secrss.com/api/articles"
    assert captured["params"] == {"referer": "web"}  # 首屏不带 lastPublishedAt 游标
    item = result.data[0]
    assert item.id == "94320"
    assert item.url == "https://www.secrss.com/articles/94320"
    assert item.author == "黑鸟"
    assert item.desc == "Dataflow 由一名年轻黑客在意大利创立。"
    assert item.hot == 912
    assert item.cover == "https://s.secrss.com/anquanneican/ab.jpg!m"
    assert item.timestamp == _ms("2026-09-26 23:51:09")


@pytest.mark.asyncio
async def test_secrss_business_shell_is_rejected(monkeypatch):
    monkeypatch.setattr(route, "get", _fake_get(json.dumps({"code": "10001", "msg": "error"})))
    with pytest.raises(RuntimeError, match="code=10001"):
        await route.handle_route(_request("secrss-latest"), no_cache=True)


# ---------------------------------------------------------------- 入口


@pytest.mark.asyncio
async def test_unknown_board_is_rejected():
    with pytest.raises(ValueError, match="Unknown board 'kanxue-latest'"):
        await route.handle_route(_request("kanxue-latest"), no_cache=True)


def test_type_map_declares_all_boards():
    assert len(route._TYPE_MAP) == 9
    assert next(iter(route._TYPE_MAP)) == "52pojie-hot"  # 声明序第一个是默认榜
    assert route.ROUTE_META["params"]["type"]["type"] is route._TYPE_MAP
