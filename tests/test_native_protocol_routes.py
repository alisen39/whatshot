from __future__ import annotations

import importlib

import pytest
from starlette.requests import Request

from whats_hot_api.utils.http_client import RequestResult

NATIVE_PROTOCOL_ROUTES = [('indiehackers', 'indiehackers', 'rss'),
 ('the_register', 'the-register', 'rss'),
 ('techcrunch', 'techcrunch', 'rss'),
 ('techcrunch_ai', 'techcrunch-ai', 'rss'),
 ('the_verge', 'the-verge', 'rss'),
 ('the_verge_ai', 'the-verge-ai', 'rss'),
 ('venturebeat_ai', 'venturebeat-ai', 'rss'),
 ('wired', 'wired', 'rss'),
 ('wired_science', 'wired-science', 'rss'),
 ('engadget', 'engadget', 'rss'),
 ('apnews_technology', 'apnews-technology', 'rsshub'),
 ('mit_tech_review', 'mit-tech-review', 'rss'),
 ('mit_tech_review_ai', 'mit-tech-review-ai', 'rss'),
 ('quanta_magazine', 'quanta-magazine', 'rss'),
 ('big_think', 'big-think', 'rss'),
 ('nature', 'nature', 'rss'),
 ('phys_org', 'phys-org', 'rss'),
 ('singularity_hub', 'singularity-hub', 'rss'),
 ('daring_fireball', 'daring-fireball', 'rss'),
 ('appleinsider', 'appleinsider', 'rss'),
 ('cult_of_mac', 'cult-of-mac', 'rss'),
 ('macrumors', 'macrumors', 'rss'),
 ('nine_to_five_mac', '9to5mac', 'rsshub'),
 ('securityonline', 'securityonline', 'rss'),
 ('cointelegraph', 'cointelegraph', 'rsshub'),
 ('economist', 'economist', 'rss'),
 ('the_atlantic', 'the-atlantic', 'rss'),
 ('the_guardian', 'the-guardian', 'rss'),
 ('financial_times', 'financial-times', 'rss'),
 ('wsj', 'wsj', 'rss'),
 ('axios', 'axios', 'rss'),
 ('business_insider', 'business-insider', 'rss'),
 ('sky_news', 'sky-news', 'rss'),
 ('google_news', 'google-news', 'rss'),
 ('politico', 'politico', 'rss'),
 ('new_yorker', 'new-yorker', 'rss'),
 ('daily_dev_popular', 'daily-dev-popular', 'rsshub'),
 ('smashing_mag', 'smashing-mag', 'rss'),
 ('css_tricks', 'css-tricks', 'rss'),
 ('infoq', 'infoq', 'rss'),
 ('stackoverflow_blog', 'stackoverflow-blog', 'rss'),
 ('huggingface_blog', 'huggingface-blog', 'rss'),
 ('openai_research', 'openai-research', 'rsshub'),
 ('openai_cookbook', 'openai-cookbook', 'rsshub'),
 ('openai_alignment', 'openai-alignment', 'rss'),
 ('openai_academy', 'openai-academy', 'rss'),
 ('anthropic_news', 'anthropic-news', 'rsshub'),
 ('transformer_circuits', 'transformer-circuits', 'rss'),
 ('claude_blog', 'claude-blog', 'rss'),
 ('claude_code_releases', 'claude-code-releases', 'rss'),
 ('xai_news', 'xai-news', 'rss'),
 ('qwen_blog', 'qwen-blog', 'rss'),
 ('zhipu_research', 'zhipu-research', 'rss'),
 ('bytedance_seed', 'bytedance-seed', 'rss'),
 ('inclusionai_huggingface', 'inclusionai-huggingface', 'rss'),
 ('ant_bailing_blog', 'ant-bailing-blog', 'rss'),
 ('meituan_longcat', 'meituan-longcat', 'rss'),
 ('kimi_updates', 'kimi-updates', 'rss'),
 ('minimax_news', 'minimax-news', 'rss'),
 ('latent_space', 'latent-space', 'rss'),
 ('simon_willison', 'simon-willison', 'rss'),
 ('sebastian_raschka', 'sebastian-raschka', 'rss'),
 ('mozilla_ai', 'mozilla-ai', 'rss'),
 ('google_research_blog', 'google-research-blog', 'rss'),
 ('google_ai_blog', 'google-ai-blog', 'rss'),
 ('google_developers_blog', 'google-developers-blog', 'rss'),
 ('deepmind_blog', 'deepmind-blog', 'rsshub'),
 ('apple_ml_research', 'apple-ml-research', 'rss'),
 ('apple_newsroom', 'apple-newsroom', 'rss'),
 ('meta_ai_blog', 'meta-ai-blog', 'rss'),
 ('meta_engineering', 'meta-engineering', 'rss'),
 ('nvidia_ai_blog', 'nvidia-ai-blog', 'rss'),
 ('cloudflare_blog', 'cloudflare-blog', 'rss'),
 ('cursor_blog', 'cursor-blog', 'rss'),
 ('runway_news', 'runway-news', 'rss'),
 ('runway_changelog', 'runway-changelog', 'rss'),
 ('midjourney_updates', 'midjourney-updates', 'rss'),
 ('suno_blog', 'suno-blog', 'rss'),
 ('openrouter_announcements', 'openrouter-announcements', 'rss'),
 ('lmsys_blog', 'lmsys-blog', 'rss'),
 ('eleutherai_blog', 'eleutherai-blog', 'rss'),
 ('berkeley_rdi', 'berkeley-rdi', 'rss'),
 ('cmu_ml_blog', 'cmu-ml-blog', 'rss'),
 ('gary_marcus', 'gary-marcus', 'rss'),
 ('tomer_tunguz', 'tomer-tunguz', 'rss'),
 ('interconnects', 'interconnects', 'rss'),
 ('dwarkesh_patel', 'dwarkesh-patel', 'rss'),
 ('one_useful_thing', 'one-useful-thing', 'rss'),
 ('dario_amodei', 'dario-amodei', 'rss'),
 ('sam_altman', 'sam-altman', 'rss'),
 ('deepseek_github', 'deepseek-github', 'rss'),
 ('descript_blog', 'descript-blog', 'rss'),
 ('servicenow_ai', 'servicenow-ai', 'rss'),
 ('deeplearning_the_batch', 'deeplearning-the-batch', 'rsshub'),
 ('arxiv_cs_ai', 'arxiv-cs-ai', 'rss'),
 ('arxiv_cs_lg', 'arxiv-cs-lg', 'rss'),
 ('arxiv_cs_cl', 'arxiv-cs-cl', 'rss'),
 ('bair_blog', 'bair-blog', 'rss'),
 ('the_gradient', 'the-gradient', 'rss'),
 ('the_decoder', 'the-decoder', 'rss'),
 ('karpathy_blog', 'karpathy-blog', 'rss'),
 ('lilian_weng', 'lilian-weng', 'rss'),
 ('arxiv_robotics', 'arxiv-robotics', 'rss'),
 ('ieee_robotics', 'ieee-robotics', 'rss'),
 ('techcrunch_robotics', 'techcrunch-robotics', 'rss'),
 ('new_atlas_robotics', 'new-atlas-robotics', 'rss'),
 ('engadget_robotics', 'engadget-robotics', 'rss'),
 ('techxplore_robotics', 'techxplore-robotics', 'rss'),
 ('robot_report', 'robot-report', 'rss'),
 ('robohub', 'robohub', 'rss'),
 ('boston_dynamics', 'boston-dynamics', 'rss'),
 ('nvidia_news_robotics', 'nvidia-news-robotics', 'rss'),
 ('nvidia_dev_robotics', 'nvidia-dev-robotics', 'rss'),
 ('mit_news_robotics', 'mit-news-robotics', 'rss'),
 ('open_robotics_blog', 'open-robotics-blog', 'rss'),
 ('robotics_automation_news', 'robotics-automation-news', 'rss'),
 ('robotics_tomorrow', 'robotics-tomorrow', 'rss'),
 ('bdtechtalks', 'bdtechtalks', 'rss'),
 ('synced_review', 'synced-review', 'rss'),
 ('arxiv_cs_cv', 'arxiv-cs-cv', 'rss'),
 ('arxiv_eess_sy', 'arxiv-eess-sy', 'rss'),
 ('ros_discourse', 'ros-discourse', 'rss'),
 ('planet_ros', 'planet-ros', 'rss'),
 ('hackaday', 'hackaday', 'rss'),
 ('toms_hardware', 'toms-hardware', 'rss'),
 ('nvidia_blog', 'nvidia-blog', 'rss'),
 ('the_verge_gadgets', 'the-verge-gadgets', 'rss'),
 ('gizmodo', 'gizmodo', 'rss'),
 ('serve_the_home', 'serve-the-home', 'rss'),
 ('adafruit', 'adafruit', 'rss'),
 ('make_magazine', 'make-magazine', 'rss'),
 ('tindie_blog', 'tindie-blog', 'rss'),
 ('liliputing', 'liliputing', 'rss'),
 ('nature_bmi', 'nature-bmi', 'rss'),
 ('nature_neuroscience', 'nature-neuroscience', 'rss'),
 ('arxiv_q_bio_nc', 'arxiv-q-bio-nc', 'rss'),
 ('frontiers_neuroscience', 'frontiers-neuroscience', 'rss'),
 ('ieee_biomedical', 'ieee-biomedical', 'rss'),
 ('mit_tech_review_bio', 'mit-tech-review-bio', 'rss'),
 ('arxiv_cs_ne', 'arxiv-cs-ne', 'rss'),
 ('frontiers_human_neuro', 'frontiers-human-neuro', 'rss'),
 ('neuroscience_news', 'neuroscience-news', 'rss'),
 ('science_alert', 'science-alert', 'rss'),
 ('zhihu_hot', 'zhihu-hot', 'rsshub'),
 ('ithome_ranking_24h', 'ithome-ranking-24h', 'rsshub'),
 ('kr36_news', '36kr-news', 'rsshub'),
 ('appinn', 'appinn', 'rss'),
 ('ruanyifeng_weekly', 'ruanyifeng-weekly', 'rss')]
