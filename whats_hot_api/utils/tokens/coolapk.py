"""Coolapk APP token and request header generation."""

from __future__ import annotations

import base64
import hashlib
import random
import string
import time


def _random_device_id() -> str:
    """Generate a random DEVICE_ID in the format used by Coolapk."""
    lengths = [10, 6, 6, 6, 14]
    chars = string.digits + string.ascii_lowercase
    return "-".join(
        "".join(random.choice(chars) for _ in range(length))
        for length in lengths
    )


def _get_app_token() -> str:
    """Compute the ``X-App-Token`` value."""
    device_id = _random_device_id()
    now = round(time.time())
    hex_now = "0x" + format(now, "x")
    md5_now = hashlib.md5(str(now).encode(), usedforsecurity=False).hexdigest()

    s = (
        "token://com.coolapk.market/c67ef5943784d09750dcfbb31020f0ab?"
        + md5_now
        + "$"
        + device_id
        + "&com.coolapk.market"
    )
    # Match JS: md5(Buffer.from(s).toString("base64"))
    b64_s = base64.b64encode(s.encode()).decode()
    md5_s = hashlib.md5(b64_s.encode(), usedforsecurity=False).hexdigest()

    return md5_s + device_id + hex_now


def gen_headers() -> dict[str, str]:
    """Return request headers required by Coolapk API."""
    return {
        "X-Requested-With": "XMLHttpRequest",
        "X-App-Id": "com.coolapk.market",
        "X-App-Token": _get_app_token(),
        "X-Sdk-Int": "29",
        "X-Sdk-Locale": "zh-CN",
        "X-App-Version": "11.0",
        "X-Api-Version": "11",
        "X-App-Code": "2101202",
        "User-Agent": (
            "Mozilla/5.0 (Linux; Android 10; Mi 10) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/111.0.5563.15 Mobile Safari/537.36"
        ),
    }
