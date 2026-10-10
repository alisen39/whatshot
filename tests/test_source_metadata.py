import importlib
import json
from pathlib import Path

import pytest
from starlette.requests import Request

from whats_hot_api.models import ListItem
from whats_hot_api.utils.http_client import RequestResult

FIXTURES = Path(__file__).parent / 'fixtures/source_metadata'

@pytest.mark.asyncio
@pytest.mark.parametrize('name,module', [
    ('baidu','baidu'), ('douyin','douyin'), ('toutiao','toutiao'), ('zhihu','zhihu'),
    ('bilibili-search','bilibili_hot_search'), ('bilibili-video','bilibili_hot_video'), ('tieba','tieba'),
])
async def test_native_metadata_from_captured_upstream_rows(monkeypatch,name,module):
    route=importlib.import_module('whats_hot_api.routes.hotlist.'+module)
    rows=json.loads((FIXTURES/(name+'.json')).read_text())
    payload={'baidu':'<!--s-data:'+json.dumps({'data':{'cards':[{'content':rows}]}})+'-->',
        'douyin':{'data':{'word_list':rows}}, 'toutiao':{'data':rows}, 'zhihu':{'data':rows},
        'bilibili-search':{'list':rows}, 'bilibili-video':{'code':0,'data':{'list':rows}},
        'tieba':{'data':{'bang_topic':{'topic_list':rows}}}}[name]
    captured={}
    async def get(*args,**kwargs):
        captured.update(kwargs)
        return RequestResult(False,'2026-10-09T15:31:00+00:00',payload)
    monkeypatch.setattr(route,'get',get)
    req=Request({'type':'http','path':'/'+name,'query_string':b'', 'headers':[]})
    result=await route.handle_route(req,no_cache=True)
    assert captured['no_cache'] is True
    assert result.updateTime=='2026-10-09T15:31:00+00:00'
    assert result.data and all(item.badges is not None for item in result.data)
    first=result.data[0]
    if name in ('baidu','douyin'):
        assert first.isPinned is True and first.sourceRank is None
        assert result.data[1].sourceRank == 1
    if name=='bilibili-search':
        assert first.cover is None
        assert first.badges[0].imageUrl == rows[0]['icon'].replace('http:','https:')
        assert first.hot == rows[0].get('heat_score')
    if name=='zhihu':
        assert first.badges[0].darkImageUrl==rows[0]['card_label']['night_icon']
        assert first.metrics['answers']==rows[0]['target']['answer_count']
        assert result.data[1].badges==[]  # debut does not fabricate a new badge
    if name=='bilibili-video':
        assert first.durationSeconds==rows[0]['duration']
        assert first.hot==rows[0]['stat']['view'] and first.hotLabel=='播放'
        assert first.metrics['danmaku']==rows[0]['stat']['danmaku']
    if name=='tieba':
        assert first.sourceRank==int(rows[0]['idx_num'])
        assert all(not badge.text and not badge.imageUrl for badge in first.badges)
    if name=='baidu':
        rows[1].pop('hotScore',None);rows[1]['hotTag']='3'
        payload='<!--s-data:'+json.dumps({'data':{'cards':[{'content':rows}]}})+'-->'
        again=await route.handle_route(req,no_cache=True)
        assert again.data[1].hot==0


def test_optional_metadata_tolerates_malformed_labels_without_losing_topic():
    item=ListItem(id='1',title='Topic',url='https://example.com',
        badges=[None,False,{'text':{},'imageUrl':'javascript:bad'},
                {'code':99,'text':'','color':'url(bad)','imageUrl':'//example.com/b.gif'}],
        sourceRank=True,isPinned='false',metrics={'views':0,'likes':-1,'invalid':True})
    assert len(item.badges)==1
    assert item.badges[0].code=='99' and item.badges[0].imageUrl=='https://example.com/b.gif'
    assert item.sourceRank is None and item.isPinned is None
    assert item.metrics=={'views':0}
    assert ListItem(id='1',title='x',url='').badges is None
    assert ListItem(id='1',title='x',url='',badges=[]).badges==[]


