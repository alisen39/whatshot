# 🔥 WhatsHot·什么火了

WhatsHot API 是热榜、实时快讯、金价和 RSS/RSSHub 来源的开源聚合核心。它提供
330+ 个自动发现路由、JSON/RSS 输出、双层缓存、CLI，以及供独立
`whatshot-mcp` 使用的 Backend Contract。

## 能力边界

| 能力 | 说明 |
| --- | --- |
| 聚合路由 | 热榜、快讯、金价与 RSS/RSSHub 来源 |
| Core HTTP API | 站点元信息、榜单数据、JSON 和 RSS 2.0 |
| Fetch Service | CLI、Scheduler、HTTP API 和 Backend Contract 共用的抓取路径 |
| 缓存 | Redis + 进程内 TTL，Redis 不可用时自动降级 |
| Scheduler | 仅采集显式配置的站点和 board |
| DuckDB 历史库 | 本地历史、关键词搜索、趋势和覆盖信息 |
| Backend Contract v1 | 独立 MCP 连接的版本化只读 HTTP 契约 |

Core 不包含 MCP Server，也不直接连接 PostgreSQL。

## 运行进程

| 端口 | 命令 | 职责 |
| --- | --- | --- |
| `6688` | `uv run python -m whats_hot_api` | Core API、JSON、RSS、响应缓存 |
| `6690` | `uv run whatshot daemon` | Scheduler、DuckDB、`/api/v1` Backend、内部 Control API |

两个进程互不依赖。只消费聚合 API 时启动 `6688`；使用定时采集、历史数据或
独立 MCP 的本地 Backend 时启动 `6690`。

## 安装与启动

