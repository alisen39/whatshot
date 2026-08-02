<div align="center">

# 🔥 WhatsHot API

**统一聚合热榜、实时快讯、金价与 RSS 数据，并提供稳定、易于消费的 API。**

![Python](https://img.shields.io/badge/Python-3.12%2B-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-async-009688?logo=fastapi&logoColor=white)
![Output](https://img.shields.io/badge/Output-JSON%20%7C%20RSS-FF6600?logo=rss&logoColor=white)
![Routes](https://img.shields.io/badge/Routes-330%2B-EA4AAA)

[项目简介](#项目简介) · [基本使用](#基本使用) · [进阶使用](#进阶使用) · [扩展开发](#扩展开发)

</div>

## 项目简介

WhatsHot API 是一个基于 Python 与 FastAPI 构建的开源数据聚合服务，核心覆盖
**热榜、实时快讯和金价**。它将不同来源的数据抓取、解析并归一化为一致的
数据结构，让网站、机器人、信息面板、研究工具或个人自动化无需分别维护
大量适配逻辑。

项目当前包含 **330+ 个自动发现的聚合路由**，覆盖热门榜单、滚动快讯、
金价与 RSS/RSSHub 聚合内容。它既可以作为独立 API 服务运行，也可以通过
App Factory 作为核心库嵌入其他 FastAPI 项目。

```text
热榜 / 快讯 / 金价 / RSS
          ↓
   自动发现的路由适配器
          ↓
异步请求 · 双层缓存 · 数据归一化
          ↓
       JSON / RSS 2.0
```

## 核心功能

| 功能 | 说明 |
| --- | --- |
| 多类型内容聚合 | 统一处理热榜、实时快讯、金价与 RSS/RSSHub 来源 |
| 路由自动发现 | 自动扫描分类目录，新增适配器无需手动登记路由 |
| 异步请求 | 基于 `httpx` 的异步 HTTP 客户端，支持 HTTP/2 与按域名代理 |
| 只读缓存模式 | 可强制只读缓存，未命中时直接返回，不向上游发起请求 |
| JSON / RSS 输出 | 同一数据端点可输出 JSON，也可按需生成 RSS 2.0 |
| OpenCLI 风格 CLI | 通过 `whatshot <site> <type>` 读取任意已注册来源，支持 7 种输出格式 |
| DuckDB 历史库 | 可选的本地分析数据库，支持历史查询、搜索和趋势分析 |
| 轻量 Scheduler | 只抓取用户显式订阅的站点和 board，负责全部历史写入 |
| MCP v2 | 提供 stdio 和 Streamable HTTP，只暴露结构化只读工具 |

## 运行进程与端口

WhatsHot 有两个可以独立启动的进程，分别承担无状态 API 和有状态数据能力：

| 默认端口 | 启动命令 | 提供的能力 | 是否依赖另一个端口 |
| --- | --- | --- | --- |
| `6688` | `uvx --from . whats-hot-api` | Core HTTP API、JSON、RSS、API 响应缓存 | 不依赖 `6690` |
| `6690` | `uv run whatshot daemon` | Scheduler、DuckDB、历史查询、MCP、内部 Control API | 不依赖 `6688` |

按用途选择需要启动的进程：

| 使用场景 | 启动 `6688` | 启动 `6690` |
| --- | --- | --- |
| 只通过 HTTP 调用实时热榜、快讯或 RSS | 是 | 否 |
| 只使用 CLI 获取实时数据 | 否 | 否 |
| 使用定时采集或历史查询 | 否 | 是 |
| 使用 MCP 实时或历史工具 | 否 | 是 |
| 同时对外提供 API，并使用历史数据或 MCP | 是 | 是 |

Scheduler 和 MCP 的实时抓取直接复用项目内部 Fetch Service，不会通过
`6688` 转发，因此使用 `6690` 时不需要额外启动 Core API。反过来，只启动
`6688` 也不会创建 DuckDB 或启动 Scheduler。`6690` 是本地控制端口，默认
只绑定 `127.0.0.1`，不应直接暴露到公网。

## 基本使用

基本模式只运行聚合 API：不连接 Redis、不保存历史数据，也不启动
Scheduler、DuckDB 或 MCP。下面的请求使用 `cache=false`，每次都会实时访问
对应上游。

### 1. 环境要求

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)

### 2. 直接启动 API

`uvx --from .` 会从当前源码创建并缓存隔离的工具环境，无需先执行
`uv sync`：

```bash
REDIS_HOST="" \
CACHE_TTL=0 \
HOTLIST_CACHE_TTL=0 \
NEWSFLASH_CACHE_TTL=0 \
USE_LOG_FILE=false \
uvx --from . whats-hot-api
```

也可以把这些变量写入 `.env`，然后直接运行：

```bash
uvx --from . whats-hot-api
```

服务默认监听 `http://127.0.0.1:6688`。这个入口只启动 Core API，不会创建
DuckDB，也不会定时抓取或保存历史数据；基本模式不需要启动 `6690`。
`6688` 可以通过 `.env` 中的 `PORT` 修改。

### 3. 调用 API

先查看全部来源和分类：

```bash
curl http://127.0.0.1:6688/all
curl http://127.0.0.1:6688/categories
```

路由规则：

| 请求 | 作用 |
| --- | --- |
| `GET /all` | 查看全部聚合路由及其分类 |
| `GET /categories` | 查看按内容类型聚合的路由目录 |
| `GET /<route>` | 获取路由元信息、可用类型和参数，不请求上游 |
| `GET /<route>/<type>` | 获取指定类型的榜单或快讯数据 |

例如：

```bash
curl http://127.0.0.1:6688/weibo
curl "http://127.0.0.1:6688/weibo/hot?limit=10&cache=false"
```

没有多类型参数的来源统一使用 `hot`。基本模式常用的查询参数：

| 参数 | 示例 | 说明 |
| --- | --- | --- |
| `limit` | `?limit=10` | 限制返回条目数，范围为 1–200 |
| `rss` | `?rss=true` | 输出 RSS 2.0 |

响应示例：

```json
{
  "code": 200,
  "kind": "hotlist",
  "name": "example",
  "title": "示例榜单",
  "type": "热门",
  "total": 2,
  "fromCache": false,
  "updateTime": "2026-07-30T12:00:00Z",
  "data": [
    {
      "id": "1",
      "title": "示例内容",
      "url": "https://example.com/item/1",
      "mobileUrl": "https://example.com/item/1",
      "hot": 10000,
      "timestamp": 1785412800000
    }
  ]
}
```

其中，条目级 `timestamp` 统一为 Unix 毫秒时间戳；响应级 `updateTime` 为本次榜单数据的刷新时间。

## 进阶使用

进阶能力按需开启。API 进程和 daemon 使用不同的配置文件，修改后需要重启
对应进程：

| 能力 | 在哪里开启 | 需要启动 | 是否持久化 |
| --- | --- | --- | --- |
| API 响应缓存 | 仓库根目录 `.env` | Core API（`6688`） | 内存不持久化；Redis 可跨进程 |
| DuckDB 历史数据 | 本地 `config.toml` 的 `[storage]` | daemon（`6690`） | 是 |
| Scheduler | 本地 `config.toml` 的 `[scheduler]` 和 `[[scheduler.jobs]]` | daemon（`6690`） | 负责写入 DuckDB |
| CLI 实时读取 | 无需开启，直接执行 `whatshot <site> <type>` | 无 | 不写数据 |
| CLI 历史查询 | 本地 `config.toml` | daemon（`6690`） | 只读 |
| MCP | 本地 `config.toml` 的 `[mcp]`，另在 MCP 客户端填写连接地址 | daemon（`6690`） | 只读 |

### 1. 开启 API 响应缓存

响应缓存与历史数据是两套独立能力。响应缓存用于降低上游压力，不会形成可
查询的时间序列。

缓存配置写在仓库根目录的 `.env`，不是 `config.toml`。首次配置时：

```bash
cd /path/to/whats-hot-api
cp .env.example .env
```

然后编辑 `./.env`。只使用当前 API 进程的内存缓存时配置：

```dotenv
REDIS_HOST=
CACHE_TTL=1800
HOTLIST_CACHE_TTL=1800
NEWSFLASH_CACHE_TTL=300
```

需要多个 API 实例共享缓存时，再配置 Redis：

```dotenv
REDIS_HOST=127.0.0.1
REDIS_PORT=6379
REDIS_PASSWORD=
REDIS_DB=0
```

保存 `.env` 后，启动或重启 Core API 才会生效：

```bash
uvx --from . whats-hot-api
```

缓存服务监听 Core API 的 `6688` 端口，不需要启动 `6690` daemon。也可以用
同名环境变量临时覆盖 `.env` 中的值。

Redis 不可用时会自动降级为最多 100 条的进程内 TTL 缓存。单次请求可以
显式控制缓存策略：

```bash
curl "http://127.0.0.1:6688/weibo/hot?cache=false" # 跳过旧缓存并刷新
curl "http://127.0.0.1:6688/weibo/hot?cache=only"  # 只读缓存，未命中返回 404
```

### 2. 定时保存历史数据

历史数据由轻量 Scheduler 定时抓取并写入 DuckDB。只有 Scheduler 能写库；
普通 API 请求、实时 CLI 和 MCP `fetch_current` 都不会形成历史记录。

daemon、Scheduler、历史 CLI 和 MCP 统一读取仓库根目录的本地配置：

```text
./config.toml
```

仓库提交 `config.example.toml` 作为配置模板；`config.toml` 已加入
`.gitignore`，可以安全保存本机路径和采集任务。首次使用时创建本地配置：

```bash
cp config.example.toml config.toml
```

它们不会各自维护配置文件。在仓库根目录运行命令时会自动发现该文件，后续
命令不需要重复传 `--config`。配置中的相对路径以 `config.toml` 所在目录为
基准，不受启动命令所在位置影响。修改 `config.toml` 后需要重启 `6690`
daemon 才会生效。

先安装 daemon 所需的 DuckDB 和 MCP 可选依赖：

```bash
uv sync --extra daemon
```

检查本地配置：

```bash
uv run whatshot config validate -f json
```

新建的本地配置默认不采集任何站点。按需在 `config.toml` 中加入 job 后，
只有显式列出且 `enabled=true` 的 job 会被采集：

```toml
[storage]
enabled = true

[scheduler]
enabled = true

[[scheduler.jobs]]
id = "weibo-hot"
site = "weibo"
type = "hot"
interval = "10m"
limit = 50
enabled = true
```

启动 daemon：

```bash
uv run whatshot daemon
```

daemon 默认监听 `127.0.0.1:6690`，负责 Scheduler、DuckDB、历史查询
Control API 和 MCP Streamable HTTP。该命令以前台方式持续运行，不返回 shell
提示符是正常现象。daemon 自己完成 Scheduler 和 MCP 所需的实时抓取，不要求
`6688` 正在运行。请保持这个终端运行，并在另一个终端检查健康状态：

```bash
curl http://127.0.0.1:6690/internal/v1/health
```

健康响应中的 `history.enabled` 和 `scheduler.running` 应为 `true`。
`scheduler.jobs` 为空表示 daemon 工作正常、但当前没有配置采集任务。多个
job 可以并发抓取，但所有 capture 都通过单 writer queue 串行写入。

调度管理：

```bash
uv run whatshot scheduler jobs
uv run whatshot scheduler status -f json
uv run whatshot scheduler trigger weibo-hot -f json
uv run whatshot scheduler trigger weibo-hot --no-wait -f json
```

历史查询：

```bash
uv run whatshot history query \
  --site weibo --board hot --since 2026-07-01T00:00:00Z -f json

uv run whatshot history search "人工智能" \
  --site weibo --since 2026-07-01T00:00:00Z -f json

uv run whatshot history trend \
  --site weibo --board hot --item-id "条目 ID" --bucket 1h -f json

uv run whatshot history stats -f json
```

默认路径：

| 类型 | 路径 |
| --- | --- |
| 配置 | `./config.toml` |
| DuckDB | `./data/whatshot.duckdb` |
| DuckDB WAL | `./data/whatshot.duckdb.wal` |
| daemon 状态 | `./data/state/` |

这里的 `./` 都相对于仓库根目录的 `config.toml`。`data/` 已加入
`.gitignore`，数据库、WAL 和运行状态只保存在本地，不会提交到 Git。
需要把数据持久化到宿主机时，挂载整个仓库 `data/` 目录即可，例如容器内
使用：

```toml
[storage]
enabled = true
path = "data/whatshot.duckdb"
```

daemon 运行期间，DuckDB 旁边可能出现 `whatshot.duckdb.wal`，这是正常的
预写日志；应将整个 `data/` 挂载到同一个本地目录，并通过正常停止 daemon
完成 checkpoint。

`storage.enabled=false` 会完全关闭持久化，不创建或打开 DuckDB/WAL。实时
CLI、Core HTTP 和 MCP `fetch_current` 仍可使用；历史查询返回
`HISTORY_DISABLED`。关闭存储时不能配置启用状态的 Scheduler job。

下一迭代计划将最近至少 7 天保存在 DuckDB，每天 01:00 把更早的完整自然日
归档为 `archive/YYYY/MM/YYYY-MM-DD.parquet`，并以单一 `data_dir` 支持本地
目录或容器 volume 挂载。该归档能力尚未实现。

完整架构、Schema、事务和验收标准见
[技术方案](../TECHNICAL_DESIGN_CLI_MCP_HISTORY_SCHEDULER.md)。

### 3. 使用 CLI

基础包已经包含 `whatshot` 入口。CLI 动态读取 Core 路由目录，不维护第二份
站点清单；使用 `uvx --from .` 可以直接从当前源码运行。

```bash
# 查看站点和参数，不请求上游
uvx --from . whatshot list -f json
uvx --from . whatshot describe bilibili -f yaml

# OpenCLI 风格实时读取，不写入历史库
uvx --from . whatshot weibo hot --limit 10
uvx --from . whatshot bilibili 1 --limit 10 -f json
uvx --from . whatshot acfun 1 --param range=WEEK -f table

# 来源名与 history/config 等内置命令重名时使用无歧义入口
uvx --from . whatshot fetch history hot -f json
```

支持 `table`、`plain`、`json`、`jsonl`、`yaml`、`markdown` 和 `csv`。
TTY 默认输出 table，管道默认输出 YAML。需要完整响应元数据时使用：

```bash
uvx --from . whatshot weibo hot --envelope -f json
```

CLI 的实时缓存策略：

```bash
uvx --from . whatshot weibo hot --cache prefer
uvx --from . whatshot weibo hot --cache refresh
uvx --from . whatshot weibo hot --cache only
```

成功数据只写 stdout，错误只写 stderr。自动化可以通过
`--error-format json` 或 `yaml` 获取结构化错误。`history` 和 `scheduler`
子命令通过 Control API 调用正在运行的 daemon，CLI 本身不会打开或写入
DuckDB。

### 4. 使用 MCP

MCP 使用 Python SDK v2，只提供结构化读取工具：

- `list_sources`
- `get_source_schema`
- `fetch_current`
- `query_history`
- `search_history`
- `get_trend_series`
- `get_storage_stats`

不提供 SQL、历史写入、删除或调度触发工具。

MCP、daemon、Scheduler 和 CLI 复用仓库根目录同一份 `config.toml`，不要为
MCP 创建第二份业务配置。如果前面已经启动了保存历史数据的 daemon，可以
直接使用 MCP；Claude Code、Codex、Cursor 或 CC Switch 中填写的内容只是
MCP 连接地址。

只需要实时 MCP、不需要 DuckDB 时，在现有 `config.toml` 中关闭存储和
Scheduler，并确保没有任何 `[[scheduler.jobs]]`：

```toml
[storage]
enabled = false

[scheduler]
enabled = false

[mcp]
enabled = true
```

安装 MCP 依赖，然后用同一份配置校验并启动 daemon：

```bash
uv sync --extra mcp
uv run whatshot config validate -f json
uv run whatshot daemon
```

修改配置前如果已有 daemon 正在运行，请先正常停止它，再用新配置重启。
daemon 是前台常驻进程，因此启动后终端不返回提示符是正常现象。

stdio 模式是 daemon 的轻量代理，因此必须先启动 daemon。然后在另一个终端
运行：

```bash
uv run whatshot-mcp
# 等价：
uv run whatshot mcp
```

Streamable HTTP 由 daemon 直接提供：

```text
http://127.0.0.1:6690/mcp
```

MCP 客户端应连接 `6690/mcp`，不要连接 Core API 的 `6688`。无论使用实时
工具还是历史工具，MCP 都只要求 daemon；不需要另外启动 Core API。

下面四种客户端均推荐连接这个 Streamable HTTP 地址。配置前先确认 daemon
健康：

```bash
curl http://127.0.0.1:6690/internal/v1/health
```

如果 `storage.enabled=false`，实时工具仍可使用，但历史工具会返回
`HISTORY_DISABLED`。

#### Claude Code

添加为当前用户的全局 MCP：

```bash
claude mcp add \
  --transport http \
  --scope user \
  whatshot \
  http://127.0.0.1:6690/mcp

claude mcp list
```

如果希望配置随项目共享，把 `--scope user` 改为 `--scope project`。对应的
项目级 `.mcp.json` 为：

```json
{
  "mcpServers": {
    "whatshot": {
      "type": "http",
      "url": "http://127.0.0.1:6690/mcp"
    }
  }
}
```

进入 Claude Code 后可用 `/mcp` 检查连接状态。配置格式参考
[Claude Code MCP 文档](https://code.claude.com/docs/en/mcp)。

#### Codex

命令行添加：

```bash
codex mcp add whatshot --url http://127.0.0.1:6690/mcp
codex mcp list
```

也可以编辑用户级 `~/.codex/config.toml`，或在可信项目中使用
`.codex/config.toml`：

```toml
[mcp_servers.whatshot]
url = "http://127.0.0.1:6690/mcp"
enabled = true
```

Codex CLI、Codex IDE 扩展和同一主机上的 Codex App 共用这份 MCP 配置。
重启客户端后用 `/mcp` 检查。配置格式参考
[Codex MCP 文档](https://learn.chatgpt.com/docs/extend/mcp)。

#### Cursor

全局配置写入 `~/.cursor/mcp.json`；只在当前项目使用时写入
`<project>/.cursor/mcp.json`：

```json
{
  "mcpServers": {
    "whatshot": {
      "url": "http://127.0.0.1:6690/mcp"
    }
  }
}
```

重启 Cursor 后，在 **Settings → Tools & MCP** 中确认 `whatshot` 已连接。
Cursor Agent CLI 也会读取同一配置，可用以下命令验证：

```bash
cursor-agent mcp list
cursor-agent mcp list-tools whatshot
```

配置格式参考
[Cursor MCP 文档](https://docs.cursor.com/context/model-context-protocol)。

#### CC Switch

CC Switch 是 MCP 配置管理器，不是独立的 MCP 客户端：

1. 打开顶部 **MCP** 面板，点击右上角 **+**；
2. Preset 选择 **Custom**；
3. Server ID 填写 `whatshot`；
4. Transport Type 选择 `http`；
5. URL 填写 `http://127.0.0.1:6690/mcp`；
6. 按需打开 **Claude** 和 **Codex** App Binding；
7. 保存后重启对应 CLI 或客户端。

CC Switch 会分别同步到 `~/.claude.json` 的 `mcpServers` 和
`~/.codex/config.toml` 的 `[mcp_servers]`。当前 CC Switch 不负责同步 Cursor，
因此 Cursor 仍需使用上一节的 `mcp.json`。操作说明参考
[CC Switch MCP Server Management](https://github.com/farion1231/cc-switch/blob/main/docs/user-manual/en/3-extensions/3.1-mcp.md)。

#### stdio 备选方式

四种工具也可以通过本地 stdio 代理连接，但 stdio 代理仍然只会转发到正在
运行的 daemon。把 `/absolute/path/to/whats-hot-api` 替换为本仓库绝对路径：

```json
{
  "mcpServers": {
    "whatshot": {
      "command": "uv",
      "args": [
        "run",
        "--directory",
        "/absolute/path/to/whats-hot-api",
        "whatshot-mcp"
      ]
    }
  }
}
```

Claude Code、Cursor 和 CC Switch 可直接使用这段 JSON 中的 server 定义。
Codex 对应配置为：

```toml
[mcp_servers.whatshot]
command = "uv"
args = [
  "run",
  "--directory",
  "/absolute/path/to/whats-hot-api",
  "whatshot-mcp",
]
```

默认只绑定 loopback。需要远程访问时，应由反向代理提供 TLS 和认证，不要
直接把 Control API 暴露到公网。

### 5. API 配置参考

复制 `.env.example` 后按需修改。未使用的可选能力可以保持为空。

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `PORT` | `6688` | 服务端口 |
| `HOTLIST_CACHE_TTL` | `1800` | 热榜缓存时长，单位为秒 |
| `NEWSFLASH_CACHE_TTL` | `300` | 快讯缓存时长，单位为秒 |
| `REQUEST_TIMEOUT` | `6000` | 上游请求超时，单位为毫秒 |
| `REDIS_HOST` | `127.0.0.1` | Redis 地址；不可用时自动降级 |
| `SOURCE_RSSHUB_BASE_URLS` | 空 | RSSHub 实例地址，可填写多个 |
| `ROUTE_PROXY` | 空 | 按域名关键词匹配的代理 JSON |
| `RSS_MODE` | `false` | 是否默认输出 RSS |

完整配置项与注释请查看 [`.env.example`](./.env.example)。

## 扩展开发

### 作为核心库嵌入

`create_app()` 支持注入自定义配置、Router、生命周期钩子和额外路由包：

```python
from fastapi import APIRouter

from whats_hot_api.app import create_app
from whats_hot_api.config import Settings


class CustomSettings(Settings):
    CUSTOM_KEY: str = ""


custom_router = APIRouter(prefix="/api")

app = create_app(
    settings=CustomSettings(),
    extra_routers=[custom_router],
    extra_route_packages=["my_extension.routes"],
    title="My WhatsHot Service",
)
```

### 新增聚合路由

在 `whats_hot_api/routes/<category>/` 下新增模块，并导出：

- `ROUTE_NAME`：对外路由名称；
- `ROUTE_META`：静态元信息和可用参数；
- `async handle_route(request, no_cache) -> RouterData`：数据抓取与解析函数。

注册器会自动发现模块，并生成元信息与数据端点。新增分类时，还需要在 `whats_hot_api/routes/_base.py` 中登记分类并创建对应子包。

### 运行测试

`uvx` 用于普通用户的一次性运行；项目开发和测试需要复用项目环境，因此
这里使用 `uv run`：

```bash
uv run pytest
```

需要访问真实上游的端到端测试默认不会运行；普通测试不会主动访问公网。

## 安全与使用说明

- `ALLOWED_DOMAIN` 使用英文逗号分隔允许的浏览器 Origin；核心服务不会启用携带凭据的 CORS。
- `cache=only` 适合不允许触发上游请求的公开读取场景。
- 上游接口、字段与可用性可能随时变化，请为生产使用设置合理的缓存、超时、限流与错误处理。
- 本项目仅对公开信息进行技术性聚合，不代表与任何数据来源存在隶属、授权或合作关系。使用者应自行遵守数据来源的服务条款、robots 规则及所在地区法律法规。

## 致谢与引用

WhatsHot API 的早期实现、聚合适配器与部分协议解析参考或迁移自以下开源项目。感谢这些项目的作者与贡献者。

以下列表只保留主要项目级引用，不展开到具体数据来源。

| 项目 | 在本项目中的引用 |
| --- | --- |
| [imsyy/DailyHotApi](https://github.com/imsyy/DailyHotApi) | 早期 API 设计与聚合路由的 Python/FastAPI 重写基础 |
| [nexmoe/opentrends](https://github.com/nexmoe/opentrends) | RSS/RSSHub 聚合来源、数据结构与适配逻辑参考 |
| [DIYgod/RSSHub](https://github.com/DIYgod/RSSHub) | RSS 路由生态与聚合能力 |
| [jackwener/OpenCLI](https://github.com/jackwener/OpenCLI) | 公开接口参数、字段映射与适配实现参考 |
| [akfamily/akshare](https://github.com/akfamily/akshare) | 部分令牌生成逻辑的代码来源 |

其他用于接口校验和交叉验证的项目不在此重复展开；涉及代码移植的版权与许可证声明见 [Third-Party Notices](./THIRD_PARTY_NOTICES.md)。
