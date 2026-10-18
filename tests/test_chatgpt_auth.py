import pytest

from mini_agent.chatgpt import auth
from mini_agent.chatgpt.credentials import CredentialRecord


def test_pkce_pair() -> None:
    verifier, challenge = auth._pkce_pair()

    assert len(verifier) >= 43
    assert challenge != verifier
    assert "=" not in challenge


def test_authorization_url_for_new_registration() -> None:
    url = auth._authorization_url(
        "https://auth.openai.com/api/accounts/authorize",
        client_id="dynamic_agent_client",
        redirect_uri="http://127.0.0.1:1234/auth/callback",
        state="state",
        nonce="nonce",
        challenge="challenge",
        host_id_value="urn:uuid:test",
        existing=None,
    )

    assert "client_id=dynamic_agent_client" in url
    assert "agent_name_hint=mini-agent" in url
    assert "ext_agent_host_id=urn%3Auuid%3Atest" in url
    assert "code_challenge_method=S256" in url
    assert "scope=openid+profile+email" in url


def test_authorization_url_for_returning_registration() -> None:
    existing = CredentialRecord(
        client_id="oaiapp_test",
        access_token="access",
        refresh_token="refresh",
        expires_at=0,
        scopes=["chatgpt.tokens.use.direct"],
        subject="subject",
        email="user@example.com",
    )

    url = auth._authorization_url(
        "https://auth.openai.com/api/accounts/authorize",
        client_id="oaiapp_test",
        redirect_uri="http://127.0.0.1:1234/auth/callback",
        state="state",
        nonce="nonce",
        challenge="challenge",
        host_id_value="urn:uuid:test",
        existing=existing,
    )

    assert "client_id=oaiapp_test" in url
    assert "agent_name_hint" not in url
    assert "login_hint=user%40example.com" in url


def test_logout_warns_when_revocation_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = CredentialRecord(
        client_id="oaiapp_test",
        access_token="access",
        refresh_token="refresh",
        expires_at=0,
        scopes=["chatgpt.tokens.use.direct"],
        subject="subject",
    )
    monkeypatch.setattr(auth, "load_credentials", lambda: record)
    monkeypatch.setattr(auth, "clear_credentials", lambda: None)
    monkeypatch.setattr(
        auth,
        "discover",
        lambda: type(
            "D",
            (),
            {"revocation_endpoint": "https://auth.openai.com/oauth/revoke"},
        )(),
    )
    monkeypatch.setattr(
        auth, "post_form", lambda *args, **kwargs: (_ for _ in ()).throw(OSError())
    )

    warning = auth.logout()

    assert warning is not None
    assert "could not be confirmed" in warning
