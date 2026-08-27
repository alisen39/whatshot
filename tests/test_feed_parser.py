from __future__ import annotations

from datetime import datetime

from whats_hot_api.utils.feed import parse_feed


def _ms(iso: str) -> int:
    return int(datetime.fromisoformat(iso).timestamp() * 1000)

FRONTIERS_STYLE_RSS = """
<rss version="2.0"><channel><title>Frontiers</title>
<pubDate>Thu, 27 Aug 2026 00:00:00 +0000</pubDate>
<item>
  <guid isPermaLink="true">https://www.frontiersin.org/articles/10.3389/fnhum.2026.1778517</guid>
  <link>https://www.frontiersin.org/articles/10.3389/fnhum.2026.1778517</link>
  <title><![CDATA[Lowercase pubdate study]]></title>
  <pubdate>2026-08-27T00:00:00Z</pubdate>
  <description>Published with a non-standard lowercase item-level pubdate tag.</description>
</item>
<item>
  <guid isPermaLink="true">https://www.frontiersin.org/articles/10.3389/fnhum.2026.1778516</guid>
  <link>https://www.frontiersin.org/articles/10.3389/fnhum.2026.1778516</link>
  <title><![CDATA[Standard pubDate study]]></title>
  <pubDate>Wed, 26 Aug 2026 00:00:00 +0000</pubDate>
  <description>Published with the standard item-level pubDate tag.</description>
</item>
</channel></rss>
"""


def test_parse_feed_reads_lowercase_item_pubdate():
    items = parse_feed(FRONTIERS_STYLE_RSS)

    assert len(items) == 2
    by_title = {item.title: item for item in items}
    # The lowercase-<pubdate> item must get a real timestamp instead of None,
    # and the parser must order by it (newer first).
    assert by_title["Lowercase pubdate study"].timestamp == _ms("2026-08-27T00:00:00+00:00")
    assert by_title["Standard pubDate study"].timestamp == _ms("2026-08-26T00:00:00+00:00")
    assert [item.title for item in items] == [
        "Lowercase pubdate study",
        "Standard pubDate study",
    ]


def test_parse_feed_prefers_standard_pubdate_when_both_casings_exist():
    rss = FRONTIERS_STYLE_RSS.replace(
        "<pubDate>Wed, 26 Aug 2026 00:00:00 +0000</pubDate>",
        "<pubDate>Thu, 27 Aug 2026 00:00:00 +0000</pubDate>",
    )
    items = parse_feed(rss)

    # Standard pubDate still wins over the lowercase variant for the same node.
    assert all(item.timestamp == _ms("2026-08-27T00:00:00+00:00") for item in items)