# ---------------------------------------------------------------------------
# 2026-10 扩展批次:wave 0-2 接入来源
# ---------------------------------------------------------------------------

def _request() -> Request:
    return Request({'type': 'http', 'path': '/x', 'query_string': b'', 'headers': []})


NEW_HOTLIST = [
    ('iqiyi-rank', 'iqiyi_rank'),
    ('ximalaya-rank', 'ximalaya_rank'),
    ('weread', 'weread'),
    ('acfun', 'acfun'),
    ('bilibili-main', 'bilibili'),
    ('csdn', 'csdn'),
    ('sspai', 'sspai'),
    ('smzdm', 'smzdm'),
    ('stackoverflow', 'stackoverflow'),
    ('tencent-hot', 'tencent_hot'),
    ('hackernews', 'hackernews'),
]


def _payload_for(name: str, rows: list[dict]):
    if name == 'hackernews':
        return {}  # 两次请求不同 payload,由测试内的 get 分发
    if name == 'iqiyi-rank':
        return {'code': 0, 'data': {'items': [{'contents': rows}]}}
    if name == 'ximalaya-rank':
        cluster = json.loads((FIXTURES / '_ximalaya-cluster.json').read_text())
        return {'ret': 200, 'data': {**cluster, 'rankList': [{**cluster['rankList'][0], 'albums': rows}]}}
    if name == 'weread':
        return {'books': rows}
    if name == 'acfun':
        return {'rankList': rows}
    if name == 'bilibili-main':
        return {'code': 0, 'data': {'list': rows}}
    if name == 'csdn':
        return {'code': 200, 'data': rows}
    if name == 'sspai':
        return {'data': rows, 'error': ''}
    if name == 'smzdm':
        return {'data': rows}
    if name == 'stackoverflow':
        return {'items': rows}
    if name == 'tencent-hot':
        return {'data': {'tabs': [{'articleList': rows}]}}
    raise AssertionError(name)


@pytest.mark.asyncio
@pytest.mark.parametrize('name,module', NEW_HOTLIST)
async def test_expanded_sources_carry_native_metadata(monkeypatch, name, module):
    route = importlib.import_module('whats_hot_api.routes.hotlist.' + module)
    rows = json.loads((FIXTURES / (name + '.json')).read_text())
    payload = _payload_for(name, rows)
    calls = []

    async def get(url, *args, **kwargs):
        calls.append(str(url))
        if name == 'hackernews' and str(url).endswith('stories.json'):
            return RequestResult(False, '2026-10-11T00:00:00+00:00',
                                 [row['id'] for row in rows])
        if name == 'hackernews':
            item_id = int(str(url).rsplit('/', 1)[-1].split('.')[0])
            row = next(row for row in rows if row['id'] == item_id)
            return RequestResult(False, '2026-10-11T00:00:00+00:00', row)
        return RequestResult(False, '2026-10-11T00:00:00+00:00', payload)

    monkeypatch.setattr(route, 'get', get)
    if name == 'bilibili-main':
        async def fake_wbi():
            return 'wts=0&w_rid=0'
        # 路由模块在 import 时绑定了自己的 get_bili_wbi 引用
        monkeypatch.setattr(route, 'get_bili_wbi', fake_wbi)
    result = await route.handle_route(_request(), no_cache=True)
    assert result.data
    badge_sources = {'iqiyi-rank', 'weread', 'acfun', 'bilibili-main', 'sspai', 'smzdm', 'stackoverflow', 'tencent-hot'}
    if name in badge_sources:
        assert all(item.badges is not None for item in result.data)
    first = result.data[0]
    if name == 'iqiyi-rank':
        assert first.sourceRank == rows[0]['order'] == 1
        assert first.hotLabel in ('实时热度', '最高热度', '飙升幅度', '推荐分', '期待值')
        assert any(badge.text for badge in first.badges)
    if name == 'ximalaya-rank':
        assert first.sourceRank == 1 and first.hotLabel == '播放'
    if name == 'weread':
        assert first.sourceRank == 1 and first.hotLabel == '阅读'
        rating = rows[0]['bookInfo'].get('newRating')
        if isinstance(rating, int) and rating > 0:
            assert first.metrics['rating'] == rating
    if name == 'acfun':
        assert first.sourceRank == 1
        assert first.durationSeconds == rows[0]['durationMillis'] // 1000
        assert first.metrics['viewCount'] == rows[0]['viewCount']
    if name == 'bilibili-main':
        assert first.hotLabel == '播放'
        assert first.durationSeconds == rows[0]['duration']
        assert first.metrics['danmaku'] == rows[0]['stat']['danmaku']
        assert first.sourceRank == 1
    if name == 'csdn':
        assert first.metrics['views'] == int(rows[0]['viewCount'])
        assert first.hotLabel == '热度'
    if name == 'sspai':
        corner = rows[0].get('corner') or {}
        if corner.get('name'):
            assert first.badges[0].text == corner['name']
    if name == 'smzdm':
        pretag = rows[0].get('article_title_pre_tag') or []
        if pretag:
            assert first.badges[0].text == pretag[0]['article_title']
    if name == 'stackoverflow':
        assert first.metrics['answers'] == rows[0]['answer_count']
    if name == 'tencent-hot':
        assert first.metrics['views'] == rows[0]['interation_info']['read_num']
        assert first.badges[0].text == rows[0]['category']['cate1_name']
    if name == 'hackernews':
        assert first.metrics['comments'] == rows[0]['descendants']
        assert first.sourceRank == 1
        assert first.desc is None  # 评论数不再拼进 desc


