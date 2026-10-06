"""xinhua_channels 路由测试:fixtures 按证据目录 tmp/board_api/xinhua_channels 净化。

一期 7 个子榜(politics/world/fortune/tech 等)与二期 5 个子榜(world-jsxw/depth-xhsp/
comments-wpyc/home-latest/comments-zhonghualun)共用同一套解析逻辑,规范要求改配置要
覆盖原有子榜 + 新增子榜,这里两侧都有用例。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import xinhua_channels
from whats_hot_api.utils.http_client import RequestResult

_BEIJING = timezone(timedelta(hours=8))


def _request(board_type: str) -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/xinhua-channels",
        "query_string": f"type={board_type}".encode(),
        "headers": [],
    })


def _ok(payload: Any) -> RequestResult:
    return RequestResult(False, "2026-09-28T00:00:00+00:00", payload)


def _ds_payload(rows: list[dict]) -> dict:
    """ds 数据文件顶层是列表元信息 + datasource 数组;fixtures 只留关键元信息。"""
    return {"categoryName": "要闻", "datasource": rows}


# 链接型行(politics 首屏全是这种):title 是一串 <a>,publishUrl 可能是绝对地址
_LINK_ROW = {
    "contentId": "202609247181c0ed2e9d4517a71c62cd073cd224",
    "title": "<a href='https://www.news.cn/politics/20260924/a512e6e3/c.html' target='_blank'>我国将开展第二次全国非遗普查 建立非遗资源总目录</a>",
    "showTitle": "<a href='https://www.news.cn/politics/20260924/a512e6e3/c.html' target='_blank'>我国将开展第二次全国非遗普查 建立非遗资源总目录</a>",
    "contentType": "Link",
    "linkUrls": [{"linkTitle": "我国将开展第二次全国非遗普查 建立非遗资源总目录",
                  "linkUrl": "https://www.news.cn/politics/20260924/a512e6e3/c.html"}],
    "publishUrl": "https://www.news.cn/politics/20260924/a512e6e3/c.html",
    # 链接型行的 publishTime 是编辑放进列表的时间,不是内容发布时间,timestamp 留空
    "publishTime": "2026-09-24 23:10:00",
    "titleImages": [],
    "summary": "",
    "author": "",
}

# 一行多链接(world"要闻"的专题行):专题标签跳过,"全文"附属跳过,其余拆成多条
_MULTI_LINK_ROW = {
    "contentId": "2026092512cc9440fc9242679b4cf2b925d95264",
    "title": "<a href='...'>专题 |</a><a href='...'>习近平主席访美难忘瞬间意义深远</a><a href='...'>王毅谈习近平主席对美国进行国事访问</a>",
    "showTitle": "<a href='...'>专题 |</a><a href='...'>习近平主席访美难忘瞬间意义深远</a>",
    "contentType": "Link",
    "linkUrls": [
        {"linkTitle": "专题 |", "linkUrl": "https://www.news.cn/world/cnleaders/fwmg/index.html"},
        {"linkTitle": "习近平主席访美难忘瞬间意义深远",
         "linkUrl": "/world/20260927/9f0b8eae/c.html"},
        {"linkTitle": "全文", "linkUrl": "/world/20260927/9f0b8eae/c.html"},
        {"linkTitle": "王毅谈习近平主席对美国进行国事访问",
         "linkUrl": "https://www.news.cn/world/20260926/988db1cb/c.html"},
    ],
    "publishUrl": "https://www.news.cn/world/cnleaders/fwmg/index.html",
    "publishTime": "2026-09-25 07:11:40",
    "titleImages": [],
    "summary": "",
    "author": "",
}

# 稿件型行(fortune/tech 等频道):相对 publishUrl + 相对封面,带作者、摘要、发布时间
_MEDIA_ROW = {
    "contentId": "2026092782b64bfae6ba47ef87c47b889bff2b7d",
    "title": "美拟大幅放松新车油耗标准 电动化转型恐放缓",
    "showTitle": "美拟大幅放松新车油耗标准 电动化转型恐放缓",
    "contentType": "MultiMedia",
    "linkUrls": [],
    "publishUrl": "/fortune/20260927/82b64bfa/c.html",
    "publishTime": "2026-09-27 16:19:33",
    "titleImages": [{"imageUrl": "20260927/82b64bfa/20260927_cover.jpg", "isPrimary": ""}],
    "summary": "美国新车油耗标准拟大幅放松。",
    "author": "王宏彬",
}

# 二期钟华论:单链接 Link 行,封面与摘要都是 HTML/相对地址,取下方列表的数据文件
_ZHONGHUALUN_ROW = {
    "contentId": "202603247f06052cb0bd4366b6408ce7a7a30dfa",
    "title": "<a href='https://www.news.cn/politics/20260323/24fc484a/c.html' target='_blank'>一步一步往上走，一程一程向复兴</a>",
    "showTitle": "<a href='https://www.news.cn/politics/20260323/24fc484a/c.html' target='_blank'>一步一步往上走，一程一程向复兴</a>",
    "contentType": "Link",
    "linkUrls": [{"linkTitle": "一步一步往上走，一程一程向复兴",
                  "linkUrl": "https://www.news.cn/politics/20260323/24fc484a/c.html"}],
    "publishUrl": "https://www.news.cn/politics/20260323/24fc484a/c.html",
    "publishTime": "2026-03-24 08:07:57",
    "titleImages": [{"imageUrl": "../../20260324/7f06052c/cover.jpeg", "isPrimary": "1"}],
    "summary": "<a href='https://www.news.cn/politics/20260323/24fc484a/c.html'>从“一五”到“十五五”，一步一个脚印坚定朝前走。</a>",
    "author": "",
}

# 二期首页"最新播报":publishUrl 是相对根目录的路径,按频道页(首页)补全
_HOME_LATEST_ROW = {
    "contentId": "2026092715e7281fb67b4db8bf49b6a623b540f6",
    "title": "41金11银4铜 中国创参加世界技能大赛最好成绩",
    "showTitle": "41金11银4铜 中国创参加世界技能大赛最好成绩",
    "contentType": "MultiMedia",
    "linkUrls": [],
    "publishUrl": "20260927/15e7281f/c.html",
    "publishTime": "2026-09-27 22:19:08",
    "titleImages": [],
    "summary": "第48届世界技能大赛于9月27日晚在上海闭幕。",
    "author": "",
}


async def test_politics_link_row_maps_fields_and_request(monkeypatch):
    captured: dict[str, Any] = {}

    async def fake_get(**kwargs):
        captured.update(kwargs)
        return _ok(_ds_payload([_LINK_ROW]))

    monkeypatch.setattr(xinhua_channels, "get", fake_get)
    result = await xinhua_channels.handle_route(_request("politics"), no_cache=True)

    # 一期时政:频道页 + datasource id 拼数据文件地址;无查询参数
    assert captured["url"] == (
        "https://www.news.cn/politics/ds_a6d618872de143bdafa2556915a7ae12.json"
    )
    assert captured["no_cache"] is True
    assert captured["headers"] == xinhua_channels._HEADERS
    assert result.name == "xinhua-channels"
    assert result.title == "新华网"
    assert result.type == "时政"
    assert result.total == 1
    item = result.data[0]
    assert item.id == "202609247181c0ed2e9d4517a71c62cd073cd224"  # 单链接行用 contentId
    assert item.title == "我国将开展第二次全国非遗普查 建立非遗资源总目录"  # <a> 片段去 HTML
    assert item.url == "https://www.news.cn/politics/20260924/a512e6e3/c.html"
    assert item.mobileUrl == item.url
    # 链接型行的 publishTime 是放进列表的时间,不是内容发布时间,timestamp 留空
    assert item.timestamp is None
    assert item.hot is None  # 列表不提供热度
    assert item.cover is None
    assert item.desc is None  # 空摘要转 None


async def test_world_multi_link_row_splits_and_skips_tag_links(monkeypatch):
    async def fake_get(**kwargs):
        return _ok(_ds_payload([_MULTI_LINK_ROW]))

    monkeypatch.setattr(xinhua_channels, "get", fake_get)
    result = await xinhua_channels.handle_route(_request("world"), no_cache=True)

    assert result.total == 2  # "专题 |"标签与"全文"附属跳过,其余两链接拆成两条
    first, second = result.data
    # 拆条没有独立 contentId,用文章 URL 当 id;相对链接按频道页补全
    assert first.id == "https://www.news.cn/world/20260927/9f0b8eae/c.html"
    assert first.title == "习近平主席访美难忘瞬间意义深远"
    assert first.url == "https://www.news.cn/world/20260927/9f0b8eae/c.html"
    assert second.id == "https://www.news.cn/world/20260926/988db1cb/c.html"
    assert second.title == "王毅谈习近平主席对美国进行国事访问"
    assert first.timestamp is None  # 链接型行 timestamp 留空


async def test_fortune_media_row_maps_timestamp_cover_and_relative_url(monkeypatch):
    async def fake_get(**kwargs):
        return _ok(_ds_payload([_MEDIA_ROW]))

    monkeypatch.setattr(xinhua_channels, "get", fake_get)
    result = await xinhua_channels.handle_route(_request("fortune"), no_cache=True)

    assert result.type == "财经"
    item = result.data[0]
    assert item.id == "2026092782b64bfae6ba47ef87c47b889bff2b7d"
    assert item.title == "美拟大幅放松新车油耗标准 电动化转型恐放缓"
    # 相对 publishUrl 与相对封面都按频道页 https://www.news.cn/fortune/ 补全
    assert item.url == "https://www.news.cn/fortune/20260927/82b64bfa/c.html"
    assert item.cover == "https://www.news.cn/fortune/20260927/82b64bfa/20260927_cover.jpg"
    assert item.author == "王宏彬"
    assert item.desc == "美国新车油耗标准拟大幅放松。"
    # 稿件型行 publishTime(北京时间)转 Unix 毫秒
    expected = int(datetime(2026, 9, 27, 16, 19, 33, tzinfo=_BEIJING).timestamp() * 1000)
    assert item.timestamp == expected


async def test_phase2_home_latest_and_zhonghualun(monkeypatch):
    urls: list[str] = []
    payloads: dict[str, dict] = {
        "home-latest": _ds_payload([_HOME_LATEST_ROW]),
        "comments-zhonghualun": _ds_payload([_ZHONGHUALUN_ROW]),
    }

    async def fake_get(**kwargs):
        urls.append(kwargs["url"])
        return _ok(payloads["home-latest"] if "bbc6736b" in kwargs["url"] else payloads["comments-zhonghualun"])

    monkeypatch.setattr(xinhua_channels, "get", fake_get)

    latest = await xinhua_channels.handle_route(_request("home-latest"), no_cache=True)
    assert urls[-1] == "https://www.news.cn/ds_bbc6736b83a14fbb9caf24d78f9aab7f.json"
    assert latest.type == "滚动新闻（首页最新播报）"
    item = latest.data[0]
    # 相对根目录的 publishUrl 按首页补全成根路径 /YYYYMMDD/.../c.html
    assert item.url == "https://www.news.cn/20260927/15e7281f/c.html"
    expected = int(datetime(2026, 9, 27, 22, 19, 8, tzinfo=_BEIJING).timestamp() * 1000)
    assert item.timestamp == expected  # 稿件型行取 publishTime

    zhonghualun = await xinhua_channels.handle_route(_request("comments-zhonghualun"), no_cache=True)
    assert urls[-1] == (
        "https://www.news.cn/comments/plldzt/zhonghualun/"
        "ds_42a905699ddb4f5298955c4c1388d868.json"  # 取下方列表的数据文件,不是顶部轮播
    )
    assert zhonghualun.type == "钟华论"
    item = zhonghualun.data[0]
    assert item.id == "202603247f06052cb0bd4366b6408ce7a7a30dfa"
    assert item.title == "一步一步往上走，一程一程向复兴"
    # 相对封面按钟华论页目录补全(../../ 从 zhonghualun/ 上溯到 /comments/);
    # Link 行 timestamp 留空,HTML 摘要去标签
    assert item.cover == "https://www.news.cn/comments/20260324/7f06052c/cover.jpeg"
    assert item.desc == "从“一五”到“十五五”，一步一个脚印坚定朝前走。"
    assert item.timestamp is None


async def test_first_screen_limit_and_url_dedup(monkeypatch):
    # tech 首屏 15 行:第 3 行与第 1 行是同一篇(URL 去重),第 16 行超出首屏不取
    dup = {**_MEDIA_ROW, "contentId": "dup", "publishUrl": "/tech/20260927/u00/c.html"}
    extra = {**_MEDIA_ROW, "contentId": "beyond-first-screen"}
    rows = [
        {**_MEDIA_ROW, "contentId": f"id{n:02d}", "publishUrl": f"/tech/20260927/u{n:02d}/c.html"}
        for n in range(14)
    ]
    rows.insert(2, dup)  # 15 行,其中 1 行重复
    rows.append(extra)  # 第 16 行

    async def fake_get(**kwargs):
        return _ok(_ds_payload(rows))

    monkeypatch.setattr(xinhua_channels, "get", fake_get)
    result = await xinhua_channels.handle_route(_request("tech"), no_cache=True)

    assert result.total == 14  # 首屏 15 行内去重 1 行;第 16 行不算
    assert result.data[2].id == "id02"  # 重复行只留第一次


async def test_all_board_configs_build_expected_urls():
    """12 个子榜的配置回归:URL 拼接、标签与默认榜(politics)。"""
    assert next(iter(xinhua_channels.type_map)) == "politics"  # 声明序第一个是默认榜
    assert xinhua_channels.type_map["politics"] == "时政"
    expected_urls = {
        "politics": "https://www.news.cn/politics/ds_a6d618872de143bdafa2556915a7ae12.json",
        "world": "https://www.news.cn/world/ds_8d5294ed513c4779af6242a3623aa27b.json",
        "comments": "https://www.news.cn/comments/ds_8e0f870f8f8b4643a239608debe7f2ee.json",
        "local": "https://www.news.cn/local/ds_5c5939c2f07b4d9c96de44dad32eadc8.json",
        "tech": "https://www.news.cn/tech/ds_fd79514d92f34849bc8baef7ce3d5aae.json",
        "fortune": "https://www.news.cn/fortune/ds_1e491dadc8944459b71b7ab13422623d.json",
        "mil": "https://www.news.cn/milpro/ds_efa406de9b714538a958d4a20a80ecf3.json",
        "world-jsxw": "https://www.news.cn/world/jsxw/ds_29089f6bdec84f03b12804d9fe4897be.json",
        "depth-xhsp": "https://www.news.cn/depthobserve/ds_1636c5be477b4b519c0a4e969cfd28ee.json",
        "comments-wpyc": "https://www.news.cn/comments/wpyc/ds_2d7f116cc1f34730974912b1512cb10d.json",
        "home-latest": "https://www.news.cn/ds_bbc6736b83a14fbb9caf24d78f9aab7f.json",
        "comments-zhonghualun": (
            "https://www.news.cn/comments/plldzt/zhonghualun/"
            "ds_42a905699ddb4f5298955c4c1388d868.json"
        ),
    }
    assert set(expected_urls) == set(xinhua_channels._BOARDS)
    for board, url in expected_urls.items():
        label, page, datasource, _first_screen = xinhua_channels._BOARDS[board]
        assert f"{page}ds_{datasource}.json" == url
        assert xinhua_channels.type_map[board] == label
    # 首屏行数与证据口径一致
    first_screens = {b: cfg[3] for b, cfg in xinhua_channels._BOARDS.items()}
    assert first_screens == {
        "politics": 50, "world": 50, "comments": 15, "local": 15, "tech": 15,
        "fortune": 20, "mil": 64, "world-jsxw": 13, "depth-xhsp": 20,
        "comments-wpyc": 15, "home-latest": 15, "comments-zhonghualun": 40,
    }


async def test_unknown_board_is_rejected():
    with pytest.raises(ValueError, match="Unknown board"):
        await xinhua_channels.handle_route(_request("nonsense"), no_cache=True)


@pytest.mark.parametrize("payload", [{}, {"datasource": []}, {"datasource": "x"}, [1, 2]])
async def test_broken_payload_is_an_error_not_empty_board(monkeypatch, payload):
    async def fake_get(**kwargs):
        return _ok(payload)

    monkeypatch.setattr(xinhua_channels, "get", fake_get)
    with pytest.raises(RuntimeError, match="datasource has no rows"):
        await xinhua_channels.handle_route(_request("politics"), no_cache=True)


async def test_empty_parse_is_an_error(monkeypatch):
    # 行都在但一条都解析不出(缺标题/缺链接)时,必须报错而不是返回空榜
    broken = [
        {"contentId": "a", "title": "", "publishUrl": ""},
        {"contentId": "b", "linkUrls": [{"linkTitle": "", "linkUrl": ""}]},
    ]

    async def fake_get(**kwargs):
        return _ok(_ds_payload(broken))

    monkeypatch.setattr(xinhua_channels, "get", fake_get)
    with pytest.raises(RuntimeError, match="parsed no items"):
        await xinhua_channels.handle_route(_request("comments"), no_cache=True)
