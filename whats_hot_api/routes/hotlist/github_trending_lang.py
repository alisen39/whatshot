from __future__ import annotations

import asyncio
import re
from datetime import UTC, datetime
from html import unescape

from bs4 import BeautifulSoup
from starlette.requests import Request

from whats_hot_api.config import config
from whats_hot_api.models import ListItem, RouterData
from whats_hot_api.utils.cache import CacheData, cache
from whats_hot_api.utils.http_client import get
from whats_hot_api.utils.logger import logger

ROUTE_NAME = "github-trending-lang"

# 子榜键 -> (GitHub 显示名, URL 语言标识)。标识取自 /trending 页面语言下拉框;
# 3 个标识含 + / % 的语言改用字母写法:c++ -> cpp、c%23 -> csharp、objective-c++ -> objective-c++。
# python 放在最前:注册元数据把 type 的第一个值作为站点默认榜
LANGUAGES: dict[str, tuple[str, str]] = {
    "python": ("Python", "python"),
    "assembly": ("Assembly", "assembly"),
    "batchfile": ("Batchfile", "batchfile"),
    "bitbake": ("BitBake", "bitbake"),
    "blade": ("Blade", "blade"),
    "c": ("C", "c"),
    "csharp": ("C#", "c%23"),
    "cpp": ("C++", "c++"),
    "cmake": ("CMake", "cmake"),
    "css": ("CSS", "css"),
    "clojure": ("Clojure", "clojure"),
    "coffeescript": ("CoffeeScript", "coffeescript"),
    "common-lisp": ("Common Lisp", "common-lisp"),
    "crystal": ("Crystal", "crystal"),
    "cuda": ("Cuda", "cuda"),
    "cython": ("Cython", "cython"),
    "d": ("D", "d"),
    "dm": ("DM", "dm"),
    "dart": ("Dart", "dart"),
    "dockerfile": ("Dockerfile", "dockerfile"),
    "ejs": ("EJS", "ejs"),
    "elixir": ("Elixir", "elixir"),
    "emacs-lisp": ("Emacs Lisp", "emacs-lisp"),
    "erlang": ("Erlang", "erlang"),
    "fortran": ("Fortran", "fortran"),
    "gdscript": ("GDScript", "gdscript"),
    "glsl": ("GLSL", "glsl"),
    "go": ("Go", "go"),
    "groovy": ("Groovy", "groovy"),
    "hcl": ("HCL", "hcl"),
    "hlsl": ("HLSL", "hlsl"),
    "html": ("HTML", "html"),
    "handlebars": ("Handlebars", "handlebars"),
    "haskell": ("Haskell", "haskell"),
    "haxe": ("Haxe", "haxe"),
    "json": ("JSON", "json"),
    "java": ("Java", "java"),
    "javascript": ("JavaScript", "javascript"),
    "jsonnet": ("Jsonnet", "jsonnet"),
    "julia": ("Julia", "julia"),
    "jupyter-notebook": ("Jupyter Notebook", "jupyter-notebook"),
    "kotlin": ("Kotlin", "kotlin"),
    "llvm": ("LLVM", "llvm"),
    "lean": ("Lean", "lean"),
    "less": ("Less", "less"),
    "lua": ("Lua", "lua"),
    "matlab": ("MATLAB", "matlab"),
    "makefile": ("Makefile", "makefile"),
    "meson": ("Meson", "meson"),
    "nim": ("Nim", "nim"),
    "nix": ("Nix", "nix"),
    "ocaml": ("OCaml", "ocaml"),
    "objective-c": ("Objective-C", "objective-c"),
    "objective-cpp": ("Objective-C++", "objective-c++"),
    "odin": ("Odin", "odin"),
    "open-policy-agent": ("Open Policy Agent", "open-policy-agent"),
    "openscad": ("OpenSCAD", "openscad"),
    "php": ("PHP", "php"),
    "plpgsql": ("PLpgSQL", "plpgsql"),
    "pascal": ("Pascal", "pascal"),
    "perl": ("Perl", "perl"),
    "powershell": ("PowerShell", "powershell"),
    "qml": ("QML", "qml"),
    "r": ("R", "r"),
    "rich-text-format": ("Rich Text Format", "rich-text-format"),
    "roff": ("Roff", "roff"),
    "ruby": ("Ruby", "ruby"),
    "rust": ("Rust", "rust"),
    "scss": ("SCSS", "scss"),
    "scala": ("Scala", "scala"),
    "shaderlab": ("ShaderLab", "shaderlab"),
    "shell": ("Shell", "shell"),
    "smali": ("Smali", "smali"),
    "solidity": ("Solidity", "solidity"),
    "starlark": ("Starlark", "starlark"),
    "svelte": ("Svelte", "svelte"),
    "swift": ("Swift", "swift"),
    "systemverilog": ("SystemVerilog", "systemverilog"),
    "tcl": ("Tcl", "tcl"),
    "tex": ("TeX", "tex"),
    "typescript": ("TypeScript", "typescript"),
    "unknown": ("Unknown languages", "unknown"),
    "v": ("V", "v"),
    "vbscript": ("VBScript", "vbscript"),
    "vala": ("Vala", "vala"),
    "verilog": ("Verilog", "verilog"),
    "vim-script": ("Vim script", "vim-script"),
    "vue": ("Vue", "vue"),
    "webassembly": ("WebAssembly", "webassembly"),
    "xslt": ("XSLT", "xslt"),
    "yaml": ("YAML", "yaml"),
    "zenscript": ("ZenScript", "zenscript"),
    "zig": ("Zig", "zig"),
}

