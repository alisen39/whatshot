"""核心数据模型 —— 热榜 / 快讯 / 金价条目与路由响应。

数据标准（硬规则，新增路由/字段必须遵守）
========================================

时间单位
--------
所有条目的 ``timestamp`` 字段统一为 **Unix 毫秒级整数**（13 位，如 ``1783231621000``）。
- 上游若给出秒级（10 位），由 ``coerce_timestamp`` 校验器自动补齐到毫秒（× 1000）。
- 路由层产出时间应优先调用 ``whats_hot_api.utils.get_time.get_time()``，它会统一返回毫秒；
  models 层的校验器是最后一道防线，兜底归一化任何漏网的秒级输入。
- 判断阈值为 ``1_000_000_000_000``（10^12，约 2001-09 的毫秒值），与前端
  ``normalizeTimestampMs``、扩展包 ``hot_fetcher._timestamp_to_datetime`` 三处对齐。

注意区分两套时间字段（单位不同，切勿混淆）：
- 条目级 ``timestamp``：int，毫秒，表示该条内容的**发布时间**。
- 响应级 ``updateTime``：str，ISO 8601 字符串，表示**本次数据的刷新时间**
  （route handler 成功取得整张榜单的时间）。

字段必填规则
------------
每个 data class 用行内注释 ``# 必填`` / ``# 选填`` 标注。
- 必填：路由必须提供，缺失即校验失败。
- 选填：可不提供，取默认值（通常为 ``None`` / 空集合）。
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from pydantic import (
    BaseModel,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)

ContentKind = Literal["hotlist", "newsflash", "gold"]
ContentStatus = Literal["full", "summary", "truncated"]
GoldQuoteType = Literal[
    "retail_sell",
    "buyback",
    "exchange",
    "exchange_alt",
    "exchange_jewellery",
    "benchmark",
    "spot",
]
GoldUnit = Literal["gram", "tael", "kilogram"]
GoldMetal = Literal["gold", "platinum", "silver"]

# 秒/毫秒判断阈值：小于此值视为秒级，×1000 补齐为毫秒。
# 取 10^12（约 2001-09 的毫秒值），与前端 normalizeTimestampMs、扩展包 hot_fetcher 对齐。
_MS_THRESHOLD = 1_000_000_000_000


def _coerce_timestamp_ms(value: object) -> int | None:
    """把任意时间值归一化为 Unix 毫秒级整数；无效则返回 None。

    - 字符串/浮点先转 int（"1783231621" → 1783231621）。
    - 秒级（< 10^12）× 1000 补齐为毫秒。
    - 毫秒级（≥ 10^12）原样保留。
    - 非正数或无法解析的值返回 None。
    """
    if not value:
        return None
    try:
        val = round(float(value))
    except (ValueError, TypeError):
        return None
    if val <= 0:
        return None
    return val * 1000 if val < _MS_THRESHOLD else val


class ListItem(BaseModel):
    """热榜 / 榜单类条目（对应 ``kind="hotlist"``）。

    用于微博、知乎、B 站、GitHub 等榜单站点。一个榜单条目至少要有标题和可跳转链接；
    热度、封面、作者、发布时间为可选增强信息。
    """

    id: str  # 必填：条目唯一标识，自动 str() 强转
    title: str  # 必填：标题
    url: str  # 必填：PC 端链接
    mobileUrl: str | None = None  # 选填：移动端链接
    hot: int | None = None  # 选填：热度值，自动 int()
    cover: str | None = None  # 选填：封面图 URL
    author: str | None = None  # 选填：作者 / UP主
    desc: str | None = None  # 选填：描述 / 摘要
    timestamp: int | None = None  # 选填：发布时间，Unix 毫秒级整数

    @field_validator("id", mode="before")
    @classmethod
    def coerce_id(cls, v: object) -> str:
        return str(v)

    @field_validator("hot", mode="before")
    @classmethod
    def coerce_hot(cls, v: object) -> int | None:
        if v is None:
            return None
        try:
            return round(float(v))
        except (ValueError, TypeError):
            return None

    @field_validator("timestamp", mode="before")
    @classmethod
    def coerce_timestamp(cls, v: object) -> int | None:
        return _coerce_timestamp_ms(v)

    @field_validator("cover", "author", "desc", mode="before")
    @classmethod
    def empty_str_to_none(cls, v: object) -> object:
        if isinstance(v, str) and not v.strip():
            return None
        return v


class GoldQuote(BaseModel):
    """品牌或市场发布的一条原生报价。

    币种和计量单位共同构成报价身份；Core 不做隐式汇率或重量换算。
    """

    quoteType: GoldQuoteType
    label: str
    price: Decimal
    currency: str
    unit: GoldUnit
    sourceQuoteTime: str | None = None
    sourceQuoteTimeTrusted: bool = False

    @field_validator("price", mode="before")
    @classmethod
    def coerce_price(cls, value: object) -> Decimal:
        try:
            normalized = Decimal(str(value).replace(",", ""))
        except (InvalidOperation, ValueError, TypeError) as exc:
            raise ValueError("Gold quote price must be numeric.") from exc
        if not normalized.is_finite() or normalized <= 0:
            raise ValueError("Gold quote price must be positive and finite.")
        return normalized

    @field_serializer("price")
    def serialize_price(self, value: Decimal) -> int | float:
        return int(value) if value == value.to_integral_value() else float(value)

    @field_validator("currency", mode="before")
    @classmethod
    def normalize_currency(cls, value: object) -> str:
        currency = str(value).strip().upper()
        if len(currency) != 3 or not currency.isalpha():
            raise ValueError("Gold quote currency must be a three-letter code.")
        return currency

    @field_validator("label", "sourceQuoteTime", mode="before")
    @classmethod
    def normalize_text(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip() or None
        return value

    @model_validator(mode="after")
    def validate_source_time_trust(self) -> GoldQuote:
        if self.sourceQuoteTimeTrusted and self.sourceQuoteTime is None:
            raise ValueError("sourceQuoteTimeTrusted requires a sourceQuoteTime value.")
        return self


class GoldItem(BaseModel):
    """金价类条目（对应 ``kind="gold"``）。

    ``quotes`` 是正式报价契约。迁移期间保留 ``sellPrice`` / ``recyclePrice``，且只从
    人民币/克的销售与回收报价生成，避免旧客户端误读港币或「两」报价。
    """

    id: str  # 必填：条目唯一标识，自动 str() 强转
    title: str  # 必填：黄金 / 贵金属品类名称
    url: str  # 必填：PC 端链接
    mobileUrl: str | None = None  # 选填：移动端链接
    metal: GoldMetal = "gold"
    quotes: list[GoldQuote] = Field(default_factory=list)
    sellPrice: int | float | None = None  # 兼容字段：人民币/克销售价
    recyclePrice: int | float | None = None  # 兼容字段：人民币/克回收价
    desc: str | None = None  # 选填：面向展示的价格说明
    timestamp: int | None = None  # 选填：价格日期，Unix 毫秒级整数

    @field_validator("id", mode="before")
    @classmethod
    def coerce_id(cls, v: object) -> str:
        return str(v)

    @field_validator("sellPrice", "recyclePrice", mode="before")
    @classmethod
    def coerce_legacy_price(cls, v: object) -> int | float | None:
        if v is None:
            return None
        try:
            value = Decimal(str(v).replace(",", ""))
        except (InvalidOperation, ValueError, TypeError):
            return None
        if not value.is_finite() or value <= 0:
            return None
        return int(value) if value == value.to_integral_value() else float(value)

    @field_validator("timestamp", mode="before")
    @classmethod
    def coerce_timestamp(cls, v: object) -> int | None:
        return _coerce_timestamp_ms(v)

    @field_validator("desc", mode="before")
    @classmethod
    def empty_str_to_none(cls, v: object) -> object:
        if isinstance(v, str) and not v.strip():
            return None
        return v

    @model_validator(mode="after")
    def populate_quote_compatibility(self) -> GoldItem:
        if not self.quotes:
            source_time = None
            if self.timestamp is not None:
                from datetime import UTC, datetime

                source_time = datetime.fromtimestamp(
                    self.timestamp / 1000, UTC
                ).isoformat()
            if self.sellPrice is not None:
                self.quotes.append(
                    GoldQuote(
                        quoteType="retail_sell",
                        label="销售价",
                        price=self.sellPrice,
                        currency="CNY",
                        unit="gram",
                        sourceQuoteTime=source_time,
                        sourceQuoteTimeTrusted=source_time is not None,
                    )
                )
            if self.recyclePrice is not None:
                self.quotes.append(
                    GoldQuote(
                        quoteType="buyback",
                        label="回收价",
                        price=self.recyclePrice,
                        currency="CNY",
                        unit="gram",
                        sourceQuoteTime=source_time,
                        sourceQuoteTimeTrusted=source_time is not None,
                    )
                )

        for quote in self.quotes:
            if quote.currency != "CNY" or quote.unit != "gram":
                continue
            legacy_value: int | float = (
                int(quote.price)
                if quote.price == quote.price.to_integral_value()
                else float(quote.price)
            )
            if quote.quoteType == "retail_sell" and self.sellPrice is None:
                self.sellPrice = legacy_value
            elif quote.quoteType == "buyback" and self.recyclePrice is None:
                self.recyclePrice = legacy_value
        return self


class NewsFlashItem(BaseModel):
    """快讯类条目（对应 ``kind="newsflash"``）。

    用于东方财富、华尔街见闻、财联社等 7×24 财经快讯站点。与 ListItem 的核心区别：
    - 必须有正文 ``content``（不只是标题）；
    - 有正文状态 ``contentStatus``（full/summary/truncated）表征正文完整性；
    - 有来源、标签、关联标的、指标等结构化增强字段。
    """

    id: str  # 必填：条目唯一标识，自动 str() 强转
    title: str  # 必填：标题
    content: str  # 必填：正文
    url: str  # 必填：PC 端链接
    mobileUrl: str | None = None  # 选填：移动端链接
    summary: str | None = None  # 选填：摘要（区别于正文 content）
    contentStatus: ContentStatus = "full"  # 选填：正文状态，默认完整
    source: str | None = None  # 选填：来源
    isImportant: bool = False  # 选填：是否重要，默认否
    tags: list[str] = Field(default_factory=list)  # 选填：标签列表
    images: list[str] = Field(default_factory=list)  # 选填：图片 URL 列表
    symbols: list[dict[str, Any]] = Field(
        default_factory=list
    )  # 选填：关联标的（股票/币种等）
    metrics: dict[str, Any] = Field(default_factory=dict)  # 选填：指标数据
    timestamp: int | None = None  # 选填：发布时间，Unix 毫秒级整数

    @field_validator("id", mode="before")
    @classmethod
    def coerce_id(cls, v: object) -> str:
        return str(v)

    @field_validator("timestamp", mode="before")
    @classmethod
    def coerce_timestamp(cls, v: object) -> int | None:
        return _coerce_timestamp_ms(v)

    @field_validator("summary", "source", mode="before")
    @classmethod
    def empty_str_to_none(cls, v: object) -> object:
        if isinstance(v, str) and not v.strip():
            return None
        return v

    @field_validator("tags", "images", "symbols", mode="before")
    @classmethod
    def none_to_list(cls, v: object) -> object:
        return [] if v is None else v

    @field_validator("metrics", mode="before")
    @classmethod
    def none_to_dict(cls, v: object) -> object:
        return {} if v is None else v


DataItem = NewsFlashItem | ListItem | GoldItem


class RouterData(BaseModel):
    """单次路由抓取的结果（内部传递 + 直接序列化为 API 响应体）。

    ``kind`` 决定 ``data`` 列表里条目的类型：``hotlist`` → ListItem，
    ``newsflash`` → NewsFlashItem，``gold`` → GoldItem。
    """

    kind: ContentKind = "hotlist"
    name: str  # 必填：路由名（站点标识，如 "weibo"）
    title: str  # 必填：站点中文名
    type: str  # 必填：榜单 / 快讯类型标签
    description: str | None = None  # 选填：描述
    params: dict | None = None  # 选填：可用参数说明
    link: str | None = None  # 选填：站点主页
    total: int  # 必填：条目总数
    fromCache: bool  # 必填：本次结果是否来自缓存
    updateTime: str  # 必填：本次数据刷新时间，ISO 8601 字符串（注意：非毫秒）
    data: list[DataItem]  # 必填：条目列表
    message: str | None = None  # 选填：附加信息


class ApiResponse(BaseModel):
    """对外 API 响应的宽松容器（所有字段可选，便于部分填充）。

    与 RouterData 字段对应，但允许省略任意字段，用于缓存命中 / 异常等场景的部分响应。
    """

    code: int = 200
    kind: ContentKind | None = None
    name: str | None = None
    title: str | None = None
    type: str | None = None
    description: str | None = None
    params: dict | None = None
    link: str | None = None
    total: int | None = None
    fromCache: bool | None = None
    updateTime: str | None = None  # 选填：ISO 8601 字符串，本次数据刷新时间
    data: list[DataItem] | None = None
    message: str | None = None


class RouteInfo(BaseModel):
    name: str
    path: str | None = None
    message: str | None = None
