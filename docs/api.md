# HTTP API 与配置

Core API 默认监听 `6688`，提供站点元信息、榜单数据、JSON 和 RSS 2.0 输出。它不依赖
daemon，也不需要数据库。

```bash
uv sync
uv run python -m whats_hot_api
curl http://127.0.0.1:6688/all
```

## 端点

每个路由提供元信息端点和数据端点：

```text
GET /weibo            站点元信息：标题、说明、可用 type 和参数
GET /weibo/hot        榜单数据
GET /bilibili/1
GET /acfun/1?range=WEEK
GET /all              全部路由
GET /categories       按分类分组的路由
```

元信息中的 `types` 列出该站点可用的榜单，`defaultType` 是默认榜单，`dataPath`
是数据端点模板。

## 通用查询参数

```text
?rss=true          输出 RSS 2.0
?cache=false       跳过旧缓存并刷新
?cache=only        只读缓存，未命中返回 404
?limit=10          限制条目数
```

## 响应格式

```json
{
  "code": 200,
  "kind": "hotlist",
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

`updateTime` 是 WhatsHot 成功拉取该榜单的 UTC 时间，不是条目的发布时间。

## 金价

金价路由使用原生报价口径；币种和单位属于每条报价，Core 不做汇率或重量换算：

```text
GET /lukfook/mainland
GET /lukfook/hong-kong
GET /chow-taifook-hk/hong-kong
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

## 配置

Core API 从 `.env` 读取缓存和上游请求配置，可从 `.env.example` 复制：

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `PORT` | `6688` | Core API 端口 |
| `HOTLIST_CACHE_TTL` | `1800` | 热榜缓存秒数 |
| `NEWSFLASH_CACHE_TTL` | `300` | 快讯缓存秒数 |
| `REQUEST_TIMEOUT` | `6000` | 上游超时毫秒数 |
| `REDIS_HOST` | `127.0.0.1` | 留空时只用内存缓存 |
| `ALLOWED_DOMAIN` | 见 `.env.example` | 允许跨域的浏览器 Origin，逗号分隔 |
| `SOURCE_RSSHUB_BASE_URLS` | 空 | RSSHub 实例列表 |
| `ROUTE_PROXY` | 空 | 按域名关键词匹配的代理 JSON |
| `ZHIHU_COOKIE` | 空 | 可选，知乎请求附带的 Cookie |

缓存是 Redis + 进程内 TTL 双层，Redis 不可用时自动降级为内存缓存。修改 `.env`
后重启 `6688`。

代理示例：

```bash
ROUTE_PROXY='{"github.com":"http://127.0.0.1:7890","nytimes.com":"http://127.0.0.1:7890"}'
```

`ENVIRONMENT=production` 时会忽略 localhost/127.0.0.1 代理。

## 命令行

CLI 与 HTTP API 共用同一条抓取路径，实时读取不需要启动任何服务：

```bash
uv run whatshot --help                 # 列出全部站点命令
uv run whatshot list -f json
uv run whatshot weibo hot -f json
uv run whatshot weibo hot --cache only
uv run whatshot bilibili 188 --limit 10 -f markdown
```

输出格式：`table`、`plain`、`json`、`jsonl`、`yaml`、`markdown`、`csv`。
`--envelope` 输出完整响应元信息，`--param KEY=VALUE` 传递路由参数。

历史与 Scheduler 子命令见 [定时采集与历史数据](daemon.md)。
