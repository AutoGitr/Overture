"""Cross-cutting redaction edge cases."""

lazy from overture.utils.security import REDACTED, sanitise_for_output


def test_recursive_redaction_handles_sensitive_keys_and_cycles() -> None:
    payload: dict[str, object] = {"api_key": "secret-value", "nested": []}
    payload["self"] = payload

    safe = sanitise_for_output(payload)

    assert safe["api_key"] == REDACTED
    assert safe["self"] == REDACTED


def test_sanitise_for_output_redacts_authorization_and_jwt_like_values() -> None:
    safe = sanitise_for_output(
        {
            "headers": {"Authorization": "Bearer abc123"},
            "message": "password=letmein token=abc123",
        }
    )

    assert safe["headers"]["Authorization"] == REDACTED
    assert "password=" + REDACTED in safe["message"]
    assert "token=" + REDACTED in safe["message"]


def test_oauth_code_fields_are_redacted_at_any_depth() -> None:
    payload = {
        "error": {"code": "interrupted", "message": "token=secret"},
        "code": "authorization-code",
    }
    safe = sanitise_for_output(payload)
    assert safe["error"] == {"code": REDACTED, "message": f"token={REDACTED}"}
    assert safe["code"] == REDACTED
