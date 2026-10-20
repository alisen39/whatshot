from __future__ import annotations

from starlette.requests import Request

from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.hf_releases import group
from whats_hot_api.utils.http_client import get

ROUTE_NAME = "huggingface-releases"
SOURCE_LINK = "https://huggingface.co/models"
API_URL = "https://huggingface.co/api/models"
# Board type -> official Hugging Face account (author is case-sensitive: "qwen" returns nothing).
ORGS: dict[str, tuple[str, str]] = {
    "deepseek-ai": ("deepseek-ai", "DeepSeek"),
    "qwen": ("Qwen", "Qwen"),
    "moonshotai": ("moonshotai", "Moonshot AI"),
    "zai-org": ("zai-org", "智谱 Z.ai"),
    "minimaxai": ("MiniMaxAI", "MiniMax"),
    "stepfun-ai": ("stepfun-ai", "阶跃星辰"),
    "xiaomimimo": ("XiaomiMiMo", "小米 MiMo"),
    "bytedance-seed": ("ByteDance-Seed", "字节跳动 Seed"),
    "inclusionai": ("inclusionAI", "蚂蚁 inclusionAI"),
    "tencent": ("tencent", "腾讯"),
    "baidu": ("baidu", "百度"),
    "openai": ("openai", "OpenAI"),
    "google": ("google", "Google"),
    "meta-llama": ("meta-llama", "Meta Llama"),
    "mistralai": ("mistralai", "Mistral AI"),
}
ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "Hugging Face 官方组织新模型",
    "description": "各 AI 机构官方 Hugging Face 账号的新模型发布，同一次发布的多个仓库合并为一条",
    "link": SOURCE_LINK,
    "params": {"type": {"name": "机构", "type": {key: label for key, (_, label) in ORGS.items()}}},
}
LIMIT = 100
_EXPAND = ("createdAt", "likes", "downloads", "tags", "pipeline_tag", "baseModels")


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    board = request.query_params.get("type", "deepseek-ai")
    author, label = ORGS.get(board, ORGS["deepseek-ai"])
    list_data = await get_releases(author, no_cache)
    return RouterData(
        **ROUTE_META,
        type=label,
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
    )


async def get_releases(author: str, no_cache: bool) -> dict:
    params = [("author", author), ("sort", "createdAt"), ("direction", "-1"), ("limit", str(LIMIT))]
    params += [("expand[]", field) for field in _EXPAND]
    result = await get(url=API_URL, params=params, no_cache=no_cache, cache_key=f"huggingface-releases:{author}")
    models = result.data if isinstance(result.data, list) else []
    return {"from_cache": result.from_cache, "update_time": result.update_time, "data": to_items(models, author)}


def to_items(models: list[dict], author: str) -> list[ListItem]:
    items = []
    for release in group(models, author):
        lead = release.representative
        names = [r.id.split("/", 1)[1] for r in sorted(release.repos, key=lambda r: (r.created, r.id))]
        url = f"https://huggingface.co/{lead.id}"
        desc = f"{len(names)} 个仓库：" + "、".join(names[:6]) + ("等" if len(names) > 6 else "")
        if lead.pipeline:
            desc += f"（{lead.pipeline}）"
        items.append(ListItem(id=f"{author}/{release.family}@{release.created:%Y%m%d%H%M}", title=lead.id.split("/", 1)[1],
                              url=url, mobileUrl=url, author=author, desc=desc,
                              hot=sum(r.likes for r in release.repos),
                              timestamp=int(release.created.timestamp() * 1000)))
    return items
