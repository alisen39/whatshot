# 开发与扩展

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

### 快讯回溯声明

快讯 route 除实时采集外，必须声明回溯方式（契约见
`whats_hot_api/backfill.py`）。`BACKFILL` 以 path type 为键，`"*"` 覆盖其余类型；
不支持也要显式声明原因：

```python
from whats_hot_api.backfill import BackfillSpec, BackfillStrategy, unsupported

BACKFILL: dict[str, BackfillSpec] = {
    "*": BackfillSpec(
        strategy=BackfillStrategy.TIME_CURSOR,
        notes="last_time=上一页最老时间（含边界）",
        supports_before=True,
        verified_at="2026-10-14",
    ),
    "hot": unsupported("推荐榜成员无法按历史还原"),
}


async def backfill_page(path_type, params, cursor, *, before):
    ...  # 返回 BackfillPage(data, next_cursor, raw_digest)
```

- 策略：`time_cursor`、`opaque_cursor`、`page_number`、`date_query` 需实现
  `backfill_page`；`snapshot` 复用 `handle_route` 的当前页；`unsupported` 不实现。
- 实时与回溯共用同一解析函数；时间游标包含边界，同秒条目由调用方去重。
- 回溯请求经 `FetchService.backfill_page` 执行，游标不进入 board 身份，也不读写响应缓存。
- 声明完整性由 `tests/test_backfill_contract.py` 强制；翻页实现需补固定数据测试
  （游标推进、边界同秒、空页/重复页停止）。

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

`extra_route_packages` 中的包遵循与内置路由相同的分类子包约定。

## 测试

```bash
uv run pytest
uv run pytest tests/test_backend_contract_api.py -v
uv run pytest tests/test_daemon.py -v
```

测试默认禁用网络。变更 Backend Contract 时，还必须使用相邻
`whatshot-mcp/contracts` 制品运行 Contract 测试。
