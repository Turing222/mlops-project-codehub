"""Core API HTTP smoke tests.

职责：固化真实 smoke 环境中的认证、用户、工作空间、权限和审计基础链路。
边界：不触发 LLM、RAG 或压测行为，只检查低成本 API 契约。
"""

from __future__ import annotations

import httpx
import pytest

from tests.smoke import _http_smoke_helpers as smoke_helpers

pytestmark = pytest.mark.smoke
smoke_client = smoke_helpers.smoke_client


async def test_core_auth_workspace_permission_and_audit_denial_flow(
    smoke_client: httpx.AsyncClient,
) -> None:
    await smoke_helpers.ensure_ready_environment(smoke_client)
    owner_headers, owner_suffix = await smoke_helpers.auth_headers_for_new_user(
        smoke_client,
        prefix="c_owner",
    )
    member_headers, _member_suffix = await smoke_helpers.auth_headers_for_new_user(
        smoke_client,
        prefix="c_member",
    )
    admin_headers, _admin_suffix = await smoke_helpers.auth_headers_for_new_user(
        smoke_client,
        prefix="c_admin",
    )

    owner = await smoke_helpers.get_current_user(smoke_client, headers=owner_headers)
    member = await smoke_helpers.get_current_user(smoke_client, headers=member_headers)
    admin = await smoke_helpers.get_current_user(smoke_client, headers=admin_headers)
    workspace = await smoke_helpers.create_workspace(
        smoke_client,
        headers=owner_headers,
        suffix=owner_suffix,
    )
    member_body = await smoke_helpers.add_workspace_member(
        smoke_client,
        headers=owner_headers,
        workspace_id=workspace["id"],
        user_id=member["id"],
    )
    admin_body = await smoke_helpers.add_workspace_member(
        smoke_client,
        headers=owner_headers,
        workspace_id=workspace["id"],
        user_id=admin["id"],
        role="admin",
    )

    assert owner["id"] != member["id"]
    assert owner["id"] != admin["id"]
    assert member_body["workspace_id"] == workspace["id"]
    assert admin_body["workspace_id"] == workspace["id"]

    policy_response = await smoke_client.get(
        "/api/v1/permissions/policy",
        headers=member_headers,
    )
    assert policy_response.status_code == 200, policy_response.text
    policy_body = policy_response.json()
    assert policy_body["permissions"]
    assert policy_body["roles"]
    assert policy_body["role_permissions"]

    audit_allowed_response = await smoke_client.get(
        "/api/v1/audit/events",
        headers=admin_headers,
        params={"workspace_id": workspace["id"]},
    )
    assert audit_allowed_response.status_code == 200, audit_allowed_response.text
    audit_body = audit_allowed_response.json()
    assert isinstance(audit_body["items"], list)
    assert audit_body["total"] >= len(audit_body["items"])

    audit_denied_response = await smoke_client.get(
        "/api/v1/audit/events",
        headers=member_headers,
        params={"workspace_id": workspace["id"]},
    )
    assert audit_denied_response.status_code == 403, audit_denied_response.text


async def test_core_auth_and_workspace_negative_flow(
    smoke_client: httpx.AsyncClient,
) -> None:
    await smoke_helpers.ensure_ready_environment(smoke_client)

    unauthenticated_response = await smoke_client.get("/api/v1/users/me")
    smoke_helpers.assert_error_response(unauthenticated_response, 401, "HTTP_401")

    invalid_token_response = await smoke_client.get(
        "/api/v1/users/me",
        headers={"Authorization": "Bearer invalid-smoke-token"},
    )
    smoke_helpers.assert_error_response(
        invalid_token_response,
        403,
        "INVALID_TOKEN",
    )

    (
        _duplicate_headers,
        duplicate_suffix,
    ) = await smoke_helpers.auth_headers_for_new_user(
        smoke_client,
        prefix="c_dup",
    )
    duplicate_username = f"c_dup_{duplicate_suffix}"
    duplicate_response = await smoke_client.post(
        "/api/v1/auth/register",
        json={
            "username": duplicate_username,
            "email": f"{duplicate_username}@example.com",
            "password": "Password123",
            "confirm_password": "Password123",
        },
    )
    smoke_helpers.assert_error_response(
        duplicate_response,
        422,
        "EMAIL_ALREADY_REGISTERED",
    )

    owner_headers, owner_suffix = await smoke_helpers.auth_headers_for_new_user(
        smoke_client,
        prefix="c_acl_own",
    )
    member_headers, _member_suffix = await smoke_helpers.auth_headers_for_new_user(
        smoke_client,
        prefix="c_acl_mem",
    )
    target_headers, _target_suffix = await smoke_helpers.auth_headers_for_new_user(
        smoke_client,
        prefix="c_acl_tgt",
    )
    member = await smoke_helpers.get_current_user(smoke_client, headers=member_headers)
    target = await smoke_helpers.get_current_user(smoke_client, headers=target_headers)
    workspace = await smoke_helpers.create_workspace(
        smoke_client,
        headers=owner_headers,
        suffix=owner_suffix,
    )
    await smoke_helpers.add_workspace_member(
        smoke_client,
        headers=owner_headers,
        workspace_id=workspace["id"],
        user_id=member["id"],
    )

    member_add_response = await smoke_client.post(
        f"/api/v1/workspaces/{workspace['id']}/members",
        headers=member_headers,
        json={"user_id": target["id"], "role": "member"},
    )
    smoke_helpers.assert_error_response(member_add_response, 403, "PERMISSION_DENIED")
