"""Official AI lab sources that replaced Google News site: proxies (2026-10-19).

Fixtures are minimal reproductions of each site's real markup or payload.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta, timezone

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import (
    ant_bailing_blog,
    bytedance_seed,
    deepseek_github,
    huggingface_releases,
    inclusionai_huggingface,
    kimi_updates,
    meta_ai_blog,
    minimax_news,
    runway_news,
    suno_blog,
    xai_news,
    zhipu_research,
)
from whats_hot_api.utils import hf_releases
from whats_hot_api.utils.http_client import RequestResult
from whats_hot_api.utils.nextjs import first_list, flight_text, json_values

CST = timezone(timedelta(hours=8))


def ms(*args, tz=UTC) -> int:
    return int(datetime(*args, tzinfo=tz).timestamp() * 1000)


def flight(payload: str) -> str:
    """Wrap text as Next.js flight chunks, split mid-JSON like real pages."""
    half = len(payload) // 2
    chunks = [payload[:half], payload[half:]]
    return "".join(f'<script>self.__next_f.push([1,{json.dumps(c)}])</script>' for c in chunks)


def request(query: bytes = b"") -> Request:
    return Request({"type": "http", "method": "GET", "path": "/", "query_string": query, "headers": []})


def test_flight_helpers_join_chunks_and_pick_longest_list():
    html = flight('x:{"posts":[{"a":1}]},y:{"posts":[{"a":1},{"a":2}]},z:{"post":{"slug":"s"}}')
    assert '"posts":' in flight_text(html)
    assert first_list(html, "posts") == [{"a": 1}, {"a": 2}]
    assert list(json_values(flight_text(html), "post")) == [{"slug": "s"}]
    assert first_list("<html></html>", "posts") == []


def test_suno_skips_undated_posts():
    html = flight(json.dumps({"posts": [
        {"title": "Introducing v6", "slug": {"current": "introducing-v6"}, "publishedAt": "2026-09-09T15:40:00Z",
         "excerpt": "Our best model.", "tags": ["Announcements"], "author": "Team Suno"},
        {"title": "About sidechaining", "slug": {"current": "about-sidechaining"}, "publishedAt": None}]}))
    [item] = suno_blog.parse_posts(html)
    assert (item.url, item.timestamp, item.hotLabel) == ("https://suno.com/blog/introducing-v6", ms(2026, 9, 9, 15, 40),
                                                         "Announcements")


def test_runway_excludes_customer_stories():
    html = flight(json.dumps({"posts": [
        {"title": "Introducing Gen-4", "href": "/research/introducing-runway-gen-4", "date": "2025-03-31T00:00:00.000Z",
         "excerpt": "$undefined", "categoryLabel": "Research"},
        {"title": "How Acme uses Runway", "href": "/customers/acme", "date": "2025-04-01T00:00:00.000Z"}]}))
    [item] = runway_news.parse_posts(html)
    assert (item.url, item.desc, item.hotLabel) == ("https://runway.com/research/introducing-runway-gen-4", None, "Research")


META_BLOG = """<noscript><div data-ms="{&quot;creative&quot;:&quot;listview-card&quot;}">
<p>Blog</p><p class="_8wl0">July 27, 2026</p><h4>Open Source</h4><h4>Reimagining Independence</h4>
<a href="https://ai.meta.com/blog/reimagining-independence/">Learn More</a></div>
<div data-ms="{&quot;creative&quot;:&quot;listview-card&quot;}"><p>April 08, 2026</p><h4>Introducing Muse Spark</h4>
<a href="https://ai.meta.com/blog/introducing-muse-spark-msl/?utm=1">Learn More</a></div></noscript>"""
META_RESEARCH = """<article data-blog-post-summary="featured"><a href="/blog/muse-spark-open">
<time dateTime="2026-10-15">October 15, 2026</time><h2>Introducing Muse Spark Open</h2></a></article>
<article data-blog-post-summary="card"><a href="https://ai.meta.com/blog/introducing-muse-spark-msl/">
<time dateTime="2026-04-08">April 8, 2026</time><h3>Introducing Muse Spark</h3></a></article>"""


def test_meta_merges_blog_and_research_without_duplicates():
    items = meta_ai_blog.merge([meta_ai_blog.parse_blog(META_BLOG), meta_ai_blog.parse_research(META_RESEARCH)])
    assert [(i.title, i.url, i.timestamp) for i in items] == [
        ("Introducing Muse Spark Open", "https://research.meta.ai/blog/muse-spark-open", ms(2026, 10, 15)),
        ("Reimagining Independence", "https://ai.meta.com/blog/reimagining-independence/", ms(2026, 7, 27)),
        ("Introducing Muse Spark", "https://ai.meta.com/blog/introducing-muse-spark-msl/", ms(2026, 4, 8)),
    ]
    assert items[1].hotLabel == "Open Source"


async def test_meta_keeps_client_default_user_agent(monkeypatch):
    calls = []

    async def fake_get(**kwargs):
        calls.append(kwargs)
        page = META_RESEARCH if kwargs["url"] == meta_ai_blog.RESEARCH_LINK else META_BLOG
        return RequestResult(False, "2026-10-19T00:00:00+00:00", page)

    monkeypatch.setattr(meta_ai_blog, "get", fake_get)
    result = await meta_ai_blog.handle_route(request())
    assert result.total == 3
    assert all("headers" not in c for c in calls)  # ai.meta.com answers 400 to desktop browser UAs.


XAI_SITEMAP = """<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<url><loc>https://x.ai/news</loc><lastmod>2026-10-14T00:00:00.000Z</lastmod></url>
<url><loc>https://x.ai/news/grok-voice-3</loc><lastmod>2026-10-14T00:00:00.000Z</lastmod></url>
<url><loc>https://x.ai/news/grok</loc><lastmod>2023-11-03T00:00:00.000Z</lastmod></url></urlset>"""
XAI_PAGE = """<a href="/news/grok-voice-3"><img alt="Grok Voice 3.0"><p>Oct 14, 2026</p><h1>Introducing Grok Voice 3.0</h1>
<p>The world's most intelligent voice model.</p></a><a href="/news/grok"><h3>Announcing Grok</h3></a>
<a href="/news/grok">Read</a><a href="/news">All news</a>"""


