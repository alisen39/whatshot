from __future__ import annotations

import json

import pytest
from starlette.requests import Request

from whats_hot_api.routes.hotlist import gitee_gitlab
from whats_hot_api.utils.http_client import RequestResult

UPDATE_TIME = "2026-10-01T00:00:00+00:00"

# fixtures 按 board_api 证据(evidence/01_gitlab_api_star_count.response.body)净化内联。
_ROWS = [
    {
        "id": 13083,
        "description": "GitLab FOSS is a read-only mirror of GitLab, with all proprietary code removed.\n\nPreviously hosted GitLab Community Edition.",
        "name": "GitLab FOSS",
        "name_with_namespace": "GitLab.org / GitLab FOSS",
        "path_with_namespace": "gitlab-org/gitlab-foss",
        "created_at": "2013-09-26T06:02:36.000Z",
        "web_url": "https://gitlab.com/gitlab-org/gitlab-foss",
        "avatar_url": "https://gitlab.com/uploads/-/system/project/avatar/13083/project_avatar.png?v=1790536909",
        "star_count": 7177,
        "namespace": {"id": 9970, "name": "GitLab.org", "path": "gitlab-org", "kind": "group"},
    },
    {
        "id": 61806,
        "description": "一个没有 description 也没有头像的项目",
        "name": "OSS",
        "name_with_namespace": "某用户 / OSS",
        "path_with_namespace": "someone/oss",
        "created_at": "2023-08-27T10:00:00.000Z",
        "web_url": "https://gitlab.com/someone/oss",
        "avatar_url": None,
        "star_count": 12,
        "namespace": {"id": 42, "name": "某用户", "path": "someone", "kind": "user"},
    },
    # 缺 web_url 的脏行应被跳过
    {"id": 999, "name": "broken"},
]


def _request(board: str | None = None) -> Request:
    query = f"type={board}" if board else ""
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/gitee-gitlab",
            "query_string": query.encode(),
            "headers": [],
        }
    )


@pytest.mark.asyncio
async def test_most_stars_requests_star_count_api(monkeypatch):
    captured = {}

    async def fake_get(**kwargs):
        captured.update(kwargs)
        return RequestResult(False, UPDATE_TIME, _ROWS)

    monkeypatch.setattr(gitee_gitlab, "get", fake_get)

    result = await gitee_gitlab.handle_route(_request(), no_cache=True)

    assert captured["url"] == "https://gitlab.com/api/v4/projects"
    # order_by 必需(缺省按 created_at 排,0 重合);active=true 与探索页 Active 标签口径一致
    assert captured["params"] == {
        "order_by": "star_count",
        "sort": "desc",
        "per_page": 20,
        "simple": "true",
        "active": "true",
    }
    assert captured["headers"] == {"Accept": "application/json"}
    assert result.name == "gitee-gitlab"
    assert result.title == "Gitee 与 GitLab"
    assert result.type == "GitLab · Most starred"
    assert result.total == 2  # 脏行被跳过
    assert result.link == "https://gitlab.com/explore/projects/active?sort=stars_desc"


@pytest.mark.asyncio
async def test_project_fields_are_mapped(monkeypatch):
    async def fake_get(**kwargs):
        return RequestResult(False, UPDATE_TIME, _ROWS)

    monkeypatch.setattr(gitee_gitlab, "get", fake_get)

    result = await gitee_gitlab.handle_route(_request("gitlab-most-stars"), no_cache=True)

    first = result.data[0]
    assert first.id == "13083"  # 项目 id,不是名次
    # 探索页口径:"组 / 项目"
    assert first.title == "GitLab.org / GitLab FOSS"
    assert first.url == "https://gitlab.com/gitlab-org/gitlab-foss"
    assert first.mobileUrl == first.url
    assert first.hot == 7177  # star_count
    assert first.author == "GitLab.org"
    assert first.desc.startswith("GitLab FOSS is a read-only mirror")
    assert "\n" not in first.desc  # 空白合并
    assert first.cover == "https://gitlab.com/uploads/-/system/project/avatar/13083/project_avatar.png?v=1790536909"
    assert first.timestamp == 1380175356000  # created_at ISO → 毫秒

    second = result.data[1]
    assert second.cover is None  # 没设头像
    assert second.timestamp == 1693130400000


@pytest.mark.asyncio
async def test_relative_avatar_is_made_absolute(monkeypatch):
    row = dict(_ROWS[0])
    row["avatar_url"] = "/uploads/-/system/project/avatar/13083/avatar.png"

    async def fake_get(**kwargs):
        return RequestResult(False, UPDATE_TIME, [row])

    monkeypatch.setattr(gitee_gitlab, "get", fake_get)

    result = await gitee_gitlab.handle_route(_request(), no_cache=True)
    assert result.data[0].cover == "https://gitlab.com/uploads/-/system/project/avatar/13083/avatar.png"


@pytest.mark.asyncio
async def test_non_list_payload_is_rejected(monkeypatch):
    async def fake_get(**kwargs):
        return RequestResult(False, UPDATE_TIME, {"message": "404 Not Found"})

    monkeypatch.setattr(gitee_gitlab, "get", fake_get)

    with pytest.raises(RuntimeError, match="not a list"):
        await gitee_gitlab.handle_route(_request(), no_cache=True)


@pytest.mark.asyncio
async def test_empty_project_list_is_an_error(monkeypatch):
    async def fake_get(**kwargs):
        return RequestResult(False, UPDATE_TIME, [])

    monkeypatch.setattr(gitee_gitlab, "get", fake_get)

    with pytest.raises(RuntimeError, match="returned no projects"):
        await gitee_gitlab.handle_route(_request(), no_cache=True)


@pytest.mark.asyncio
async def test_unknown_board_is_rejected():
    with pytest.raises(ValueError, match="Unknown board 'gitee-hot'"):
        await gitee_gitlab.handle_route(_request("gitee-hot"), no_cache=True)


def test_type_map_declares_single_board():
    assert len(gitee_gitlab.type_map) == 1
    assert gitee_gitlab.DEFAULT_TYPE == "gitlab-most-stars"
    assert json.dumps(gitee_gitlab.ROUTE_META["params"]["type"]["type"])  # JSON 可序列化
