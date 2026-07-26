import pytest

from app.core.edition import AppEdition, policy_for


def test_cloud_exposes_only_hosted_product_controls():
    policy = policy_for(AppEdition.CLOUD)

    assert policy.supported_mcp_transports == ("streamable_http",)
    assert not policy.allow_provider_connection_overrides
    assert set(policy.managed_ai_roles) == {
        "embedding",
        "reranker",
        "transcription",
        "diarization",
    }


def test_community_exposes_advanced_controls():
    policy = policy_for(AppEdition.COMMUNITY)

    assert "stdio" in policy.supported_mcp_transports
    assert policy.allow_provider_connection_overrides
    assert policy.show_advanced_model_settings


def test_cloud_rejects_non_official_provider_endpoint():
    policy = policy_for(AppEdition.CLOUD)

    with pytest.raises(ValueError, match="official provider endpoints"):
        policy.validate_provider_patch(
            {
                "api_base_override": "https://gateway.example.com/v1",
            }
        )

    policy.validate_provider_patch({"enabled": True})
    policy.validate_provider_patch({"api_base_override": ""})