async def test_xai_uses_http1_browser_ua_and_sitemap_dates(monkeypatch):
    calls = []

    async def fake_get(**kwargs):
        calls.append(kwargs)
        return RequestResult(False, "2026-10-19T00:00:00+00:00", XAI_SITEMAP if kwargs["url"].endswith(".xml") else XAI_PAGE)

    monkeypatch.setattr(xai_news, "get", fake_get)
    result = await xai_news.handle_route(request())
    assert [(i.title, i.timestamp, i.desc) for i in result.data] == [
        ("Introducing Grok Voice 3.0", ms(2026, 10, 14), "The world's most intelligent voice model."),
        ("Announcing Grok", ms(2023, 11, 3), None)]
    assert all(c["http2"] is False and "Chrome" in c["headers"]["User-Agent"] for c in calls)


def test_bytedance_seed_filters_recruitment_and_prefers_chinese_titles():
    def article(i, area, title_zh, status_zh=2):
        return {"ArticleMeta": {"ArticleID": i, "PublishDate": ms(2026, 8, i, tz=CST), "StatusZh": status_zh,
                                "ResearchArea": [{"ResearchAreaName": area}]},
                "ArticleSubContentEn": {"Title": f"English {i}", "TitleKey": f"post-{i}", "Abstract": " "},
                "ArticleSubContentZh": {"Title": title_zh, "Abstract": "摘要"}}
    items = bytedance_seed.parse_articles([article(5, "Audio", "SeedRealtime 发布"), article(6, "Recruitment", "招聘"),
                                           article(4, "Visual", "未发布", status_zh=1)])
    assert [(i.title, i.url, i.desc) for i in items] == [
        ("SeedRealtime 发布", "https://seed.bytedance.com/zh/blog/post-5", "摘要"),
        ("English 4", "https://seed.bytedance.com/zh/blog/post-4", None)]


