# 定时采集与历史数据

Core API 只返回“此刻”的榜单。需要按计划采集、保存历史、关键词搜索或给
[whatshot-mcp](https://github.com/alisen39/whatshot-mcp) 提供本地数据时，启动 daemon。

## 运行进程

| 端口 | 命令 | 职责 |
| --- | --- | --- |
| `6688` | `uv run python -m whats_hot_api` | Core API、JSON、RSS、响应缓存 |
| `6690` | `uv run whatshot daemon` | Scheduler、DuckDB、`/api/v1` Backend、内部 Control API |

两个进程互不依赖。只消费聚合 API 时启动 `6688`；使用定时采集、历史数据或
独立 MCP 的本地 Backend 时启动 `6690`。Core 不包含 MCP Server，也不直接连接
PostgreSQL。

## 启动

```bash
cp config.example.toml config.toml
uv sync --extra daemon
uv run whatshot config validate -f json
uv run whatshot daemon
```

健康检查：

```bash
curl http://127.0.0.1:6690/internal/v1/health
curl http://127.0.0.1:6690/api/v1/capabilities
```

## 配置

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

## 命令行

历史和 Scheduler 子命令通过正在运行的 daemon Control API 调用，CLI 不直接打开
DuckDB：

```bash
uv run whatshot history query --site weibo --board hot
uv run whatshot history search 关键词 --site weibo
uv run whatshot scheduler status -f json
uv run whatshot scheduler trigger weibo-hot -f json
```

## Backend Contract v1

daemon 为独立 `whatshot-mcp` 提供版本化只读 HTTP 契约：

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

## 接入 MCP

独立 MCP 的默认配置：

```toml
[backend]
url = "http://127.0.0.1:6690/api/v1"
```

AI 客户端连接 MCP 服务的 `http://127.0.0.1:6691/mcp`，不能把 `6690` 当作 MCP
endpoint。安装与客户端配置见
[whatshot-mcp](https://github.com/alisen39/whatshot-mcp)。

## 安全边界

- Core 数据路由只读。
- daemon 默认只绑定 loopback。
- Backend Contract 不接受任意 URL、SQL、文件路径或 Token 参数。
- DuckDB 单写者由 owner lock 保证。
- Redis 不可用时自动降级，不影响基本 API。
