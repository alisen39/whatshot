from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

CHINA_TZ = timezone(timedelta(hours=8))


def get_time(time_input: str | int | float | None) -> int | None:
    """把上游时间统一转换为 **Unix 毫秒级整数**（数据标准主入口）。

    路由产出条目 ``timestamp`` 时应优先调用本函数，而非自行转换。
    支持三类输入，均归一化为 13 位毫秒整数：
    - 数值（秒 / 毫秒）：按 ``946684800000``（2000-01-01 的 ms）为阈值判断，
      小于则视为秒级 × 1000，大于则视为毫秒原样返回。
    - 纯数字字符串：先转 float 后按数值规则处理。
    - 中文 / 标准日期字符串（"刚刚"、"N小时前"、"N月N日"、ISO 等）：交由
      ``_parse_chinese_time`` 解析，结果经 ``_timestamp_ms`` 统一 × 1000。

    无效输入返回 None；日期字符串无法识别时返回 0（由 models 层校验器过滤为 None）。
    """
    if time_input is None:
        return None
    try:
        if isinstance(time_input, (int, float)):
            num = time_input
        else:
            # str case
            try:
                num = float(time_input)
            except ValueError:
                return _parse_chinese_time(time_input)

        # Millisecond vs second threshold (2000-01-01 in ms)
        if num > 946684800000:
            return int(num)
        else:
            return int(num * 1000)
    except Exception:
        return None


def _parse_chinese_time(s: str) -> int | None:
    now = datetime.now(CHINA_TZ)

    # "HH:MM"
    if re.match(r"^\d{2}:\d{2}$", s):
        h, m = map(int, s.split(":"))
        dt = now.replace(hour=h, minute=m, second=0, microsecond=0)
        return _timestamp_ms(dt)

    # "昨日 HH:MM"
    m = re.match(r"^昨日\s+(\d{2}):(\d{2})$", s)
    if m:
        h, mi = int(m.group(1)), int(m.group(2))
        dt = (now - timedelta(days=1)).replace(hour=h, minute=mi, second=0, microsecond=0)
        return _timestamp_ms(dt)

    # "N月N日 HH:MM"
    m = re.match(r"^(\d{1,2})月(\d{1,2})日\s+(\d{2}):(\d{2})$", s)
    if m:
        mo, d, h, mi = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
        dt = now.replace(month=mo, day=d, hour=h, minute=mi, second=0, microsecond=0)
        return _timestamp_ms(dt)

    # "N月N日"
    m = re.match(r"^(\d{1,2})月(\d{1,2})日$", s)
    if m:
        mo, d = int(m.group(1)), int(m.group(2))
        dt = now.replace(month=mo, day=d, hour=0, minute=0, second=0, microsecond=0)
        return _timestamp_ms(dt)

    # "今天 HH:MM"
    m = re.match(r"今天\s*(\d{1,2}):(\d{2})", s)
    if m:
        h, mi = int(m.group(1)), int(m.group(2))
        dt = now.replace(hour=h, minute=mi, second=0, microsecond=0)
        return _timestamp_ms(dt)

    # "昨天 HH:MM"
    m = re.match(r"昨天\s*(\d{1,2}):(\d{2})", s)
    if m:
        h, mi = int(m.group(1)), int(m.group(2))
        dt = (now - timedelta(days=1)).replace(hour=h, minute=mi, second=0, microsecond=0)
        return _timestamp_ms(dt)

    # "N小时前"
    m = re.search(r"(\d+)\s*小时前", s)
    if m:
        hours = int(m.group(1))
        dt = now - timedelta(hours=hours)
        return _timestamp_ms(dt)

    # "N分钟前"
    m = re.search(r"(\d+)\s*分钟前", s)
    if m:
        minutes = int(m.group(1))
        dt = now - timedelta(minutes=minutes)
        return _timestamp_ms(dt)

    # Standard formats
    iso_text = s.strip().replace("Z", "+00:00")
    try:
        return _timestamp_ms(datetime.fromisoformat(iso_text))
    except ValueError:
        pass

    standardized = s
    standardized = re.sub(
        r"(\d{4})-(\d{2})-(\d{2})-(\d{2})", r"\1-\2-\3 \4", standardized
    )
    standardized = re.sub(
        r"(\d{4})-(\d{2})-(\d{2})[T\s](\d{2}):?(\d{2})?:?(\d{2})?",
        r"\1-\2-\3 \4:\5:\6",
        standardized,
    )
    standardized = re.sub(r"(\d{4})[-/](\d{2})[-/](\d{2})", r"\1-\2-\3", standardized)
    standardized = re.sub(r"\s+", " ", standardized).strip()

    for fmt in [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M:",
        "%Y-%m-%d %H::",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d %H",
        "%Y-%m-%d",
    ]:
        try:
            dt = datetime.strptime(standardized, fmt)
            return _timestamp_ms(dt)
        except ValueError:
            continue

    return 0


def _timestamp_ms(dt: datetime) -> int:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=CHINA_TZ)
    return int(dt.timestamp() * 1000)


def get_current_datetime(pad_zero: bool = False) -> dict[str, str]:
    now = datetime.now(timezone.utc)
    pad = (lambda n: f"{n:02d}") if pad_zero else (lambda n: str(n))
    return {
        "year": str(now.year),
        "month": pad(now.month),
        "day": pad(now.day),
        "hour": pad(now.hour),
        "minute": pad(now.minute),
        "second": pad(now.second),
    }