def test_ant_ling_posts_from_flight_payload():
    html = flight(json.dumps({"children": [{"post": {"slug": "ling-3.1-flash-open-source", "title": "Ling-3.1-flash 正式开源",
                                                      "date": "2026-10-15", "tags": ["模型发布"], "summary": "开源"}},
                                            {"post": {"slug": "draft", "title": "x", "date": "soon"}}]}))
    [item] = ant_bailing_blog.parse_posts(html)
    assert (item.url, item.timestamp, item.hotLabel) == (
        "https://developer.ant-ling.com/zh-CN/blogs/ling-3.1-flash-open-source", ms(2026, 10, 15, tz=CST), "模型发布")


def test_deepseek_sidebar_labels():
    html = """<a class="menu__link" href="/news/news261017">DeepSeek-V4.1-Flash-1017 Release 2026/10/17</a>
    <a href="/news/news250120">DeepSeek-R1 Release 2025/01/20</a><a href="/news/news250120/">DeepSeek-R1 Release 2025/01/20</a>
    <a href="/news/news0725">New API Features 2024/07/25</a><a href="/guides">Guides</a>"""
    items = deepseek_github.parse_sidebar(html)
    assert [(i.title, i.url, i.timestamp) for i in items] == [
        ("DeepSeek-V4.1-Flash-1017 Release", "https://api-docs.deepseek.com/news/news261017", ms(2026, 10, 17, tz=CST)),
        ("DeepSeek-R1 Release", "https://api-docs.deepseek.com/news/news250120", ms(2025, 1, 20, tz=CST)),
        ("New API Features", "https://api-docs.deepseek.com/news/news0725", ms(2024, 7, 25, tz=CST))]


def test_kimi_keeps_only_moonshot_accounts():
    html = flight(json.dumps({"articleList": {"items": [
        {"id": "kimi-k3", "title": "Kimi K3", "href": "/en/blog/kimi-k3", "date": "2026-07-16", "description": ""},
        {"id": "kimi-dev", "title": "Kimi-Dev", "href": "https://github.com/MoonshotAI/Kimi-Dev", "date": "2025-06-17"},
        {"id": "mooncake", "title": "Mooncake", "href": "https://github.com/kvcache-ai/Mooncake", "date": "2025-06-01"}]}}))
    items = kimi_updates.parse_blog(html)
    assert [(i.title, i.url) for i in items] == [("Kimi K3", "https://www.kimi.com/en/blog/kimi-k3"),
                                                 ("Kimi-Dev", "https://github.com/MoonshotAI/Kimi-Dev")]


def test_zhipu_cms_articles():
    docs = [{"id": "162", "title_zh": "GLM-5.3：前沿编程能力", "title_en": "GLM-5.3", "createAt": "2026-08-14T06:00:00.000Z",
             "resume_zh": None},
            {"id": "163", "title_zh": None, "title_en": "GLM-5.3-Flash", "createAt": "2026-08-26T14:00:00.000Z",
             "resume_zh": " 普惠 "},
            {"id": "1", "title_zh": "无日期", "createAt": None}]
    items = zhipu_research.parse_articles(docs)
    assert [(i.title, i.url, i.desc) for i in items] == [
        ("GLM-5.3-Flash", "https://www.zhipuai.cn/zh/research/163", "普惠"),
        ("GLM-5.3：前沿编程能力", "https://www.zhipuai.cn/zh/research/162", None)]


def test_minimax_release_notes_markdown():
    markdown = """# Models
#### Oct. 19, 2026

<Card title="MiniMax M3.1 Flash" icon="file-text" href="https://www.minimax.io/blog/minimax-m31f" cta="Learn More">
  An ultra-efficient open-weight model.
</Card>

#### Apr. 2026

<Card title="Music-2.6" icon="music" href="/docs/guides/music" cta="Learn More">
  Cover Reborn.
</Card>
"""
    items = minimax_news.parse_release_notes(markdown)
    assert [(i.title, i.url, i.timestamp, i.hotLabel) for i in items] == [
        ("MiniMax M3.1 Flash", "https://www.minimax.io/blog/minimax-m31f", ms(2026, 10, 19), None),
        ("Music-2.6", "https://platform.minimax.io/docs/guides/music", ms(2026, 4, 1), "month")]


def _model(repo, created, **extra):
    return {"id": repo, "createdAt": created, "likes": 1, **extra}


