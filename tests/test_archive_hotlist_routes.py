from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from starlette.requests import Request

from whats_hot_api.models import ListItem
from whats_hot_api.routes.hotlist import (
    cankaoxiaoxi,
    bilibili_hot_search,
    bilibili_hot_video,
    chongbuluo,
    crowdsupply,
    iqiyi_hot_ranklist,
    lobsters,
    nowcoder,
    openai_news,
    pcbeta,
    qqvideo_tv_hotsearch,
    qwen_research,
    solidot,
    sputniknewscn,
    tencent_hot,
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
async def test_cankaoxiaoxi_merges_channels_and_sorts(monkeypatch):
    payloads = {
        "zhongguo": {
            "list": [
                {
                    "data": {
                        "id": "china-1",
                        "title": "中国频道较早新闻",
                        "url": "https://ckxxapp.ckxx.net/pages/china-1.html",
                        "publishTime": "2026-07-06 11:00:18",
                        "channelName": "时事",
                        "mCoverImg_s": "https://example.com/china_s.jpg",
                        "commentCount": 2,
                        "praiseCount": 3,
                    }
                }
            ]
        },
        "gj": {
            "list": [
                {
                    "data": {
                        "id": "world-1",
                        "title": "国际频道较新新闻",
                        "url": "https://ckxxapp.ckxx.net/pages/world-1.html",
                        "publishTime": "2026-07-06 13:34:24",
                        "channelName": "国际",
                        "mCoverImg": "https://example.com/world.jpg",
                        "visitCount": 10,
                    }
                }
            ]
        },
        "guandian": {"list": []},
    }

    async def fake_get(**kwargs):  # noqa: ANN003
        url = kwargs["url"]
        channel = url.rsplit("/", 2)[-2]
        return RequestResult(False, f"update-{channel}", payloads[channel])

    monkeypatch.setattr(cankaoxiaoxi, "get", fake_get)

    route_data = await cankaoxiaoxi.handle_route(_request())
    item = route_data.data[0]

    assert route_data.name == "cankaoxiaoxi"
    assert route_data.total == 2
    assert isinstance(item, ListItem)
    assert item.id == "world-1"
    assert item.title == "国际频道较新新闻"
    assert item.author == "国际"
    assert item.cover == "https://example.com/world.jpg"
    assert item.hot == 10
    assert item.timestamp is not None
    assert item.url == "https://ckxxapp.ckxx.net/pages/world-1.html"
    assert route_data.data[1].hot == 5


@pytest.mark.asyncio
async def test_chongbuluo_maps_hot_html(monkeypatch):
    html = """
    <div class="bmw"><table>
      <tr>
        <th class="common">
          <a class="xst" href="thread-24716-1-1.html">听说 NodeLoc 开放注册了？</a>
          <span class="xi1">52人参与</span>
        </th>
        <td class="by"><cite><a>Curry</a></cite></td>
        <td class="num"><a class="xi2">88</a><em>3088</em></td>
        <td class="by"><em><a><span title="2026-7-6 15:45">5 分钟前</span></a></em></td>
      </tr>
    </table></div>
    """

    async def fake_get(**kwargs):  # noqa: ANN003, ARG001
        return RequestResult(False, "2026-07-06T08:55:00+00:00", html)

    monkeypatch.setattr(chongbuluo, "get", fake_get)

    route_data = await chongbuluo.handle_route(_request(b"type=hot"))
    item = route_data.data[0]

    assert route_data.name == "chongbuluo"
    assert route_data.type == "热门"
    assert isinstance(item, ListItem)
    assert item.id == "24716"
    assert item.title == "听说 NodeLoc 开放注册了？"
    assert item.author == "Curry"
    assert item.desc == "52人参与"
    assert item.hot == 3176
    assert item.timestamp is not None
    assert item.url == "https://www.chongbuluo.com/thread-24716-1-1.html"


@pytest.mark.asyncio
async def test_chongbuluo_maps_latest_rss(monkeypatch):
    rss = """<?xml version="1.0" encoding="utf-8"?>
    <rss version="2.0"><channel>
      <item>
        <title>国产Vibe Coding还有多少路要走呢？</title>
        <link>https://www.chongbuluo.com/thread-24762-1-1.html</link>
        <description><![CDATA[<p>最近下载了Trea。</p>]]></description>
        <category>软件</category>
        <author>我们抬头望月</author>
        <pubDate>Mon, 06 Jul 2026 04:23:52 +0000</pubDate>
      </item>
    </channel></rss>
    """

    async def fake_get(**kwargs):  # noqa: ANN003, ARG001
        return RequestResult(False, "2026-07-06T09:00:00+00:00", rss)

    monkeypatch.setattr(chongbuluo, "get", fake_get)

    route_data = await chongbuluo.handle_route(_request(b"type=latest"))
    item = route_data.data[0]

    assert route_data.type == "最新"
    assert item.id == "24762"
    assert item.title == "国产Vibe Coding还有多少路要走呢？"
    assert item.author == "我们抬头望月"
    assert item.desc == "最近下载了Trea。"
    assert item.timestamp == 1783311832000
    assert item.url == "https://www.chongbuluo.com/thread-24762-1-1.html"


@pytest.mark.asyncio
async def test_nowcoder_maps_hot_search_payload(monkeypatch):
    async def fake_get(**kwargs):  # noqa: ANN003
        assert kwargs["cache_key"].endswith("size=20")
        return RequestResult(
            False,
            "2026-07-06T09:10:00+00:00",
            {
                "success": True,
                "code": 0,
                "msg": "OK",
                "data": {
                    "result": [
                        {
                            "type": 74,
                            "id": "2871010",
                            "hotValueFromDolphin": 7761,
                            "title": "AI Coding 面试解题思路总结",
                            "uuid": "d10f345c3de84bc5a3377391b515df61",
                            "desc": "面试解题",
                        },
                        {
                            "type": 0,
                            "id": "12345",
                            "hotValueFromDolphin": 88,
                            "title": "牛客讨论帖",
                        },
                    ]
                },
            },
        )

    monkeypatch.setattr(nowcoder, "get", fake_get)

    route_data = await nowcoder.handle_route(_request())

    assert route_data.name == "nowcoder"
    assert route_data.total == 2
    assert route_data.data[0].id == "d10f345c3de84bc5a3377391b515df61"
    assert route_data.data[0].title == "AI Coding 面试解题思路总结"
    assert route_data.data[0].desc == "面试解题"
    assert route_data.data[0].hot == 7761
    assert route_data.data[0].url == (
        "https://www.nowcoder.com/feed/main/detail/d10f345c3de84bc5a3377391b515df61"
    )
    assert route_data.data[1].id == "12345"
    assert route_data.data[1].url == "https://www.nowcoder.com/discuss/12345"


@pytest.mark.asyncio
async def test_pcbeta_maps_windows_rss(monkeypatch):
    rss = """<?xml version="1.0" encoding="utf-8"?>
    <rss version="2.0"><channel>
      <item>
        <title>Windows 11 新版本体验</title>
        <link>https://bbs.pcbeta.com/thread-2048001-1-1.html</link>
        <description><![CDATA[<p>系统更新讨论。</p>]]></description>
        <author>远景用户</author>
        <pubDate>Mon, 06 Jul 2026 07:54:21 +0000</pubDate>
      </item>
    </channel></rss>
    """

    async def fake_get(**kwargs):  # noqa: ANN003
        assert "fid=563" in kwargs["url"]
        return RequestResult(False, "2026-07-06T09:20:00+00:00", rss)

    monkeypatch.setattr(pcbeta, "get", fake_get)

    route_data = await pcbeta.handle_route(_request(b"type=windows11"))
    item = route_data.data[0]

    assert route_data.name == "pcbeta"
    assert route_data.type == "Windows 11"
    assert item.id == "2048001"
    assert item.title == "Windows 11 新版本体验"
    assert item.author == "远景用户"
    assert item.desc == "系统更新讨论。"
    assert item.timestamp == 1783324461000
    assert item.url == "https://bbs.pcbeta.com/thread-2048001-1-1.html"


@pytest.mark.asyncio
async def test_solidot_maps_homepage_blocks(monkeypatch):
    html = """
    <div class="block_m">
      <div class="bg_htit"><a href="/story?sid=84760">微软将利润转移到低税国家</a></div>
      <div class="talk_time">Edwards (42866) 发表于2026年07月06日 00时16分 星期一 来自发条人偶</div>
      <div class="p_mainnew">微软显然在将利润转移到低企业税国家。</div>
    </div>
    """

    async def fake_get(**kwargs):  # noqa: ANN003, ARG001
        return RequestResult(False, "2026-07-06T09:30:00+00:00", html)

    monkeypatch.setattr(solidot, "get", fake_get)

    route_data = await solidot.handle_route(_request())
    item = route_data.data[0]

    assert route_data.name == "solidot"
    assert item.id == "84760"
    assert item.title == "微软将利润转移到低税国家"
    assert item.author == "Edwards"
    assert item.desc == "微软显然在将利润转移到低企业税国家。"
    assert item.timestamp is not None
    assert item.url == "https://www.solidot.org/story?sid=84760"


@pytest.mark.asyncio
async def test_sputniknewscn_maps_lenta_widget(monkeypatch):
    html = """
    <div class="lenta">
      <div class="lenta__item">
        <a href="/20260706/1072192404.html">
          <span class="lenta__item-text">俄国防部：俄军打击基辅多个军事目标</span>
          <span class="lenta__item-date" data-unixtime="1783323939">15:45</span>
        </a>
      </div>
    </div>
    """

    async def fake_get(**kwargs):  # noqa: ANN003, ARG001
        return RequestResult(False, "2026-07-06T09:40:00+00:00", html)

    monkeypatch.setattr(sputniknewscn, "get", fake_get)

    route_data = await sputniknewscn.handle_route(_request())
    item = route_data.data[0]

    assert route_data.name == "sputniknewscn"
    assert item.id == "1072192404"
    assert item.title == "俄国防部：俄军打击基辅多个军事目标"
    assert item.author == "俄罗斯卫星通讯社"
    assert item.timestamp == 1783323939000
    assert item.url == "https://sputniknews.cn/20260706/1072192404.html"


@pytest.mark.asyncio
async def test_tencent_hot_maps_tag_info_payload(monkeypatch):
    async def fake_get(**kwargs):  # noqa: ANN003
        assert kwargs["params"] == {"tagId": "aEWqxLtdgmQ="}
        return RequestResult(
            False,
            "2026-07-06T09:50:00+00:00",
            {
                "ret": 0,
                "msg": "ok",
                "data": {
                    "tabs": [
                        {
                            "articleList": [
                                {
                                    "id": "20260705A07IVP00",
                                    "title": "哈梅内伊葬礼第二天",
                                    "publish_time": "2026-07-05 19:26:44",
                                    "pic_info": {
                                        "share_img": "https://example.com/share.jpg",
                                        "big_img": ["https://example.com/big.jpg"],
                                    },
                                    "link_info": {
                                        "url": "https://view.inews.qq.com/a/20260705A07IVP00",
                                        "share_url": "https://view.inews.qq.com/a/20260705A07IVP00",
                                    },
                                    "media_info": {"chl_name": "观察者网"},
                                    "interation_info": {
                                        "read_num": 121844,
                                        "commet_num": 95,
                                    },
                                    "desc": "葬礼进入第二天。",
                                }
                            ]
                        }
                    ]
                },
            },
        )

    monkeypatch.setattr(tencent_hot, "get", fake_get)

    route_data = await tencent_hot.handle_route(_request())
    item = route_data.data[0]

    assert route_data.name == "tencent-hot"
    assert item.id == "20260705A07IVP00"
    assert item.title == "哈梅内伊葬礼第二天"
    assert item.cover == "https://example.com/share.jpg"
    assert item.author == "观察者网"
    assert item.desc == "葬礼进入第二天。"
    assert item.hot == 121844
    assert item.timestamp is not None
    assert item.url == "https://view.inews.qq.com/a/20260705A07IVP00"


@pytest.mark.asyncio
async def test_iqiyi_hot_ranklist_maps_video_payload(monkeypatch):
    async def fake_get(**kwargs):  # noqa: ANN003, ARG001
        return RequestResult(
            False,
            "2026-07-06T10:00:00+00:00",
            {
                "code": 0,
                "items": [
                    {
                        "video": [
                            {
                                "data": [
                                    {
                                        "entity_id": 5549082522309401,
                                        "title": "灿如繁星",
                                        "page_url": "https://www.iqiyi.com/v_2f1sx772wzo.html",
                                        "date": {"year": 2026, "month": 7, "day": 5},
                                        "desc": "一往无前 直抵繁星",
                                        "description": "长篇简介",
                                        "hot_score": 7824,
                                        "image_url_normal": "https://example.com/iqiyi.webp",
                                        "starring": [
                                            {"id": 245375805, "name": "陈靖可"},
                                            {"id": 234131205, "name": "虞书欣"},
                                        ],
                                    }
                                ]
                            }
                        ]
                    }
                ],
            },
        )

    monkeypatch.setattr(iqiyi_hot_ranklist, "get", fake_get)

    route_data = await iqiyi_hot_ranklist.handle_route(_request())
    item = route_data.data[0]

    assert route_data.name == "iqiyi-hot-ranklist"
    assert item.id == "5549082522309401"
    assert item.title == "灿如繁星"
    assert item.cover == "https://example.com/iqiyi.webp"
    assert item.author == "陈靖可 / 虞书欣"
    assert item.desc == "一往无前 直抵繁星"
    assert item.hot == 7824
    assert item.timestamp is not None
    assert item.url == "https://www.iqiyi.com/v_2f1sx772wzo.html"


@pytest.mark.asyncio
async def test_qqvideo_tv_hotsearch_posts_and_maps_cards(monkeypatch):
    async def fake_post(**kwargs):  # noqa: ANN003
        assert kwargs["body"]["page_params"]["rank_name"] == "HotSearch"
        assert kwargs["headers"]["Content-Type"] == "application/json"
        return RequestResult(
            False,
            "2026-07-06T10:10:00+00:00",
            {
                "ret": 0,
                "msg": "",
                "data": {
                    "card": {
                        "children_list": {
                            "list": {
                                "cards": [
                                    {
                                        "id": "mzc003ii8jjw44v",
                                        "params": {
                                            "cid": "mzc003ii8jjw44v",
                                            "title": "她似日光",
                                            "sub_title": "两世情缘，宿命难牵",
                                            "image_url": "https://example.com/qqvideo.jpg",
                                            "publish_date": "2026-07-06",
                                        },
                                    }
                                ]
                            }
                        }
                    }
                },
            },
        )

    monkeypatch.setattr(qqvideo_tv_hotsearch, "post", fake_post)

    route_data = await qqvideo_tv_hotsearch.handle_route(_request())
    item = route_data.data[0]

    assert route_data.name == "qqvideo-tv-hotsearch"
    assert item.id == "mzc003ii8jjw44v"
    assert item.title == "她似日光"
    assert item.cover == "https://example.com/qqvideo.jpg"
    assert item.desc == "两世情缘，宿命难牵"
    assert item.timestamp is not None
    assert item.url == "https://v.qq.com/x/cover/mzc003ii8jjw44v.html"


@pytest.mark.asyncio
async def test_bilibili_hot_search_maps_hotword_payload(monkeypatch):
    async def fake_get(**kwargs):  # noqa: ANN003
        assert kwargs["params"] == {"limit": "30"}
        return RequestResult(
            False,
            "2026-07-06T10:20:00+00:00",
            {
                "code": 0,
                "list": [
                    {
                        "hot_id": 259825,
                        "keyword": "内马尔宣布将退出国家队",
                        "show_name": "内马尔宣布将退出国家队",
                        "icon": "http://i0.hdslb.com/icon.png",
                        "heat_score": 4148295,
                        "stat_datas": {"stime": "1783318181"},
                    }
                ],
            },
        )

    monkeypatch.setattr(bilibili_hot_search, "get", fake_get)

    route_data = await bilibili_hot_search.handle_route(_request())
    item = route_data.data[0]

    assert route_data.name == "bilibili-hot-search"
    assert item.id == "259825"
    assert item.title == "内马尔宣布将退出国家队"
    assert item.cover == "https://i0.hdslb.com/icon.png"
    assert item.hot == 4148295
    assert item.timestamp == 1783318181000
    assert item.url == (
        "https://search.bilibili.com/all?keyword=%E5%86%85%E9%A9%AC%E5%B0%94"
        "%E5%AE%A3%E5%B8%83%E5%B0%86%E9%80%80%E5%87%BA%E5%9B%BD%E5%AE%B6%E9%98%9F"
    )


@pytest.mark.asyncio
async def test_bilibili_hot_video_maps_popular_payload(monkeypatch):
    async def fake_get(**kwargs):  # noqa: ANN003, ARG001
        return RequestResult(
            False,
            "2026-07-06T10:30:00+00:00",
            {
                "code": 0,
                "data": {
                    "list": [
                        {
                            "bvid": "BV18HTD61EXk",
                            "title": "PC预下载开启！主题曲",
                            "pubdate": 1783310450,
                            "desc": "预约遗忘之海。",
                            "pic": "http://i0.hdslb.com/bfs/archive/cover.jpg",
                            "owner": {"name": "遗忘之海"},
                            "stat": {"view": 903009, "like": 23188},
                            "short_link_v2": "https://b23.tv/BV18HTD61EXk",
                        }
                    ]
                },
            },
        )

    monkeypatch.setattr(bilibili_hot_video, "get", fake_get)

    route_data = await bilibili_hot_video.handle_route(_request())
    item = route_data.data[0]

    assert route_data.name == "bilibili-hot-video"
    assert item.id == "BV18HTD61EXk"
    assert item.title == "PC预下载开启！主题曲"
    assert item.desc == "预约遗忘之海。"
    assert item.cover == "https://i0.hdslb.com/bfs/archive/cover.jpg"
    assert item.author == "遗忘之海"
    assert item.hot == 903009
    assert item.timestamp == 1783310450000
    assert item.url == "https://b23.tv/BV18HTD61EXk"
    assert item.mobileUrl == "https://m.bilibili.com/video/BV18HTD61EXk"


@pytest.mark.asyncio
async def test_qwen_research_sorts_and_maps_articles(monkeypatch):
    async def fake_get(**kwargs):  # noqa: ANN003, ARG001
        return RequestResult(
            False,
            "2026-07-06T10:40:00+00:00",
            {
                "success": True,
                "data": {
                    "articles": [
                        {
                            "id": "old",
                            "path": "old-paper",
                            "title": "Old Paper",
                            "extra": {
                                "date": "2025-01-01T00:00:00+08:00",
                                "author": "QwenTeam",
                                "introduction": "<p>Old intro</p>",
                            },
                        },
                        {
                            "id": "new",
                            "path": "new-paper",
                            "title": "New Paper",
                            "extra": {
                                "date": "2025-12-05T04:00:00+08:00",
                                "author": "QwenTeam",
                                "cover_small": "https://example.com/qwen.png",
                                "introduction": "<div>New <b>intro</b></div>",
                            },
                        },
                    ]
                },
            },
        )

    monkeypatch.setattr(qwen_research, "get", fake_get)

    route_data = await qwen_research.handle_route(_request())
    item = route_data.data[0]

    assert route_data.name == "qwen-research"
    assert item.id == "new"
    assert item.title == "New Paper"
    assert item.cover == "https://example.com/qwen.png"
    assert item.author == "QwenTeam"
    assert item.desc == "New intro"
    assert item.timestamp is not None
    assert item.url == "https://qwen.ai/research/new-paper"


@pytest.mark.asyncio
async def test_crowdsupply_maps_project_tiles(monkeypatch):
    html = """
    <a class="project-tile" href="/scale-rf/quadrf" aria-label="QuadRF">
      <div class="project-tile-overview"><p>A 4x4 MIMO SDR tile</p></div>
      <img src="/img/quadrf.jpg" />
      <span>1,623 % Funded!</span>
    </a>
    """

    async def fake_get(**kwargs):  # noqa: ANN003, ARG001
        return RequestResult(False, "2026-07-06T10:50:00+00:00", html)

    monkeypatch.setattr(crowdsupply, "get", fake_get)

    route_data = await crowdsupply.handle_route(_request())
    item = route_data.data[0]

    assert route_data.name == "crowdsupply"
    assert item.id == "scale-rf/quadrf"
    assert item.title == "QuadRF"
    assert item.cover == "https://www.crowdsupply.com/img/quadrf.jpg"
    assert item.desc == "A 4x4 MIMO SDR tile"
    assert item.hot == 1623
    assert item.url == "https://www.crowdsupply.com/scale-rf/quadrf"


@pytest.mark.asyncio
async def test_lobsters_maps_rss_items(monkeypatch):
    rss = """<?xml version="1.0" encoding="utf-8"?>
    <rss version="2.0"><channel>
      <item>
        <title>Rayfish - P2P VPN built on top of Iroh</title>
        <link>https://rayfish.xyz/blog/01-introducing-rayfish</link>
        <guid>https://lobste.rs/s/4behtu</guid>
        <author>rayfish.xyz via tomas</author>
        <pubDate>Sun, 05 Jul 2026 13:39:26 -0500</pubDate>
        <comments>https://lobste.rs/s/4behtu/rayfish_p2p_vpn_built_on_top_iroh</comments>
        <category>networking</category>
        <category>distributed</category>
      </item>
    </channel></rss>
    """

    async def fake_get(**kwargs):  # noqa: ANN003, ARG001
        return RequestResult(False, "2026-07-06T11:00:00+00:00", rss)

    monkeypatch.setattr(lobsters, "get", fake_get)

    route_data = await lobsters.handle_route(_request())
    item = route_data.data[0]

    assert route_data.name == "lobsters"
    assert item.id == "4behtu"
    assert item.title == "Rayfish - P2P VPN built on top of Iroh"
    assert item.author == "rayfish.xyz via tomas"
    assert item.desc == "networking, distributed"
    assert item.timestamp is not None
    assert item.url == "https://rayfish.xyz/blog/01-introducing-rayfish"


@pytest.mark.asyncio
async def test_openai_news_maps_and_limits_rss_items(monkeypatch):
    items = []
    start = datetime(2026, 6, 1, 9, 0, tzinfo=timezone.utc)
    for index in range(55):
        item_time = start + timedelta(days=index)
        day = index + 1
        items.append(
            f"""
            <item>
              <title>OpenAI item {day}</title>
              <description><![CDATA[<p>Description {day}</p>]]></description>
              <link>https://openai.com/index/item-{day}</link>
              <guid>https://openai.com/index/item-{day}</guid>
              <category>Company</category>
              <pubDate>{item_time.strftime('%a, %d %b %Y %H:%M:%S GMT')}</pubDate>
            </item>
            """
        )
    rss = f"""<?xml version="1.0" encoding="utf-8"?>
    <rss version="2.0"><channel>{''.join(items)}</channel></rss>
    """

    async def fake_get(**kwargs):  # noqa: ANN003, ARG001
        return RequestResult(False, "2026-07-06T11:10:00+00:00", rss)

    monkeypatch.setattr(openai_news, "get", fake_get)

    route_data = await openai_news.handle_route(_request())
    item = route_data.data[0]

    assert route_data.name == "openai-news"
    assert route_data.total == 50
    assert item.id == "item-55"
    assert item.title == "OpenAI item 55"
    assert item.desc == "Description 55"
    assert item.author == "Company"
    assert item.timestamp is not None
    assert item.url == "https://openai.com/index/item-55"
