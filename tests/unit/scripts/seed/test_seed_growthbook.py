"""Unit tests for GrowthBook seed payload generation."""

from scripts.seed.seed_growthbook import (
    _build_flag_payload,
    _merge_generated_environment_rules,
)


def test_build_flag_payload_includes_smoke_closed_beta_override() -> None:
    payload = _build_flag_payload(
        "enable-closed-beta-login",
        False,
        {
            "local": {"enable-closed-beta-login": True},
            "smoke": {"enable-closed-beta-login": False},
            "prod": {"enable-closed-beta-login": True},
        },
        "project-id",
        "owner@example.com",
        ["local", "smoke", "prod"],
    )

    assert payload["environments"] == {
        "local": {
            "enabled": True,
            "rules": [
                {
                    "description": "Override for local",
                    "condition": '{"env": "local"}',
                    "id": "env-override-local",
                    "enabled": True,
                    "type": "force",
                    "value": "true",
                },
            ],
        },
        "smoke": {"enabled": True},
        "prod": {
            "enabled": True,
            "rules": [
                {
                    "description": "Override for prod",
                    "condition": '{"env": "prod"}',
                    "id": "env-override-prod",
                    "enabled": True,
                    "type": "force",
                    "value": "true",
                },
            ],
        },
    }


def test_build_flag_payload_keeps_smoke_ai_flags_on_default() -> None:
    payload = _build_flag_payload(
        "enable-llm-model-routing",
        False,
        {
            "local": {"enable-llm-model-routing": True},
            "smoke": {"enable-llm-model-routing": False},
            "prod": {"enable-llm-model-routing": True},
        },
        "project-id",
        "owner@example.com",
        ["local", "smoke", "prod"],
    )

    assert [rule["id"] for rule in payload["environments"]["local"]["rules"]] == [
        "env-override-local"
    ]
    assert "rules" not in payload["environments"]["smoke"]
    assert [rule["id"] for rule in payload["environments"]["prod"]["rules"]] == [
        "env-override-prod"
    ]


def test_merge_generated_environment_rules_preserves_manual_rules() -> None:
    merged = _merge_generated_environment_rules(
        {
            "local": {
                "enabled": True,
                "rules": [
                    {"id": "manual-rollout", "value": "false"},
                    {"id": "env-override-local", "value": "false"},
                ],
            },
            "prod": {
                "enabled": False,
                "rules": [{"id": "manual-prod-rule", "value": "true"}],
            },
        },
        {
            "local": {
                "enabled": True,
                "rules": [{"id": "env-override-local", "value": "true"}],
            },
            "smoke": {"enabled": True},
        },
        ["local", "smoke"],
    )

    assert merged == {
        "local": {
            "enabled": True,
            "rules": [
                {"id": "manual-rollout", "value": "false"},
                {"id": "env-override-local", "value": "true"},
            ],
        },
        "prod": {
            "enabled": False,
            "rules": [{"id": "manual-prod-rule", "value": "true"}],
        },
        "smoke": {"enabled": True},
    }
