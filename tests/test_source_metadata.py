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
