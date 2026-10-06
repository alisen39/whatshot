"""thepaper_channels 路由测试:fixtures 按证据目录 tmp/board_api/thepaper_channels 净化(结构与字段一致,内容摘录)。"""

from __future__ import annotations

from typing import Any

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import thepaper_channels
from whats_hot_api.utils.http_client import RequestResult

_UPDATE_AT = "2026-09-28T00:00:00+00:00"


def _request(board_type: str) -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/thepaper-channels",
        "query_string": f"type={board_type}".encode(),
        "headers": [],
    })


def _row(cont_id: str, name: str, **extra: Any) -> dict[str, Any]:
    """证据里 list[] 条目的净化版:结构一致,内容摘录。"""
    row: dict[str, Any] = {
        "contId": cont_id,
        "link": "",
        "praiseTimes": "14",
        "pic": f"https://imgpai.thepaper.cn/newpai/image/{cont_id}.png",
        "pubTimeLong": 1790244750786,
        "nodeInfo": {"nodeId": 25444, "name": "社论"},
    }
    row.update(extra)
    row["name"] = name
    return row


# 栏目(nodeCont/getByNodeIdPortal):第 2 条是外链(澎湃早晚报形态),praiseTimes 是"1.2万"写法
_NODE_PAYLOAD = {
    "code": 200,
    "desc": "ok",
    "data": {
        "hasNext": True,
        "startTime": 1788168472152,
        "list": [
            _row("34141689", "【社论】打破围墙，让艺术更加接地气"),
            _row(
                "34132998",
                "  澎湃早晚报｜10月1日\n",
                link="https://www.peopleapp.com/column/300532-500007",
                praiseTimes="1.2万",
                pic="",
                nodeInfo=None,
            ),
            _row("", "缺 contId 的行应跳过"),  # 无 contId,解析时跳过
        ],
    },
}

# 频道(channel/normalTopInfo):文字头条为空,轮播 1 条;头条区排除与推荐位 id 照证据
_CHANNEL_TOP = {
    "code": 200,
    "data": {
        "recommendTxt": [],
        "recommendImg": [
            _row("34159801", "AI失控风险加剧，OpenAI和Anthropic正调查数万",
                 nodeInfo={"nodeId": 25353, "name": "全球速报"}, praiseTimes="20",
                 pubTimeLong=1790492525973),
        ],
        "excludeContIds": [34159801, 34160440],
        "listRecommendIds": [34160547, 34160440],
    },
}

# 频道信息流(nodeCont/getByChannelId):开头是钉住的推荐条,第 2 条与轮播重复(按 contId 去重)
_CHANNEL_FLOW = {
    "code": 200,
    "data": {
        "hasNext": True,
        "list": [
            _row("34160547", "美国即将放宽汽车油耗标准", nodeInfo={"nodeId": 25353, "name": "全球速报"},
                 praiseTimes="57", pubTimeLong=1790508841654),
            _row("34159801", "AI失控风险加剧，OpenAI和Anthropic正调查数万",
                 nodeInfo={"nodeId": 25353, "name": "全球速报"}, praiseTimes="20",
                 pubTimeLong=1790492525973),
            _row("34160440", "欧盟宣布对部分进口钢铝产品取消配额", nodeInfo={"nodeId": 25353, "name": "全球速报"},
                 praiseTimes="8", pubTimeLong=1790505000000),
        ],
    },
}

# 首页(wwwIndex/recommendNews):resultCode=1 表示成功;文字头条是分组二维数组([[1], [2]] 两组)
_HOME_TOP = {
    "resultCode": 1,
    "resultMsg": "success",
    "data": {
        "recommendTxt": [
            [_row("34161494", "视频画报｜习近平主席的华盛顿时间：继往开来万里行",
                  link="https://h.xinhuaxmt.com/vh512/share/13305132?newstype=1001",
                  nodeInfo=None, praiseTimes="15", pubTimeLong=1790511691414)],
            [
                _row("34161501", "中秋假期收官、国庆将至", nodeInfo={"nodeId": 25949, "name": "要闻"},
                     pubTimeLong=1790514000000),
                _row("34161502", "多部门部署国庆假期工作", nodeInfo={"nodeId": 25949, "name": "要闻"},
                     pubTimeLong=1790515000000),
            ],
        ],
        "recommendImg": [_row("34161956", "41金！中国连续5届位居世界技能大赛金牌榜榜首",
                              nodeInfo={"nodeId": 25462, "name": "中国政库"}, praiseTimes="27",
                              pubTimeLong=1790518499677)],
        "excludeContIds": [34161494, 34161956, 34161501, 34161502],
        "listRecommendIds": [34161592],
    },
}

