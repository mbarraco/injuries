import pytest

from app import auth


def test_accepts_the_configured_credentials(monkeypatch):
    monkeypatch.setenv(auth.USER_VAR, "alice")
    monkeypatch.setenv(auth.PASSWORD_VAR, "s3cret")
    assert auth.verify("alice", "s3cret") is True


@pytest.mark.parametrize("username, password", [
    ("alice", "wrong"),
    ("bob", "s3cret"),
    ("", ""),
])
def test_rejects_anything_else(monkeypatch, username, password):
    monkeypatch.setenv(auth.USER_VAR, "alice")
    monkeypatch.setenv(auth.PASSWORD_VAR, "s3cret")
    assert auth.verify(username, password) is False


@pytest.mark.parametrize("missing", [auth.USER_VAR, auth.PASSWORD_VAR])
def test_refuses_to_authenticate_when_credentials_are_unset(monkeypatch, missing):
    """Unset credentials must fail closed, never authenticate everyone.

    This is the failure that matters: a plain getenv default would compare
    None to None and let the whole world in, silently.
    """
    monkeypatch.setenv(auth.USER_VAR, "alice")
    monkeypatch.setenv(auth.PASSWORD_VAR, "s3cret")
    monkeypatch.delenv(missing)
    with pytest.raises(RuntimeError, match="refusing to serve"):
        auth.verify("alice", "s3cret")


def test_handles_non_ascii_input_without_crashing(monkeypatch):
    """compare_digest rejects non-ASCII str, so input must be encoded first."""
    monkeypatch.setenv(auth.USER_VAR, "alice")
    monkeypatch.setenv(auth.PASSWORD_VAR, "s3cret")
    assert auth.verify("álice", "pässword") is False
