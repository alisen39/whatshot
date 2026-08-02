from __future__ import annotations

from datetime import datetime, timezone

from feedgen.feed import FeedGenerator

from whats_hot_api.models import RouterData
from whats_hot_api.utils.logger import logger


def get_rss(data: RouterData) -> str | None:
    try:
        fg = FeedGenerator()
        fg.title(data.title)
        fg.description(
            data.title + data.type + (f" - {data.description}" if data.description else "")
        )
        fg.id(data.name)
        if data.link:
            fg.link(href=data.link)
        fg.language("zh")
        fg.generator("whats-hot-api")
        fg.copyright("Copyright © WhatsHot")
        try:
            fg.updated(datetime.fromisoformat(data.updateTime))
        except (ValueError, TypeError):
            fg.updated(datetime.now(timezone.utc))

        for item in data.data:
            fe = fg.add_entry()
            fe.id(str(item.id))
            fe.title(item.title)
            try:
                fe.updated(datetime.fromisoformat(data.updateTime))
            except (ValueError, TypeError):
                fe.updated(datetime.now(timezone.utc))
            fe.link(href=item.url or "获取失败")
            description = (
                getattr(item, "content", None)
                or getattr(item, "summary", None)
                or getattr(item, "desc", None)
            )
            author = getattr(item, "source", None) or getattr(item, "author", None)
            if description:
                fe.description(description)
            if author:
                fe.author(name=author)

        return fg.rss_str(pretty=True).decode("utf-8")
    except Exception as e:
        logger.error(f"❌ [ERROR] getRSS failed: {e}")
        raise
