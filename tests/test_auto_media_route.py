from __future__ import annotations

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import auto_media
from whats_hot_api.utils.http_client import RequestResult


def _request(board_type: str) -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/auto-media",
        "query_string": f"type={board_type}".encode(),
        "headers": [],
    })


# content.api.autohome.com.cn/pc/rank/v2/list 的净化版
_RANK_PAYLOAD = {
    "returncode": 0,
    "message": " successful",
    "result": [
        {
            "bizId": 26578467,
            "title": "12.99万元之后，大众要重新回答一个问题",
            "subTitle": "494.9万",
            "url": "https://chejiahao.autohome.com.cn/info/26578467#pvareaid=6834132",
            "hotScore": 88823,
            "rank": 1,
        },
        {"bizId": 1317507, "title": "全新宝马3系燃油版官图发布", "subTitle": "8823", "url": "http://www.autohome.com.cn/news/202609/1317507.html"},
        {"bizId": 1317508, "title": "没有链接的行不算", "subTitle": "1.0万", "url": ""},
    ],
}


@pytest.mark.asyncio
async def test_autohome_rank_maps_subtitle_index_and_count_param(monkeypatch):
    captured: dict[str, object] = {}

    async def fake_get(url, headers=None, params=None, no_cache=None, response_type=None, **kwargs):
        captured.update({"url": url, "params": params})
        return RequestResult(False, "2026-10-01T00:00:00+00:00", _RANK_PAYLOAD)

    monkeypatch.setattr(auto_media, "get", fake_get)
    result = await auto_media.handle_route(_request("autohome-article"), no_cache=True)

    assert captured["url"] == "https://content.api.autohome.com.cn/pc/rank/v2/list"
    assert captured["params"] == {"count": "30", "ranktype": "3"}  # count=30 必需,不带只回 15 条
    assert result.type == "汽车之家 · 文章排行榜（三日热门文章）"
    first = result.data[0]
    assert first.id == "26578467"  # bizId,不是名次
    assert first.url == "https://chejiahao.autohome.com.cn/info/26578467#pvareaid=6834132"
    assert first.hot == 4949000  # subTitle"494.9万" -> 页面显示的指数
    assert result.data[1].hot == 8823  # 无单位按原数
    assert len(result.data) == 2  # 没有链接的行跳过


@pytest.mark.asyncio
async def test_autohome_rank_error_shell_is_rejected(monkeypatch):
    async def fake_get(url, headers=None, params=None, no_cache=None, response_type=None, **kwargs):
        return RequestResult(False, "t", {"returncode": -1, "message": "error", "result": None})

    monkeypatch.setattr(auto_media, "get", fake_get)
    with pytest.raises(RuntimeError, match="returncode=-1"):
        await auto_media.handle_route(_request("autohome-video"), no_cache=True)


_CLUB_HOME = """<html><body>
<div class="rank-group"><h2 class="rank-group-name">论坛7日家人榜</h2>
<ul class="rank-list"><li><span class="name"><a href="//i.autohome.com.cn/1176247#pvareaid=6826817">hehe6666</a></span>
<span class="result">511062活跃值</span></li></ul></div>
<div class="rank-group"><h2 class="rank-group-name">论坛热帖榜</h2>
<ul class="rank-list">
<li><span class="num">1</span><span class="name"><a href="//club.autohome.com.cn/bbs/thread/49bf6859e33e376f/116303700-1.html#pvareaid=6826819">方程豹宣布钛9四季度上市</a></span>
<span class="result"><i class="icon-hot"></i>73495</span></li>
<li><span class="num">2</span><span class="name"><a href="//club.autohome.com.cn/bbs/thread/be11ef11dfb53240/116305870-1.html">ES8最值得入手的配置</a></span>
<span class="result"><i class="icon-hot"></i>64141</span></li>
</ul></div></body></html>"""


@pytest.mark.asyncio
async def test_club_hot_picks_named_group_and_thread_ids(monkeypatch):
    async def fake_get(url, headers=None, no_cache=None, response_type=None, **kwargs):
        return RequestResult(False, "2026-10-01T00:00:00+00:00", _CLUB_HOME)

    monkeypatch.setattr(auto_media, "get", fake_get)
    result = await auto_media.handle_route(_request("autohome-club-hot"), no_cache=True)

    assert result.type == "汽车之家论坛 · 论坛热帖榜"
    first = result.data[0]
    assert first.id == "116303700"  # 帖子 id,不是名次
    assert first.title == "方程豹宣布钛9四季度上市"
    assert first.url == "https://club.autohome.com.cn/bbs/thread/49bf6859e33e376f/116303700-1.html#pvareaid=6826819"
    assert first.hot == 73495
    assert len(result.data) == 2  # "论坛7日家人榜"不取


@pytest.mark.asyncio
async def test_club_hot_missing_group_is_an_error(monkeypatch):
    async def fake_get(url, headers=None, no_cache=None, response_type=None, **kwargs):
        return RequestResult(False, "t", "<html><body>改版后的论坛首页</body></html>")

    monkeypatch.setattr(auto_media, "get", fake_get)
    with pytest.raises(RuntimeError, match="论坛热帖榜"):
        await auto_media.handle_route(_request("autohome-club-hot"), no_cache=True)


