"""politics-media 路由测试:fixtures 依据 board_api 证据目录 tmp/board_api/politics_media 净化。

- 观察者网首页/时评/国际栏目:evidence/01_guancha_*(轮播重复组、li.middle、tsp-list、column-list)
- 环球网:evidence/02_huanqiu_channel_pc、02_huanqiu_api_list(channel_pc 节点 → api/list)
- 参考消息:evidence/03_cankaoxiaoxi_yaowen_list(list[].data)
- 凤凰热榜:evidence/04_ifeng_hotnewsrank(var allData = {…})
- 中国新闻周刊:evidence/05_inewsweek_home(GBK;top10 li、grid-item)
- China Daily:evidence/06_chinadaily_*(电子版 newslist-*、频道 tw3_01_2)
- 央广网:evidence/07_cnr_kuaixun(GBK;?sign= 预览参数)
- 中国科技网 / 南风窗 / 求是:evidence/08_stdaily_node_324、09_nfcmag_home、10_qstheory_*
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import politics_media
from whats_hot_api.utils.http_client import RequestResult

_BEIJING = timezone(timedelta(hours=8))
_UPDATE_TIME = "2026-09-28T00:00:00+00:00"


def _request(board_type: str | None = None) -> Request:
    query = f"type={board_type}" if board_type else ""
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/politics-media",
        "query_string": query.encode(),
        "headers": [],
    })


def _ok(data: Any) -> RequestResult:
    return RequestResult(False, _UPDATE_TIME, data)


def _ms(*args: int) -> int:
    return int(datetime(*args, tzinfo=_BEIJING).timestamp() * 1000)


# 观察者网首页:轮播(同一组链接重复 3 份)+ 中栏 li.middle(含配图/作者/阅读数)+ 头条
_GUANCHA_HOME = """<html><body>
<div class="content-topnews-box-neo-box">
<a href="/ZhengZhi/2026_09_27_902423.shtml">视频画报|习近平主席的华盛顿时间</a>
<a href="/ZhengZhi/2026_09_27_902426.shtml">良法善治·回响|何以"跟进一步"</a>
</div>
<div class="content-topnews-box-neo-box">
<a href="/ZhengZhi/2026_09_27_902423.shtml">视频画报|习近平主席的华盛顿时间</a>
<a href="/ZhengZhi/2026_09_27_902426.shtml">良法善治·回响|何以"跟进一步"</a>
</div>
<li class="middle"><ul class="img-List">
<li><h4 class="module-title"><a href="/GuoJi·ZhanLue/2026_09_27_902427.shtml">中国第六座南极站,引来澳大利亚乱猜</a></h4>
<div class="fastRead-img"><a href="/GuoJi·ZhanLue/2026_09_27_902427.shtml"><img data-original="https://i.guancha.cn/news/a.jpg"></a></div>
<div class="module-interact"><span class="module-interact-creator">周砚之</span>
<a data-sensor="阅读数">阅读 30892</a></div></li>
<li><h4 class="module-title"><a href="/GuoJi·ZhanLue/2026_09_27_902428.shtml">第二条要闻</a></h4></li>
</ul></li>
<div class="content-headline">
<h3><a href="/GuoJi·ZhanLue/2026_09_27_902413.shtml">无视美国制裁,尼加拉瓜正大量向中企出售黄金矿权</a></h3>
<a data-sensor="图片"><img src="https://i.guancha.cn/news/b.jpg"></a>
<div class="module-interact"><span class="module-interact-creator">周砚之</span>
<a data-sensor="阅读数">阅读 60761</a></div>
</div>
</body></html>
"""

# 观察者网时评页:头条 + 热点热评(末尾 span 是发布时间)
_GUANCHA_SP = """<html><body>
<div class="tsp-list1"><a class="tsp-list1-title" href="/WangShiChun/2026_09_27_902379.shtml">一周军评:大海属于中国人</a>
<img class="tsp-list1-pic" src="https://i.guancha.cn/news/c.jpg">
<div class="tsp-list1-name">王世纯</div></div>
<ul class="tsp-list2-list">
<li><a class="tsp-list2-title" href="/XiJinPing/2023_02_17_680194.shtml">当前经济工作的几个重大问题</a>
<div class="tsp-list2-name">习近平</div>
<div class="tsp-list2-content">总需求不足是当前经济运行面临的突出矛盾。</div>
<div class="tsp-list2-review"><span>阅读数 206242</span><span>2023-02-17 08:00</span></div></li>
<li><a class="tsp-list2-title" href="/GuoJi·ZhanLue/2026_09_27_902431.shtml">新的时评</a></li>
</ul></body></html>
"""

# 观察者网国际栏目列表第 1 页(ul class 是 "column-list fix")
_GUANCHA_INTL = """<html><body><ul class="column-list fix" data-total="300">
<li><h4 class="module-title"><a href="/GuoJi·ZhanLue/2026_09_27_902431.shtml">"特朗普认为他能等"</a></h4>
<p class="module-artile">导语正文。<a href="/GuoJi·ZhanLue/2026_09_27_902431.shtml">[全文]</a></p>
<div class="module-interact"><span>2026-09-27 22:09</span></div></li>
<li><h4 class="module-title"><a href="/GuoJi·ZhanLue/2026_09_27_902430.shtml">第二条国际新闻</a></h4>
<div class="module-interact"><span>2026-09-27 22:03</span></div></li>
</ul></body></html>
"""

# 环球网 api/channel_pc(根节点下栏目)与 api/list(末尾空对象)
_HUANQIU_CHANNEL = {
    "children": {
        "/e3pmh22ph": {
            "node": "/e3pmh22ph",
            "children": {
                "/e3pmh22ph/e3pmh2398": {"node": "/e3pmh22ph/e3pmh2398"},
                "/e3pmh22ph/e3pmh26vv": {"node": "/e3pmh22ph/e3pmh26vv"},
            },
        }
    }
}
_HUANQIU_LIST = {
    "list": [
        {"aid": "4TNv5to6eSF", "title": "亚运会羽球女单开打", "summary": "比赛时间不断推迟。",
         "addltype": "normal", "ctime": "1790521556447",
         "cover": "//img.huanqiucdn.cn/dp/api/files/a.png", "host": "world.huanqiu.com"},
        {"aid": "4TNrj1nxgfP", "title": "环视图集", "addltype": "gallery", "ctime": "",
         "host": "world.huanqiu.com"},
        {},
    ]
}

# 参考消息 yaowen/list.json(list[].data)
_CKXX_LIST = {
    "list": [
        {"data": {"id": "5e34ce019e244d398ed22db1760cb51d", "title": "伊朗在联合国发起外交攻势",
                  "url": "https://ckxxapp.ckxx.net/pages/2026/09/27/5e34.html",
                  "mCoverImg": "https://ckxxapp.ckxx.net/upload/a.jpg", "author": "参考消息",
                  "description": "伊朗发起外交攻势。", "publishTime": "2026-09-27 20:54:04"}},
        {"data": {"id": "abc", "title": "无日期条目", "url": "https://ckxxapp.ckxx.net/pages/b.html",
                  "mCoverImg": "", "author": "", "description": ""}},
    ]
}

# 凤凰热榜页内嵌 allData
_IFENG_ALLDATA = (
    '<html><script>var config = {};</script>\n'
    '<script>var allData = {"content": {"list": ['
    '{"documentId": "doc_1", "title": "凤凰热榜第一条", '
    '"link": {"weburl": "https://ishare.ifeng.com/c/s/abc"}, '
    '"thumbnail": "//p0.ifengimg.com/a.jpg", "hotLabel": {"hotGrade": "297万热度"}},'
    '{"id": "doc_2", "title": "无热度条目", "link": {"weburl": "https://ishare.ifeng.com/c/s/def"}, "hotLabel": {"hotGrade": ""}}'
    ']}};\n</script></html>'
)

# 中国新闻周刊首页(GBK):十大热文 li + 首页推荐 grid-item
_INEWSWEEK_TOP10 = """<html><body>
<div class="sin_top10_cont"><ul>
<li><a href="/finance/2026-09-24/32324.shtml"><img class="fl" src="/finance/a.jpeg">
<div class="sin_top10_txt fl"><h4>"发霉,还发出刺鼻异味",交个朋友翻车</h4></div></a></li>
<li><a href="//www.inewsweek.cn/people/2026-09-24/32323.shtml"><h4>第二条热文</h4></a></li>
</ul></div></body></html>
"""
_INEWSWEEK_REC = """<html><body>
<div class="grid"><div class="grid-item"><a href="//www.inewsweek.cn/world/2026-09-17/32168.shtml">
<img src="/world/b.jpeg"><div><p style="overflow: hidden;">英国要分裂了?</p></div></a></div>
<!-- <div class="grid-item ten_text">被注释掉的板块不算</div> -->
</div></body></html>
"""

# China Daily 报纸电子版(一天的全部版面)
_EPAPER_PAGE = """<html><body><div class="lft_art">
<div class="edition-name">CHINA-US SUMMIT</div>
<div class="newslist-bigtitle"><h2><a href="//epaper.chinadaily.com.cn/a/202609/26/WS6ab70bed.html">Xi: Turn Sino-US shared vision into action</a></h2>
<p>President Xi Jinping called on China and the United States.</p></div>
<div class="newslist-common"><a href="//epaper.chinadaily.com.cn/a/202609/26/WS6ab70bf0.html">Insights offered to push for steady ties</a></div>
</div></body></html>
"""
_EPAPER_EMPTY = "<html><body>当天版面还没有文章</body></html>"

# China Daily China 频道 Latest 列表
_CHINADAILY_CHINA_PAGE = """<html><body><div class="lft_art">
<div class="mb10 tw3_01_2"><span class="tw3_01_2_p">
<a href="//www.chinadaily.com.cn/a/202609/27/WS6ab938c3.html"><img src="//img2.chinadaily.com.cn/a.jpeg"></a></span>
<span class="tw3_01_2_t"><h4><a href="//www.chinadaily.com.cn/a/202609/27/WS6ab938c3.html">China shines at WorldSkills Shanghai 2026</a></h4>
<b>2026-09-27 23:39</b></span></div></div></body></html>
"""

# 央广网滚动(GBK,链接带 ?sign= TRS 预览参数)
_CNR_PAGE = (
    '<html><body><div class="articleList"><div class="item">'
    '<a href="https://www.cnr.cn/newscenter/kx/20260927/t20260927_527827128.shtml'
    '?sign=ABZ0cnNfd2NtX3ByZXZpZXdfYWNjZXNz"><span class="text kuaixun">'
    "<strong>41金11银4铜 中国创参加世界技能大赛最好成绩</strong>"
    "<em>第48届世界技能大赛于9月27日晚在上海闭幕。</em></span>"
    '<span class="publishTime">2026-09-27  22:23</span></a></div>'
    "<div class=\"item\"><a href='https://www.cnr.cn/newscenter/kx/b.shtml'>"
    "<strong>第二条快讯</strong></a></div>"
    "</div></body></html>"
).encode("gb18030")

# 中国科技网滚动
_STDAILY_PAGE = """<html><body><div class="f_lieb_list"><dl>
<h3><a href="https://www.stdaily.com/web/gdxw/2026-09/27/content_588826.html">活力中国调研行|智慧宫原来真是一座"宫"</a></h3>
<dt><a href="https://www.stdaily.com/web/gdxw/2026-09/27/content_588826.html"><img src="https://www.stdaily.com/web/gdxw/pic/a.png"></a></dt>
<dd><div class="wenzi_box"><p>智慧宫的摘要。</p></div></dd>
<div class="sourthTime"><span>科技日报</span><span>2026-09-27 10:20</span></div>
</dl></div></body></html>
"""

# 南风窗首页(各栏目推荐块)
_NFCMAG_PAGE = """<html><body>
<div class="article-box comBox"><h4>区域</h4><ul>
<li class="d"><h5 class="title"><a href="/article/9546.html">东北,终于出了第一个万亿户</a></h5>
<p><a href="/article/9546.html">这是一座城的突围。</a></p></li>
<li class="d"><h5 class="title"><a href="/article/9502.html">迎来全球最大单体机场</a></h5></li>
</ul></div></body></html>
"""

# 求是网首页头条区(content 大标题 + more 相关链接指向同一篇,去重后 1 条)
_QSTHEORY_HOME = """<html><body>
<div class="headtitle"><div class="content"><a href="https://www.qstheory.cn/20260915/443b96d3/c.html">深度调研|新型能源体系调查</a></div>
<div class="more"><ul><li><a href="https://www.qstheory.cn/20260915/443b96d3/c.html">新型能源体系"新"在何处</a></li>
<li><a href="https://www.qstheory.cn/20260915/443b96d3/c.html">能源转型发展"难"在哪里</a></li></ul></div></div>
</body></html>
"""

# 求是往期数据文件 + 目录页(p 标题 /作者)
_QSTHEORY_DS = {
    "datasource": [
        {"title": "2026年第18期", "publishUrl": "/20260915/3ffd335483ab41a3a67f182fcfdb5c72/c.html"}
    ]
}
_QSTHEORY_TOC = """<html><body><div id="detailContent">
<p><img src="cover.jpg"></p>
<p><strong>目 录</strong></p>
<p><a href="https://www.qstheory.cn/20260915/0196377275f74e5e8a523a6d481dd793/c.html">本期导读</a></p>
<p><a href="https://www.qstheory.cn/20260915/aa/c.html">新型能源体系调查 /本刊评论员</a></p>
</div></body></html>
"""


def _route(board_type: str, responder: Any, monkeypatch) -> Any:
    captured: dict[str, Any] = {"urls": [], "kwargs": []}

    async def fake_get(url, **kwargs):
        captured["urls"].append(url)
        captured["kwargs"].append(kwargs)
        return responder(url)

    monkeypatch.setattr(politics_media, "get", fake_get)
    return captured


async def test_guancha_yaowen_maps_fields(monkeypatch):
    captured = _route("guancha-yaowen", lambda url: _ok(_GUANCHA_HOME), monkeypatch)
    result = await politics_media.handle_route(_request("guancha-yaowen"), no_cache=True)

    assert captured["urls"] == ["https://www.guancha.cn/"]
    assert result.type == "观察者网 · 要闻"
    assert result.total == 2
    first = result.data[0]
    assert first.id == "https://www.guancha.cn/GuoJi·ZhanLue/2026_09_27_902427.shtml"
    assert first.title == "中国第六座南极站,引来澳大利亚乱猜"
    assert first.cover == "https://i.guancha.cn/news/a.jpg"  # data-original 优先
    assert first.author == "周砚之"
    assert first.hot == 30892  # "阅读 30892"
    assert first.timestamp == _ms(2026, 9, 27)  # 文章地址里的日期,北京时间 0 点,毫秒
    assert result.data[1].hot is None


async def test_guancha_top_dedups_carousel_and_maps_headline(monkeypatch):
    _route("guancha-top", lambda url: _ok(_GUANCHA_HOME), monkeypatch)
    result = await politics_media.handle_route(_request("guancha-top"), no_cache=True)

    assert result.type == "观察者网 · 首页新闻"
    # 轮播同一组链接重复多份只留第一次(2 条)+ 头条 1 条
    assert [item.id for item in result.data] == [
        "https://www.guancha.cn/ZhengZhi/2026_09_27_902423.shtml",
        "https://www.guancha.cn/ZhengZhi/2026_09_27_902426.shtml",
        "https://www.guancha.cn/GuoJi·ZhanLue/2026_09_27_902413.shtml",
    ]
    head = result.data[-1]
    assert head.title == "无视美国制裁,尼加拉瓜正大量向中企出售黄金矿权"
    assert head.cover == "https://i.guancha.cn/news/b.jpg"
    assert head.hot == 60761


async def test_guancha_shiping_and_intl_use_page_time(monkeypatch):
    captured = _route(
        "guancha-shiping", lambda url: _ok(_GUANCHA_INTL if "column" in url else _GUANCHA_SP),
        monkeypatch,
    )
    result = await politics_media.handle_route(_request("guancha-shiping"), no_cache=True)
    assert captured["urls"] == ["https://www.guancha.cn/mainnews-sp/"]
    first = result.data[0]
    assert first.title == "一周军评:大海属于中国人"
    assert first.author == "王世纯"
    assert first.timestamp == _ms(2026, 9, 27)  # 头条取地址日期
    second = result.data[1]
    assert second.timestamp == _ms(2023, 2, 17, 8, 0)  # 热评取页面时间(置顶旧文)
    assert second.desc == "总需求不足是当前经济运行面临的突出矛盾。"

    result = await politics_media.handle_route(_request("guancha-intl"), no_cache=True)
    first = result.data[0]
    assert first.desc == "导语正文。"  # 导语末尾的"[全文]"链接已去掉
    assert first.timestamp == _ms(2026, 9, 27, 22, 9)


async def test_huanqiu_builds_node_query_and_maps_list(monkeypatch):
    captured = _route(
        "huanqiu-world",
        lambda url: _ok(_HUANQIU_CHANNEL if url.endswith("channel_pc") else _HUANQIU_LIST),
        monkeypatch,
    )
    result = await politics_media.handle_route(_request("huanqiu-world"), no_cache=True)

    assert captured["urls"][0] == "https://world.huanqiu.com/api/channel_pc"
    list_url = captured["urls"][1]
    assert list_url.startswith("https://world.huanqiu.com/api/list?node=")
    assert "%22/e3pmh22ph/e3pmh2398%22,%22/e3pmh22ph/e3pmh26vv%22" in list_url
    assert "offset=0&limit=24" in list_url
    assert captured["kwargs"][1]["headers"]["X-Requested-With"] == "XMLHttpRequest"
    assert captured["kwargs"][1]["cache_key"] == "politics-media:huanqiu-world"

    assert result.total == 2  # 列表末尾的空对象跳过
    first = result.data[0]
    assert first.id == "4TNv5to6eSF"
    assert first.url == "https://world.huanqiu.com/article/4TNv5to6eSF"
    assert first.cover == "https://img.huanqiucdn.cn/dp/api/files/a.png"  # // 协议相对补全
    assert first.timestamp == 1790521556447  # ctime 本来就是毫秒
    second = result.data[1]
    assert second.url == "https://world.huanqiu.com/gallery/4TNrj1nxgfP"  # gallery 拼法
    assert second.timestamp is None  # ctime 为空


async def test_huanqiu_without_channel_nodes_is_error(monkeypatch):
    _route(
        "huanqiu-world",
        lambda url: _ok({} if url.endswith("channel_pc") else _HUANQIU_LIST),
        monkeypatch,
    )
    with pytest.raises(RuntimeError, match="channel nodes"):
        await politics_media.handle_route(_request("huanqiu-world"), no_cache=True)


async def test_cankaoxiaoxi_maps_fields(monkeypatch):
    captured = _route(
        "cankaoxiaoxi-yaowen", lambda url: _ok(_CKXX_LIST), monkeypatch
    )
    result = await politics_media.handle_route(_request("cankaoxiaoxi-yaowen"), no_cache=True)

    assert captured["urls"] == ["https://www.cankaoxiaoxi.com/json/channel/yaowen/list.json"]
    first = result.data[0]
    assert first.id == "5e34ce019e244d398ed22db1760cb51d"
    assert first.title == "伊朗在联合国发起外交攻势"
    assert first.cover == "https://ckxxapp.ckxx.net/upload/a.jpg"
    assert first.author == "参考消息"
    assert first.timestamp == _ms(2026, 9, 27, 20, 54, 4)
    second = result.data[1]
    assert second.cover is None  # 空 mCoverImg 不映射成空串
    assert second.timestamp is None


async def test_ifeng_maps_hot_and_needs_alldata(monkeypatch):
    captured = _route("ifeng-hot", lambda url: _ok(_IFENG_ALLDATA), monkeypatch)
    result = await politics_media.handle_route(_request("ifeng-hot"), no_cache=True)

    assert captured["urls"] == ["https://ishare.ifeng.com/hotNewsRank"]
    first = result.data[0]
    assert first.id == "doc_1"  # documentId 优先
    assert first.url == "https://ishare.ifeng.com/c/s/abc"  # link.weburl
    assert first.cover == "//p0.ifengimg.com/a.jpg"  # 照页面原样(协议相对)
    assert first.hot == 2970000  # "297万热度"
    assert first.timestamp is None  # 页面没有日期,留空
    assert result.data[1].hot is None

    _route("ifeng-hot", lambda url: _ok("<html>没有 allData 的页面</html>"), monkeypatch)
    with pytest.raises(RuntimeError, match="allData"):
        await politics_media.handle_route(_request("ifeng-hot"), no_cache=True)


async def test_inewsweek_decodes_gbk_and_both_blocks(monkeypatch):
    captured = _route(
        "inewsweek-top10",
        lambda url: _ok(_INEWSWEEK_TOP10.encode("gb18030")),
        monkeypatch,
    )
    result = await politics_media.handle_route(_request("inewsweek-top10"), no_cache=True)

    assert captured["kwargs"][0]["response_type"] == "arraybuffer"  # GBK 按 GB18030 解码
    first = result.data[0]
    assert first.title == '"发霉,还发出刺鼻异味",交个朋友翻车'
    assert first.url == "https://www.inewsweek.cn/finance/2026-09-24/32324.shtml"
    assert first.cover == "https://www.inewsweek.cn/finance/a.jpeg"
    assert first.timestamp == _ms(2026, 9, 24)
    assert result.data[1].url == "https://www.inewsweek.cn/people/2026-09-24/32323.shtml"

    _route("inewsweek-rec", lambda url: _ok(_INEWSWEEK_REC.encode("gb18030")), monkeypatch)
    result = await politics_media.handle_route(_request("inewsweek-rec"), no_cache=True)
    assert result.total == 1  # 注释掉的 ten_text 不算
    assert result.data[0].title == "英国要分裂了?"  # 标题在 grid-item 的 p 里
    assert result.data[0].timestamp == _ms(2026, 9, 17)


async def test_chinadaily_epaper_walks_back_over_empty_day_and_sunday(monkeypatch):
    class _FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):  # 2026-09-28 是周一;09-27 周日无报
            return datetime(2026, 9, 28, 8, 0, tzinfo=_BEIJING)

    monkeypatch.setattr(politics_media, "datetime", _FixedDatetime)
    captured = _route(
        "chinadaily-epaper",
        lambda url: _ok(_EPAPER_PAGE if "/2026-09/26" in url else _EPAPER_EMPTY),
        monkeypatch,
    )
    result = await politics_media.handle_route(_request("chinadaily-epaper"), no_cache=True)

    # 28 号有页面但没文章 → 27 号周日跳过 → 26 号(周六)出文章
    assert [url for url in captured["urls"] if "epaper" in url] == [
        "http://epaper.chinadaily.com.cn/china/2026-09/28",
        "http://epaper.chinadaily.com.cn/china/2026-09/26",
    ]
    assert result.total == 2
    first = result.data[0]
    assert first.title == "Xi: Turn Sino-US shared vision into action"
    assert first.url == "http://epaper.chinadaily.com.cn/a/202609/26/WS6ab70bed.html"
    assert first.desc == "President Xi Jinping called on China and the United States."
    assert first.timestamp == _ms(2026, 9, 26)  # 出版日 0 点
    assert result.data[1].desc is None  # newslist-common 没有导语


async def test_chinadaily_china_maps_latest_list(monkeypatch):
    _route("chinadaily-china", lambda url: _ok(_CHINADAILY_CHINA_PAGE), monkeypatch)
    result = await politics_media.handle_route(_request("chinadaily-china"), no_cache=True)

    first = result.data[0]
    assert first.url == "https://www.chinadaily.com.cn/a/202609/27/WS6ab938c3.html"
    assert first.cover == "https://img2.chinadaily.com.cn/a.jpeg"
    assert first.timestamp == _ms(2026, 9, 27, 23, 39)


async def test_cnr_drops_sign_and_maps_time(monkeypatch):
    captured = _route("cnr-roll", lambda url: _ok(_CNR_PAGE), monkeypatch)
    result = await politics_media.handle_route(_request("cnr-roll"), no_cache=True)

    assert captured["kwargs"][0]["response_type"] == "arraybuffer"
    first = result.data[0]
    assert first.title == "41金11银4铜 中国创参加世界技能大赛最好成绩"
    assert first.url == "https://www.cnr.cn/newscenter/kx/20260927/t20260927_527827128.shtml"
    assert "?sign=" not in first.url  # TRS 预览参数去掉
    assert first.desc == "第48届世界技能大赛于9月27日晚在上海闭幕。"
    assert first.timestamp == _ms(2026, 9, 27, 22, 23)  # 双空格时间也能解析
    assert result.data[1].timestamp is None


async def test_stdaily_nfcmag_qstheory_headline_map(monkeypatch):
    _route("stdaily-roll", lambda url: _ok(_STDAILY_PAGE), monkeypatch)
    result = await politics_media.handle_route(_request("stdaily-roll"), no_cache=True)
    first = result.data[0]
    assert first.title == '活力中国调研行|智慧宫原来真是一座"宫"'
    assert first.desc == "智慧宫的摘要。"
    assert first.cover == "https://www.stdaily.com/web/gdxw/pic/a.png"
    assert first.timestamp == _ms(2026, 9, 27, 10, 20)

    _route("nfcmag-home", lambda url: _ok(_NFCMAG_PAGE), monkeypatch)
    result = await politics_media.handle_route(_request("nfcmag-home"), no_cache=True)
    assert result.data[0].id == "https://www.nfcmag.cn/article/9546.html"  # 页面无稿件 id,用链接
    assert result.data[0].desc == "这是一座城的突围。"
    assert result.data[0].timestamp is None  # 南风窗页面没有日期

    _route("qstheory-headline", lambda url: _ok(_QSTHEORY_HOME), monkeypatch)
    result = await politics_media.handle_route(_request("qstheory-headline"), no_cache=True)
    assert result.total == 1  # 相关链接与大标题同链,去重后 1 条
    assert result.data[0].title == "深度调研|新型能源体系调查"
    assert result.data[0].timestamp == _ms(2026, 9, 15)


async def test_qstheory_issue_two_step_fetch(monkeypatch):
    captured = _route(
        "qstheory-issue",
        lambda url: _ok(_QSTHEORY_DS if url.endswith(".json") else _QSTHEORY_TOC),
        monkeypatch,
    )
    result = await politics_media.handle_route(_request("qstheory-issue"), no_cache=True)

    assert captured["urls"] == [
        "https://www.qstheory.cn/ds_32929c18a87a4be0b577ff0591492df5.json",
        "https://www.qstheory.cn/20260915/3ffd335483ab41a3a67f182fcfdb5c72/c.html",
    ]
    titles = [item.title for item in result.data]
    assert titles == ["本期导读", "新型能源体系调查"]  # 目录页" /作者"拆掉
    assert result.data[1].author == "本刊评论员"
    assert result.data[0].author is None
    assert result.data[0].timestamp == _ms(2026, 9, 15)
    assert result.data[1].timestamp == _ms(2026, 9, 15)


async def test_empty_pages_and_missing_blocks_are_errors(monkeypatch):
    # 观察者网首页没有中栏
    _route("guancha-yaowen", lambda url: _ok("<html><body>改版了</body></html>"), monkeypatch)
    with pytest.raises(RuntimeError, match="li.middle"):
        await politics_media.handle_route(_request("guancha-yaowen"), no_cache=True)

    # 正常页面但解析不到条目(空解析不静默降级)
    _route("stdaily-roll", lambda url: _ok("<html><body>维护中</body></html>"), monkeypatch)
    with pytest.raises(RuntimeError, match="parsed no items"):
        await politics_media.handle_route(_request("stdaily-roll"), no_cache=True)

    # 电子版 7 天都没有文章
    class _FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 9, 28, 8, 0, tzinfo=_BEIJING)

    monkeypatch.setattr(politics_media, "datetime", _FixedDatetime)
    _route("chinadaily-epaper", lambda url: _ok(_EPAPER_EMPTY), monkeypatch)
    with pytest.raises(RuntimeError, match="epaper"):
        await politics_media.handle_route(_request("chinadaily-epaper"), no_cache=True)


async def test_unknown_type_is_rejected(monkeypatch):
    async def fake_get(url, **kwargs):  # pragma: no cover - 不应被调用
        raise AssertionError("unknown type 不应发起上游请求")

    monkeypatch.setattr(politics_media, "get", fake_get)
    with pytest.raises(ValueError, match="Unknown board"):
        await politics_media.handle_route(_request("guancha-life"), no_cache=True)


def test_type_map_matches_board_api():
    """16 个子榜与 board_api 同构;声明序第一个(guancha-yaowen)是默认榜。"""
    assert list(politics_media._TYPE_MAP) == [
        "guancha-yaowen", "guancha-top", "guancha-shiping", "guancha-intl",
        "huanqiu-world", "cankaoxiaoxi-yaowen", "ifeng-hot", "inewsweek-top10",
        "inewsweek-rec", "chinadaily-epaper", "chinadaily-china", "cnr-roll",
        "stdaily-roll", "nfcmag-home", "qstheory-headline", "qstheory-issue",
    ]
    assert politics_media._DEFAULT_TYPE == "guancha-yaowen"
    assert politics_media.ROUTE_NAME == "politics-media"
    # 全部子榜都有 fetcher
    assert set(politics_media._FETCHERS) == set(politics_media._TYPE_MAP)