_HOME_FLOW = {
    "code": 200,
    "data": {
        "hasNext": True,
        "list": [_row("34161592", "“请3休13”拼假族提前享受美景", nodeInfo={"nodeId": 25475, "name": "地产界"},
                      praiseTimes="20", pubTimeLong=1790516198323)],
    },
}


@pytest.fixture(autouse=True)
def _no_throttle(monkeypatch):
    """单测不验证限速本身,只验证请求口径;跳过 3 秒真实间隔。"""

    async def _noop() -> None:
        return None

    monkeypatch.setattr(thepaper_channels, "_polite_delay", _noop)


def _ok(data: Any, update_time: str = _UPDATE_AT, from_cache: bool = False) -> RequestResult:
    return RequestResult(from_cache, update_time, data)


async def test_node_board_maps_fields_and_request(monkeypatch):
    captured: dict[str, Any] = {}

    async def fake_post(**kwargs):
        captured.update(kwargs)
        return _ok(_NODE_PAYLOAD)

    monkeypatch.setattr(thepaper_channels, "post", fake_post)
    result = await thepaper_channels.handle_route(_request("shelun"), no_cache=True)

    assert captured["url"] == "https://api.thepaper.cn/contentapi/nodeCont/getByNodeIdPortal"
    assert captured["body"] == {"nodeId": 25444, "pageSize": 20, "pageNum": 1}
    assert captured["headers"]["Referer"] == "https://www.thepaper.cn/"  # WAF 硬门槛
    assert captured["headers"]["Content-Type"] == "application/json;charset=UTF-8"
    assert result.name == "thepaper-channels"
    assert result.type == "社论"
    assert result.link == "https://www.thepaper.cn/list_25444"  # 响应级 link 是该榜的原站页面
    first = result.data[0]
    assert first.id == "34141689"  # 上游稳定标识 contId,不是名次
    assert first.title == "【社论】打破围墙，让艺术更加接地气"
    assert first.url == "https://www.thepaper.cn/newsDetail_forward_34141689"
    assert first.mobileUrl == "https://m.thepaper.cn/newsDetail_forward_34141689"
    assert first.author == "社论"  # nodeInfo.name,与 thepaper 路由一致
    assert first.hot == 14
    assert first.timestamp == 1790244750786  # pubTimeLong 毫秒原样保留
    second = result.data[1]
    assert second.title == "澎湃早晚报｜10月1日"  # 连续空白压成一个空格、去首尾
    assert second.url == "https://www.peopleapp.com/column/300532-500007"  # 有 link 用 link
    assert second.mobileUrl == "https://www.peopleapp.com/column/300532-500007"  # 外链不换 m 域名
    assert second.hot == 12000  # "1.2万" 换算
    assert second.cover is None  # 空 pic 转为 None
    assert second.author is None
    assert result.total == 2  # 缺 contId 的行不输出


async def test_channel_board_orders_top_carousel_flow_and_dedupes(monkeypatch):
    calls: list[dict[str, Any]] = []

    async def fake_post(**kwargs):
        calls.append(kwargs)
        payload = _CHANNEL_TOP if "normalTopInfo" in kwargs["url"] else _CHANNEL_FLOW
        return _ok(payload, update_time=f"2026-09-28T00:00:0{len(calls)}+00:00")

    monkeypatch.setattr(thepaper_channels, "post", fake_post)
    result = await thepaper_channels.handle_route(_request("guoji"), no_cache=True)

    assert [call["url"].rsplit("/", 1)[-1] for call in calls] == ["normalTopInfo", "getByChannelId"]
    assert calls[0]["body"] == {"channelId": "122908"}
    # 信息流请求照页面调用:带上头条区的排除与推荐位、一页 20 条、startTime 空串
    assert calls[1]["body"] == {
        "channelId": "122908",
        "excludeContIds": [34159801, 34160440],
        "listRecommendIds": [34160547, 34160440],
        "pageSize": 20,
        "startTime": "",
    }
    assert result.type == "国际"
    assert result.link == "https://www.thepaper.cn/channel_122908"
    # 顺序:轮播(文字头条为空)→ 信息流;与轮播重复的 34159801 只留先出现的位置
    assert [item.id for item in result.data] == ["34159801", "34160547", "34160440"]
    assert result.updateTime == "2026-09-28T00:00:02+00:00"  # 用最后一步(信息流)的刷新时间


