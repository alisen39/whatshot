from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PORT: int = 6688
    CACHE_TTL: int = 1800
    HOTLIST_CACHE_TTL: int = 1800
    NEWSFLASH_CACHE_TTL: int = 300
    REQUEST_TIMEOUT: int = 6000
    # Comma-separated origins. Use "*" only for deliberately public APIs;
    # credentialed CORS is never enabled by the core application.
    ALLOWED_DOMAIN: str = "https://whatshot.top,http://127.0.0.1:3000"
    ENVIRONMENT: str = ""
    USE_LOG_FILE: bool = True
    RSS_MODE: bool = False
    REDIS_HOST: str = "127.0.0.1"
    REDIS_PORT: int = 6379
    REDIS_PASSWORD: str = ""
    REDIS_DB: int = 0
    ZHIHU_COOKIE: str = ""
    ROUTE_PROXY: str = ""  # JSON: {"github.com":"http://127.0.0.1:7890"}
    SOURCE_RSSHUB_BASE_URLS: str = ""  # Optional comma/space separated RSSHub instances

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )


# Module-level singleton. The create_app() factory may replace this with a
# subclass instance so that extension settings are visible to all core modules.
config: Settings = Settings()


def replace_config(new_config: Settings) -> None:
    """Replace the module-level config singleton.

    Called by create_app() when an extension provides custom settings.
    All core modules that do ``from whats_hot_api.config import config``
    will see the updated object after this call because we mutate the
    module's global dict.
    """
    import whats_hot_api.config as _mod

    old_config = _mod.config
    if old_config is not new_config:
        old_config.__dict__.clear()
        old_config.__dict__.update(new_config.__dict__)
        if hasattr(new_config, "__pydantic_fields_set__"):
            old_config.__pydantic_fields_set__ = set(new_config.__pydantic_fields_set__)
        if hasattr(new_config, "__pydantic_extra__"):
            old_config.__pydantic_extra__ = new_config.__pydantic_extra__
        if hasattr(new_config, "__pydantic_private__"):
            old_config.__pydantic_private__ = new_config.__pydantic_private__

    _mod.config = new_config