def test_weibo_category_band_parses_native_metadata():
    category = importlib.import_module('whats_hot_api.routes.hotlist._weibo_categories')
    rows = [
        {'realpos': 1, 'num': 100, 'word': '话题A', 'word_scheme': '#话题A#',
         'icon_desc': '热', 'icon_desc_color': '#ff9406', 'is_ad': 0},
        {'realpos': 2, 'num': 90, 'word': '话题B', 'word_scheme': '#话题B#',
         'icon_desc': '', 'is_ad': 0},
    ]
    data = category._parse_band({'ok': 1, 'data': {'band_list': rows}})
    assert [item.sourceRank for item in data] == [1, 2]
    assert data[0].badges[0].text == '热' and data[0].badges[0].color == '#ff9406'
    assert data[1].badges == [] and data[1].hotLabel == '热度'


def test_iqiyi_hot_ranklist_corner_badges_use_known_codes_only():
    ranklist = importlib.import_module('whats_hot_api.routes.hotlist.iqiyi_hot_ranklist')
    badges = ranklist._corner_badges({'cornerMark': 'vip', 'dq_updatestatus': '更新至4集', 'pay_mark': 'VIP_MARK'})
    assert [badge['text'] for badge in badges] == ['VIP', '更新至4集', 'VIP']
    assert ranklist._corner_badges({'cornerMark': 'mystery-code'}) is None


def test_dongqiudi_metrics_use_comments_total():
    dongqiudi = importlib.import_module('whats_hot_api.routes.hotlist.dongqiudi')
    item = dongqiudi._item({'id': '1', 'title': 'T', 'comments_total': 3962}, pc_link=True)
    assert item.metrics == {'comments': 3962}
    assert dongqiudi._item({'id': '1', 'title': 'T'}, pc_link=True).metrics is None


@pytest.mark.asyncio
async def test_newsflash_wallstreetcn_score_maps_to_important(monkeypatch):
    route = importlib.import_module('whats_hot_api.routes.newsflash.wallstreetcn')
    rows = json.loads((FIXTURES / 'wallstreetcn-newsflash.json').read_text())

    async def get(url, *args, **kwargs):
        return RequestResult(False, '2026-10-11T00:00:00+00:00', {'data': {'items': rows}})

    monkeypatch.setattr(route, 'get', get)
    result = await route.handle_route(_request(), no_cache=True)
    assert result.data[0].isImportant is True  # score=2 整条加红（页面核验）
    assert all(item.isImportant is False for item in result.data[1:])