RSS_SAMPLE = """<?xml version="1.0"?><rss><channel><item><guid>sample</guid><title>Sample</title><link>https://example.com/sample</link></item></channel></rss>"""


def _request() -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/",
        "query_string": b"",
        "headers": [],
    })


@pytest.mark.asyncio
@pytest.mark.parametrize(("module_name", "route_name", "provider"), NATIVE_PROTOCOL_ROUTES)
async def test_native_protocol_route_owns_metadata_and_fetch(monkeypatch, module_name, route_name, provider):
    module = importlib.import_module(f"whats_hot_api.routes.hotlist.{module_name}")
    assert module.ROUTE_NAME == route_name
    assert module.ROUTE_META["name"] == route_name
    assert module.ROUTE_META["title"]

    if provider == "rss":
        captured = {}

        async def fake_get(**kwargs):  # noqa: ANN003
            captured.update(kwargs)
            return RequestResult(False, "2026-07-30T00:00:00+00:00", RSS_SAMPLE)

        monkeypatch.setattr(module, "get", fake_get)
    else:
        captured = {}

        async def fake_fetch(**kwargs):  # noqa: ANN003
            captured.update(kwargs)
            return {
                "from_cache": False,
                "update_time": "2026-07-30T00:00:00+00:00",
                "data": [],
            }

        monkeypatch.setattr(module, "fetch_rsshub_feed", fake_fetch)

    result = await module.handle_route(_request(), no_cache=True)

    assert result.name == route_name
    assert result.title == module.ROUTE_META["title"]
    assert result.fromCache is False
    assert result.updateTime == "2026-07-30T00:00:00+00:00"
    if provider == "rss":
        assert captured["url"] == module.FEED_URL
        assert captured["no_cache"] is True
        assert captured["response_type"] == "text"
    else:
        assert captured["route_name"] == route_name
        assert captured["route_path"] == module.RSSHUB_ROUTE
        assert captured["no_cache"] is True