def test_hf_release_grouping():
    models = [
        _model("zai-org/GLM-5.3", "2026-08-25T10:00:00Z", pipeline_tag="text-generation"),
        _model("zai-org/GLM-5.3-Flash", "2026-08-25T11:00:00Z"),
        _model("zai-org/GLM-5.3-FP8", "2026-08-26T09:00:00Z"),
        _model("zai-org/GLM-5.3-GGUF", "2026-09-10T00:00:00Z", tags=["gguf"]),  # Late export joins the release.
        _model("zai-org/GLM-5.2", "2026-06-17T00:00:00Z"),
        _model("zai-org/Qwen3-8B-tuned", "2026-08-01T00:00:00Z",
               baseModels={"relation": "finetune", "models": [{"id": "Qwen/Qwen3-8B"}]}),  # Third-party derivative.
    ]
    releases = hf_releases.group(models, "zai-org")
    assert [(r.family, r.representative.id, len(r.repos)) for r in releases] == [
        ("glm-5.3", "zai-org/GLM-5.3", 4), ("glm-5.2", "zai-org/GLM-5.2", 1)]
    assert hf_releases.family("DeepSeek-V4.1-Flash-1017", "deepseek-ai") == "deepseek-v4.1"
    assert hf_releases.family("Qwen3.8-2.4T-A95B", "Qwen") == "qwen3.8"
    [item, _] = huggingface_releases.to_items(models, "zai-org")
    assert item.title == "GLM-5.3" and item.url == "https://huggingface.co/zai-org/GLM-5.3"
    assert item.desc.startswith("4 个仓库：GLM-5.3、GLM-5.3-Flash、GLM-5.3-FP8、GLM-5.3-GGUF")
    assert item.timestamp == ms(2026, 8, 25, 10)


@pytest.mark.parametrize(("board", "author"), [(b"type=qwen", "Qwen"), (b"type=unknown", "deepseek-ai"), (b"", "deepseek-ai")])
async def test_hf_release_route_maps_board_to_case_sensitive_author(monkeypatch, board, author):
    seen = {}

    async def fake_get(**kwargs):
        seen.update(kwargs)
        return RequestResult(False, "2026-10-19T00:00:00+00:00", [])

    monkeypatch.setattr(huggingface_releases, "get", fake_get)
    await huggingface_releases.handle_route(request(board))
    assert ("author", author) in seen["params"] and ("expand[]", "baseModels") in seen["params"]
    assert seen["cache_key"] == f"huggingface-releases:{author}"


async def test_inclusionai_route_uses_release_grouping(monkeypatch):
    async def fake_get(**kwargs):
        return RequestResult(False, "2026-10-19T00:00:00+00:00",
                             [_model("inclusionAI/Ling-3.1-flash", "2026-10-13T11:16:41Z"),
                              _model("inclusionAI/Ling-3.1-flash-MXFP4", "2026-10-13T12:00:00Z")])

    monkeypatch.setattr(huggingface_releases, "get", fake_get)
    result = await inclusionai_huggingface.handle_route(request())
    assert [i.title for i in result.data] == ["Ling-3.1-flash"]


async def test_zhipu_falls_back_to_release_notes(monkeypatch):
    markdown = '<Update label="2026-8-19" description="GLM-5.3 新一代旗舰模型上线">\n<Update label="2026-08-26" description="GLM-5.3-Flash 上线">'
    urls = []

    async def fake_get(**kwargs):
        urls.append(kwargs["url"])
        if kwargs["url"] == zhipu_research.API_URL:
            raise TimeoutError("cms unreachable")
        return RequestResult(False, "2026-10-19T00:00:00+00:00", markdown)

    monkeypatch.setattr(zhipu_research, "get", fake_get)
    result = await zhipu_research.handle_route(request())
    assert urls == [zhipu_research.API_URL, zhipu_research.RELEASES_URL]
    assert [(i.title, i.url, i.timestamp) for i in result.data] == [
        ("GLM-5.3-Flash 上线", "https://docs.bigmodel.cn/cn/update/new-releases#2026-08-26", ms(2026, 8, 26, tz=CST)),
        ("GLM-5.3 新一代旗舰模型上线", "https://docs.bigmodel.cn/cn/update/new-releases#2026-8-19", ms(2026, 8, 19, tz=CST))]