RANGES = {"daily": "日榜", "weekly": "周榜", "monthly": "月榜"}
# 页面 <title> 里时间范围的写法,用于确认 since 生效(GitHub 对不认识的 since 静默回退为日榜)
RANGE_IN_TITLE = {"daily": "today", "weekly": "this week", "monthly": "this month"}
PAGE_TITLE = re.compile(r"<title>\s*Trending\s*(.*?)\s*repositories on GitHub (today|this week|this month)")
NO_TRENDING = "have any trending repositories"

ROUTE_META: dict = {
    "name": ROUTE_NAME,
    "title": "GitHub",
    "description": "GitHub 按编程语言的 Trending 仓库(日榜 / 周榜 / 月榜)。",
    "link": "https://github.com/trending",
    "params": {
        "type": {
            "name": "编程语言",
            "type": {key: display for key, (display, _) in LANGUAGES.items()},
        },
        "range": {
            "name": "时间范围",
            "type": RANGES,
        },
    },
}


async def handle_route(request: Request, no_cache: bool = False) -> RouterData:
    type_param = request.query_params.get("type", "python")
    range_param = request.query_params.get("range", "daily")
    list_data = await _get_list(type_param, range_param, no_cache)
    return RouterData(
        **{**ROUTE_META, "link": list_data["link"]},
        type=f"{LANGUAGES[type_param][0]} · {RANGES[range_param]}",
        total=len(list_data["data"]),
        fromCache=list_data["from_cache"],
        updateTime=list_data["update_time"],
        data=list_data["data"],
        message=list_data.get("message"),
    )


async def _get_list(type_param: str, range_param: str, no_cache: bool) -> dict:
    if type_param not in LANGUAGES:
        raise ValueError(
            f"Unknown language '{type_param}' for route '{ROUTE_NAME}'. "
            f"See /{ROUTE_NAME} for the supported language list."
        )
    if range_param not in RANGES:
        raise ValueError(
            f"Unknown range '{range_param}' for route '{ROUTE_NAME}'. "
            f"Supported values: {sorted(RANGES)}."
        )
    url = f"https://github.com/trending/{LANGUAGES[type_param][1]}?since={range_param}"

    if not no_cache:
        cached = await cache.get(url)
        if cached:
            logger.info("💾 [CACHE] The request is cached")
            return {
                "from_cache": True,
                "update_time": cached.update_time,
                "data": cached.data or [],
                "link": url,
                "message": None,
            }

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    }
    max_retries = 3
    last_error: Exception | None = None
    for i in range(max_retries):
        try:
            result = await get(url=url, no_cache=True, response_type="text", headers=headers)
            page = result.data
            _verify_language_page(page, type_param, range_param, url)

            repos = []
            for el in BeautifulSoup(page, "lxml").select("article.Box-row"):
                anchor = el.select_one("h2 a")
                if not anchor:
                    continue
                href = str(anchor.get("href") or "")
                parts = href.strip("/").split("/")
                if len(parts) != 2:
                    continue
                desc_el = el.select_one("p.col-9.color-fg-muted")
                stars_el = el.select_one('a[href$="/stargazers"]')
                stars_text = stars_el.get_text().strip().replace(",", "") if stars_el else ""
                repos.append({
                    "owner": parts[0],
                    "repo": parts[1],
                    "path": f"/{parts[0]}/{parts[1]}",
                    "desc": desc_el.get_text().strip() if desc_el else "",
                    "stars": int(stars_text) if stars_text.isdigit() else None,
                })

            if not repos and NO_TRENDING not in page:
                raise RuntimeError(f"GitHub page structure changed: no repositories parsed ({url})")

            update_time = datetime.now(UTC).isoformat()
            await cache.set(url, CacheData(update_time=update_time, data=repos), config.HOTLIST_CACHE_TTL)
            logger.info("✅ request was successful")
            data = [
                ListItem(
                    id=v["path"],
                    title=v["repo"],
                    url=f"https://github.com{v['path']}",
                    mobileUrl=f"https://github.com{v['path']}",
                    author=v["owner"],
                    desc=v["desc"] or None,
                    hot=v["stars"],
                    hotLabel="stars",
                    sourceRank=position,
                )
                for position, v in enumerate(repos, start=1)
            ]
            message = None
            if not repos:
                message = f"GitHub 当前没有 {LANGUAGES[type_param][0]} 的 Trending 仓库"
            return {
                "from_cache": False,
                "update_time": update_time,
                "data": data,
                "link": url,
                "message": message,
            }
        except Exception as e:
            last_error = e
            logger.error(f"❌ [ERROR] attempt {i + 1} failed: {e}")
            if i < max_retries - 1:
                await asyncio.sleep(2**i)
    raise last_error or Exception("request failed")


def _verify_language_page(page: str, type_param: str, range_param: str, url: str) -> None:
    """核对页面 <title>:语言标识写错会 200 落到别的语言页(如 c# 被当 URL 片段请求到 C),
    since 写错会静默回退为日榜;两种都算抓错了榜,报错而不是输出错误列表。"""
    matched = PAGE_TITLE.search(page)
    if not matched:
        raise RuntimeError(f"GitHub page structure changed: no Trending title ({url})")
    shown = unescape(matched.group(1)).strip()
    expected = "Unknown" if type_param == "unknown" else LANGUAGES[type_param][0]
    if shown.casefold() != expected.casefold():
        raise RuntimeError(f"GitHub page shows {shown!r} trending, expected {expected!r} ({url})")
    if matched.group(2) != RANGE_IN_TITLE[range_param]:
        raise RuntimeError(
            f"GitHub ignored since={range_param}, page shows {matched.group(2)!r} ({url})"
        )
