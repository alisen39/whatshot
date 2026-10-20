"""Collapse an organization's Hugging Face repos into releases.

One launch usually creates many sibling repos (sizes, FP8/GGUF/MLX exports,
base/instruct variants), sometimes days apart. Rules (validated 2026-10-19 on
16 official orgs, last 12 months):

1. Each repo is primary, quant (same-org quantized/format export) or a
   third-party derivative (baseModels points at another org).
2. Family key: lower-cased name split on -/_, org prefix dropped; leading tokens
   up to and including the first version token, stopping at size, quant, variant
   or date tokens, at most three.
3. Within a family, repos created within WINDOW of the first one form one release.
4. A quant-only group within LATE_WINDOW after a release of the same family joins it.
5. Groups made only of third-party derivatives are not releases.

createdAt is the repo creation time and can precede the public release.
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta

WINDOW = timedelta(hours=48)
LATE_WINDOW = timedelta(days=30)
QUANT = {"fp8", "fp4", "nvfp4", "mxfp4", "mxfp8", "int4", "int8", "w4a16", "w8a8", "w4a8", "awq", "gptq", "gguf",
         "mlx", "onnx", "bnb", "4bit", "8bit", "qat", "unquantized", "dspark", "dflash", "dflash2", "eagle", "eagle3",
         "mtp", "q4", "q8", "exl2", "nf4"}
PRECISION = {"bf16", "fp16", "fp32"}
VARIANT = {"base", "instruct", "chat", "it", "pt", "thinking", "think", "reasoning", "sft", "rl", "dpo", "flash", "pro",
           "mini", "nano", "lite", "turbo", "max", "plus", "super", "ultra", "tiny", "small", "medium", "large",
           "preview", "exp", "vl", "omni", "tts", "asr", "audio", "embed", "embedding", "rerank", "vision", "coder",
           "code", "math", "distill", "next"}
_SIZE = re.compile(r"^(\d+(\.\d+)?[bmkt]|a\d+(\.\d+)?b|e\d+b|\d+x\d+b)$")
_DATE = re.compile(r"^(\d{4}|\d{6}|\d{8})$")
_VERSION = re.compile(r"^(v?\d+(\.\d+)+|v\d+|[a-z]+v?\d+(\.\d+)*)$")


@dataclass
class Repo:
    id: str
    created: datetime
    kind: str  # primary | quant | derivative
    likes: int = 0
    downloads: int = 0
    pipeline: str | None = None


@dataclass
class Release:
    family: str
    repos: list[Repo] = field(default_factory=list)

    @property
    def created(self) -> datetime:
        return min(r.created for r in self.repos)

    @property
    def representative(self) -> Repo:
        primary = [r for r in self.repos if r.kind == "primary"] or self.repos
        return min(primary, key=lambda r: (r.created, len(r.id), r.id))

    @property
    def is_release(self) -> bool:
        return any(r.kind != "derivative" for r in self.repos)


def _tokens(name: str, org: str) -> list[str]:
    tokens = [t for t in re.split(r"[-_]", name.lower()) if t]
    return tokens[1:] if len(tokens) > 1 and tokens[0] == org.lower() else tokens


def family(name: str, org: str) -> str:
    out: list[str] = []
    for token in _tokens(name, org):
        stop = token in QUANT or token in PRECISION or token in VARIANT or _SIZE.match(token) or _DATE.match(token)
        if out and stop:
            break
        out.append(token)
        if _VERSION.match(token) and not token.isalpha() or len(out) >= 3:
            break
    return "-".join(out)


def classify(model: dict, org: str) -> str:
    base = model.get("baseModels") if isinstance(model.get("baseModels"), dict) else None
    owners = {m.get("id", "").split("/")[0].lower() for m in (base or {}).get("models") or [] if isinstance(m, dict)}
    if owners - {org.lower()}:
        return "derivative"
    name = model["id"].split("/", 1)[-1]
    if any(t in QUANT for t in _tokens(name, org)[1:]) or "gguf" in (model.get("tags") or []) \
            or (base or {}).get("relation") == "quantized":
        return "quant"
    return "primary"


def _created(value: object) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def group(models: list[dict], org: str) -> list[Release]:
    """Releases newest first."""
    families: dict[str, list[Repo]] = defaultdict(list)
    for model in models:
        created = _created(model.get("createdAt"))
        if not isinstance(model.get("id"), str) or "/" not in model["id"] or created is None:
            continue
        repo = Repo(model["id"], created, classify(model, org), int(model.get("likes") or 0),
                    int(model.get("downloads") or 0), model.get("pipeline_tag"))
        families[family(model["id"].split("/", 1)[1], org)].append(repo)
    releases: list[Release] = []
    for key, repos in families.items():
        repos.sort(key=lambda r: (r.created, r.id))
        groups: list[Release] = []
        for repo in repos:
            if groups and repo.created - groups[-1].repos[0].created <= WINDOW:
                groups[-1].repos.append(repo)
                continue
            late = repo.kind == "quant" and repo.created - groups[-1].repos[0].created <= LATE_WINDOW if groups else False
            if late and any(r.kind == "primary" for r in groups[-1].repos):
                groups[-1].repos.append(repo)  # Late GGUF/FP8 export of the previous release.
                continue
            groups.append(Release(key, [repo]))
        releases += groups
    return sorted((r for r in releases if r.is_release), key=lambda r: (r.created, r.family), reverse=True)
