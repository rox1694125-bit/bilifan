import pytest

from bilifan.web.security import TokenAuth, generate_token


def test_generate_token_is_urlsafe_and_long_enough():
    token = generate_token()

    assert len(token) >= 32
    assert "/" not in token
    assert "+" not in token


def test_token_auth_accepts_matching_header_or_query():
    auth = TokenAuth("secret-token")

    auth.require(header_token="secret-token", query_token=None)
    auth.require(header_token=None, query_token="secret-token")


def test_token_auth_rejects_missing_or_wrong_token():
    auth = TokenAuth("secret-token")

    with pytest.raises(PermissionError):
        auth.require(header_token=None, query_token=None)
    with pytest.raises(PermissionError):
        auth.require(header_token="wrong", query_token=None)