async def test_home_board_uses_recommend_news_and_empty_channel_id(monkeypatch):
    calls: list[dict[str, Any]] = []

    async def fake_post(**kwargs):
        calls.append(kwargs)
        payload = _HOME_TOP if "recommendNews" in kwargs["url"] else _HOME_FLOW
        return _ok(payload)

    monkeypatch.setattr(thepaper_channels, "post", fake_post)
    result = await thepaper_channels.handle_route(_request("yaowen"), no_cache=True)

    assert calls[0]["url"] == "https://api.thepaper.cn/contentapi/wwwIndex/recommendNews"
    assert calls[0]["body"] == {}  # 首页 JS 不带参数
    assert calls[1]["body"]["channelId"] == ""  # 首页信息流的 channelId 是空串
    assert calls[1]["body"]["excludeContIds"] == [34161494, 34161956, 34161501, 34161502]
    # 顺序照首页 JS 渲染树:文字头条(按组摊平:1 + 2 条)→ 轮播 → 信息流
    assert [item.id for item in result.data] == ["34161494", "34161501", "34161502", "34161956", "34161592"]
    assert result.type == "首页要闻"
    assert result.link == "https://www.thepaper.cn/"
    headline = result.data[0]
    assert headline.url == "https://h.xinhuaxmt.com/vh512/share/13305132?newstype=1001"  # 外链合集
    assert headline.author is None  # 首页文字头条接口不带 nodeInfo


async def test_node_board_rejects_business_error_shell(monkeypatch):
    # 频道 id 当栏目用会返回 code=10000 请求无效(证据实测),错误壳必须报错而不是空榜
    async def fake_post(**kwargs):
        return _ok({"code": 10000, "desc": "请求无效"})

    monkeypatch.setattr(thepaper_channels, "post", fake_post)
    with pytest.raises(RuntimeError, match="10000"):
        await thepaper_channels.handle_route(_request("shelun"), no_cache=True)


async def test_recommend_news_error_shell_is_rejected(monkeypatch):
    # recommendNews 的成功壳是 resultCode=1;缺它(如 code=99998 系统繁忙)按错误处理
    async def fake_post(**kwargs):
        return _ok({"code": 99998, "desc": "系统繁忙"})

    monkeypatch.setattr(thepaper_channels, "post", fake_post)
    with pytest.raises(RuntimeError, match="error shell"):
        await thepaper_channels.handle_route(_request("yaowen"), no_cache=True)


async def test_waf_html_page_is_an_error(monkeypatch):
    # api.thepaper.cn 不带 Referer 返回 403 的腾讯云 WAF 拦截页(HTML),JSON 解析即失败
    async def fake_post(**kwargs):
        raise ValueError("Expecting value: line 1 column 1 (char 0)")

    monkeypatch.setattr(thepaper_channels, "post", fake_post)
    with pytest.raises(RuntimeError, match="WAF"):
        await thepaper_channels.handle_route(_request("shelun"), no_cache=True)


async def test_empty_parse_is_an_error_not_empty_board(monkeypatch):
    async def fake_post(**kwargs):
        return _ok({"code": 200, "data": {"hasNext": False, "list": []}})

    monkeypatch.setattr(thepaper_channels, "post", fake_post)
    with pytest.raises(RuntimeError, match="parsed no items"):
        await thepaper_channels.handle_route(_request("shelun"), no_cache=True)


async def test_unknown_board_is_rejected():
    with pytest.raises(ValueError, match="Unknown board"):
        await thepaper_channels.handle_route(_request("nonsense"), no_cache=True)


def test_hot_parses_wan_suffix_and_rejects_garbage():
    assert thepaper_channels._hot("1.2万") == 12000
    assert thepaper_channels._hot("37") == 37
    assert thepaper_channels._hot("0") == 0
    assert thepaper_channels._hot("-") is None
    assert thepaper_channels._hot("") is None
    assert thepaper_channels._hot(None) is None
