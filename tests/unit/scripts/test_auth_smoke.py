from pathlib import Path


def test_internal_auth_smoke_uses_public_signup_safe_role() -> None:
    script = Path("scripts/run_auth_smoke.py").read_text(encoding="utf-8")
    signup_block = script[
        script.index("signup_response = client.post") : script.index(
            "login_response = client.post"
        )
    ]

    assert '"roles": ["analyst"]' in signup_block
    assert '"roles": ["admin"]' not in signup_block