_JINGXUAN = """<html><body>
<ul class="js-show-bd"><li>顶部轮播推荐位不算</li></ul>
<ul class="content">
<li tid="116166947" class="">
  <div class="pic-box"><a href="//club.autohome.com.cn/bbs/thread/99d2148273f324ea/116166947-1.html" title="奥迪E7X提车作业分享">
  <img src="//z.autoimg.cn/holdimg.png" data-original="//club2.autoimg.cn/album/g33/M01/cover.jpg"></a></div>
  <div class="pic_txt"><span class="model-num">新能源</span>
  <p><a href="//club.autohome.com.cn/bbs/thread/99d2148273f324ea/116166947-1.html" title="奥迪E7X提车作业分享">空间表现满分 奥迪E7X提车作业分享</a></p>
  <dl><dt class="user"><a href="//i.autohome.com.cn/306774021/"><span>北京车友2056843</span></a></dt></dl></div>
</li>
</ul></body></html>"""


@pytest.mark.asyncio
async def test_jingxuan_maps_fields_and_skips_carousel(monkeypatch):
    async def fake_get(url, headers=None, no_cache=None, response_type=None, **kwargs):
        return RequestResult(False, "t", _JINGXUAN)

    monkeypatch.setattr(auto_media, "get", fake_get)
    result = await auto_media.handle_route(_request("autohome-club-meiren"), no_cache=True)

    assert result.type == "汽车之家论坛 · 美人生活秀"
    item = result.data[0]
    assert item.id == "116166947"  # li[tid]
    assert item.title == "空间表现满分 奥迪E7X提车作业分享"
    assert item.cover == "https://club2.autoimg.cn/album/g33/M01/cover.jpg"  # data-original 补 https
    assert item.author == "北京车友2056843"
    assert item.desc == "新能源"  # 标签
    assert len(result.data) == 1  # ul.js-show-bd 轮播不输出


_DC_PAYLOAD = {"prompts": [], "status": 0, "message": "success",
               "data": {"rank_name": "热搜榜", "rank_code": 0,
                        "tops": [{"gid": "", "title": "38.98万起 新款问界M8开启预售", "is_hot": 2, "score": 1634806, "description": ""},
                                 {"gid": "", "title": "", "score": 1}]}}


@pytest.mark.asyncio
async def test_dongchedi_hot_search_builds_search_links(monkeypatch):
    async def fake_get(url, headers=None, no_cache=None, response_type=None, **kwargs):
        assert url == "https://www.dongchedi.com/motor/pc/common/rank/hot_search"
        return RequestResult(False, "t", _DC_PAYLOAD)

    monkeypatch.setattr(auto_media, "get", fake_get)
    result = await auto_media.handle_route(_request("dongchedi-hot-search"), no_cache=True)

    assert result.type == "懂车帝 · 实时热搜榜"
    assert len(result.data) == 1  # 空词条跳过
    item = result.data[0]
    assert item.id == "38.98万起 新款问界M8开启预售"  # 词条作 id
    assert item.url == "https://www.dongchedi.com/search?keyword=38.98%E4%B8%87%E8%B5%B7%20%E6%96%B0%E6%AC%BE%E9%97%AE%E7%95%8CM8%E5%BC%80%E5%90%AF%E9%A2%84%E5%94%AE"
    assert item.hot == 1634806  # score
    assert item.timestamp is None  # 热搜词没有时间字段


_YICHE_HOME = """<html><body><div class="comm-right-box"><h1>资讯排行榜</h1>
<ul class="comm-list-box">
<li class="comm-item ka point-content" point-crgn="zixunpaihangbang" point-cid="113483091" point-cpos="1">
<a href="https://news.yiche.com/xinchexiaoxi/20260929/11113483091.html"><span class="h-zx-title">2027款长城欧拉好猫正式上市</span></a></li>
<li class="comm-item" point-crgn="otherblock" point-cid="999"><a href="https://news.yiche.com/x/1.html"><span>其它区块不算</span></a></li>
</ul></div></body></html>"""


@pytest.mark.asyncio
async def test_yiche_rank_maps_point_cid(monkeypatch):
    async def fake_get(url, headers=None, no_cache=None, response_type=None, **kwargs):
        assert url == "https://www.yiche.com/"
        return RequestResult(False, "t", _YICHE_HOME)

    monkeypatch.setattr(auto_media, "get", fake_get)
    result = await auto_media.handle_route(_request("yiche-news-rank"), no_cache=True)

    assert result.type == "易车 · 资讯排行榜（最火文章排行）"
    assert len(result.data) == 1  # 其它埋点区块不取
    item = result.data[0]
    assert item.id == "113483091"  # point-cid
    assert item.title == "2027款长城欧拉好猫正式上市"
    assert item.url == "https://news.yiche.com/xinchexiaoxi/20260929/11113483091.html"
    assert item.timestamp is None  # 列表不给发布时间


@pytest.mark.asyncio
async def test_unknown_board_is_rejected():
    with pytest.raises(ValueError, match="Unknown board"):
        await auto_media.handle_route(_request("nonsense"), no_cache=True)


@pytest.mark.asyncio
async def test_empty_parse_is_an_error(monkeypatch):
    async def fake_get(url, headers=None, no_cache=None, response_type=None, **kwargs):
        return RequestResult(False, "t", "<html><body>空页面</body></html>")

    monkeypatch.setattr(auto_media, "get", fake_get)
    with pytest.raises(RuntimeError, match="parsed no items"):
        await auto_media.handle_route(_request("autohome-club-jingxuan"), no_cache=True)