要求 Python 3.12+ 和 [uv](https://docs.astral.sh/uv/)。

启动 Core API：

```bash
uv sync
uv run python -m whats_hot_api
```

启动 daemon：

```bash
cp config.example.toml config.toml
uv sync --extra daemon
uv run whatshot config validate -f json
uv run whatshot daemon
```

健康检查：

```bash
curl http://127.0.0.1:6688/all
curl http://127.0.0.1:6690/internal/v1/health
curl http://127.0.0.1:6690/api/v1/capabilities
```

## Core HTTP API

每个路由提供元信息端点和数据端点：

```text
GET /weibo
GET /weibo/hot
GET /bilibili/1
GET /acfun/1?range=WEEK
GET /all
GET /categories
```

通用查询参数：

```text
?rss=true          输出 RSS 2.0
?cache=false       跳过旧缓存并刷新
?cache=only        只读缓存，未命中返回 404
?limit=10          限制条目数
```

响应示例：

```json
{
  "code": 200,
  "name": "weibo",
  "title": "微博",
  "type": "热搜榜",
  "total": 50,
  "updateTime": "2026-08-16T12:00:00Z",
  "fromCache": true,
  "data": [
    {
      "id": "1",
      "title": "热搜标题",
      "hot": 999999,
      "url": "https://example.com"
    }
  ]
}
```

金价路由使用原生报价口径；币种和单位属于每条报价，Core 不做汇率或重量换算：

```text
GET /lukfook/mainland
GET /lukfook/hong-kong
GET /chow-taifook-hk/hot
GET /beijing-rtj/hot
```

```json
{
  "id": "gold-jewellery",
  "title": "999.9饰金",
  "metal": "gold",
  "quotes": [
    {
      "quoteType": "retail_sell",
      "label": "销售价",
      "price": 1319.5,
      "currency": "HKD",
      "unit": "gram",
      "sourceQuoteTime": "2026-08-10T18:28:12+08:00",
      "sourceQuoteTimeTrusted": true
    }
  ]
}
```

`metal` 可区分 `gold` / `silver` / `platinum` / `palladium`。`sellPrice` /
`recyclePrice` 暂时保留给旧客户端，但只会映射人民币/克报价。历史金价
序列按 `board + item + quoteType + currency + unit` 分开保存。

## 缓存配置

Core API 从 `.env` 读取缓存和上游请求配置：

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `PORT` | `6688` | Core API 端口 |
| `HOTLIST_CACHE_TTL` | `1800` | 热榜缓存秒数 |
| `NEWSFLASH_CACHE_TTL` | `300` | 快讯缓存秒数 |
| `REQUEST_TIMEOUT` | `6000` | 上游超时毫秒数 |
| `REDIS_HOST` | `127.0.0.1` | 留空时只用内存缓存 |
| `SOURCE_RSSHUB_BASE_URLS` | 空 | RSSHub 实例列表 |
| `ROUTE_PROXY` | 空 | 按域名关键词匹配的代理 JSON |

修改 `.env` 后重启 `6688`。

## daemon 配置

daemon 从本地 `config.toml` 读取设置。该文件由 `config.example.toml` 复制，已被
Git 忽略。

```toml
[daemon]
bind = "127.0.0.1"
port = 6690
state_path = "data/state"

[storage]
enabled = true
path = "data/whatshot.duckdb"
retention_days = 180
query_timeout_seconds = 5
cursor_ttl_seconds = 86400
checkpoint_on_shutdown = true

[scheduler]
enabled = true
max_fetch_concurrency = 4
writer_queue_size = 32

[backend_api]
max_result_items = 200
default_history_days = 7
max_history_days = 365
```

默认不采集任何来源。增加采集任务：

```toml
[[scheduler.jobs]]
id = "weibo-hot"
site = "weibo"
type = "hot"
interval = "10m"
limit = 50
enabled = true
run_on_start = true
```

`6690` 是 DuckDB 的唯一 owner。不得让其他进程直接打开同一数据库写入，也不要把
内部 Control API 直接暴露到公网。

## Backend Contract v1

daemon 为独立 `whatshot-mcp` 提供：

```text
GET  /api/v1/capabilities
GET  /api/v1/sources
GET  /api/v1/sources/{site}
POST /api/v1/current
POST /api/v1/current/batch
GET  /api/v1/history
GET  /api/v1/history/search
GET  /api/v1/history/trends
GET  /api/v1/coverage
```

`storage.enabled=false` 时只声明 `core-read`；启用历史存储后同时声明
`history-read`。Backend Contract 不提供 Scheduler trigger、数据库路径或写操作。

独立 MCP 的默认配置：

```toml
[backend]
url = "http://127.0.0.1:6690/api/v1"
```

AI 客户端连接 MCP 服务的 `http://127.0.0.1:6691/mcp`，不能把 `6690` 当作 MCP
endpoint。

## CLI

实时读取不需要启动任何服务：

```bash
uv run whatshot list -f json
uv run whatshot weibo hot -f json
uv run whatshot weibo hot --cache only
```

历史和 Scheduler 子命令通过正在运行的 daemon Control API 调用：

```bash
uv run whatshot history query --site weibo --board hot
uv run whatshot history search 关键词 --site weibo
uv run whatshot scheduler status -f json
uv run whatshot scheduler trigger weibo-hot -f json
```

CLI 不直接打开 DuckDB。

## 作为核心库嵌入

扩展项目通过 App Factory 注入配置、路由和生命周期钩子：

```python
from whats_hot_api.app import create_app
from whats_hot_api.config import Settings


class ExtSettings(Settings):
    MY_CUSTOM_KEY: str = ""


app = create_app(
    settings=ExtSettings(),
    extra_routers=[my_router],
    extra_startup=[my_startup],
    extra_shutdown=[my_shutdown],
    extra_route_packages=["my_ext.routes"],
    title="My Extended API",
)
```

## 新增路由

在 `whats_hot_api/routes/<category>/` 下增加模块，并导出：

```python
ROUTE_NAME = "example"
ROUTE_META = {
    "name": "example",
    "title": "Example",
    "description": "Example source",
    "link": "https://example.com",
    "params": None,
}


async def handle_route(request, no_cache):
    ...
```

分类子包的 `__init__.py` 导出 `CATEGORY` 和 `CATEGORY_LABEL`。路由由 registry
递归发现，不维护手工路由表。

## 测试

```bash
uv run pytest
uv run pytest tests/test_backend_contract_api.py -v
uv run pytest tests/test_daemon.py -v
```

变更 Backend Contract 时，还必须使用相邻 `whatshot-mcp/contracts` 制品运行
Contract 测试。

## 安全边界

- Core 数据路由只读。
- daemon 默认只绑定 loopback。
- Backend Contract 不接受任意 URL、SQL、文件路径或 Token 参数。
- DuckDB 单写者由 owner lock 保证。
- Redis 不可用时自动降级，不影响基本 API。

## License

MIT。第三方来源和授权说明见 `THIRD_PARTY_NOTICES.md`。
