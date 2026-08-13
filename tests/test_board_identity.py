from __future__ import annotations

import pytest

from whats_hot_api.fetch import (
    BOARD_KEY_VERSION,
    SUPPORTED_BOARD_DIMENSIONS,
    BoardIdentityError,
    board_key_read_candidates,
    canonical_board_key,
)
from whats_hot_api.registry import discover_and_register_routes, fetch_service


def test_board_key_v1_has_fixed_identity_without_dimensions() -> None:
    assert BOARD_KEY_VERSION == 1
    assert (
        canonical_board_key(
            path_type="hot",
            params={},
            declared_dimensions=(),
        )
        == "hot"
    )


def test_board_key_v1_orders_type_first_then_dimension_names() -> None:
    assert (
        canonical_board_key(
            path_type="ranking",
            params={"range": "week", "game": "genshin"},
            declared_dimensions={"range", "type", "game"},
        )
        == "type=ranking&game=genshin&range=week"
    )


def test_board_key_v1_covers_date_and_province_dimensions() -> None:
    assert (
        canonical_board_key(
            path_type="weather",
            params={
                "province": "北京市 海淀/区",
                "month": "2026-08",
                "day": "2026-08-13",
            },
            declared_dimensions={"type", "province", "month", "day"},
        )
        == (
            "type=weather&day=2026-08-13&month=2026-08&"
            "province=%E5%8C%97%E4%BA%AC%E5%B8%82%20%E6%B5%B7%E6%B7%80%2F%E5%8C%BA"
        )
    )


@pytest.mark.parametrize(
    ("params", "declared", "message"),
    [
        ({"limit": "10"}, {"limit"}, "unsupported declared"),
        ({"sort": "new"}, {"type"}, "not declared"),
        ({"type": "new"}, {"type"}, "only as path_type"),
        ({"range": ""}, {"range"}, "non-empty string value"),
        ({"": "value"}, {"range"}, "non-empty strings"),
    ],
)
def test_board_key_v1_rejects_invalid_dimensions(
    params: dict[str, str],
    declared: set[str],
    message: str,
) -> None:
    with pytest.raises(BoardIdentityError, match=message):
        canonical_board_key(
            path_type="hot",
            params=params,
            declared_dimensions=declared,
        )


def test_legacy_default_is_read_only_alias_for_hot() -> None:
    assert board_key_read_candidates("hot") == ("hot", "default")
    assert board_key_read_candidates("default") == ("hot", "default")
    assert board_key_read_candidates("type=weekly") == ("type=weekly",)


def test_all_core_sources_only_declare_contract_v1_dimensions() -> None:
    discover_and_register_routes()

    observed: set[str] = set()
    for source in fetch_service.list_sources():
        declared = set((source.params or {}).keys())
        observed.update(declared)
        assert declared <= SUPPORTED_BOARD_DIMENSIONS, source.name

    # Inventory guard: dropping one of these dimensions from route discovery
    # must be an explicit metadata/contract decision, not a silent change.
    assert observed == SUPPORTED_BOARD_DIMENSIONS
