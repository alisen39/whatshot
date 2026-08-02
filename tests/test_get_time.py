from __future__ import annotations

from datetime import datetime, timedelta, timezone

from whats_hot_api.utils.get_time import get_time


CHINA_TZ = timezone(timedelta(hours=8))


def _timestamp_ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def test_naive_standard_datetime_is_parsed_as_china_time():
    assert get_time("2026-07-05 14:07:00") == _timestamp_ms(
        datetime(2026, 7, 5, 14, 7, tzinfo=CHINA_TZ)
    )


def test_iso_datetime_with_timezone_keeps_declared_timezone():
    assert get_time("2026-07-05T06:07:00+00:00") == _timestamp_ms(
        datetime(2026, 7, 5, 6, 7, tzinfo=timezone.utc)
    )


def test_numeric_second_timestamp_is_converted_to_milliseconds():
    assert get_time(1783231621) == 1783231621000
