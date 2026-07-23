"""AL-59: server-side logout revokes outstanding tokens.

token_version is embedded in every JWT as `tv` and checked on decode, so logout
bumps it and every access + refresh token minted before then stops validating —
a leaked/logged-out refresh token no longer lives to its 14d expiry.
"""


def _login(client, email="alex@ascme-labs.com"):
    r = client.post("/api/auth/login", json={"email": email, "password": "agentledger"})
    assert r.status_code == 200, r.text
    return r.json()


def test_logout_revokes_access_token(client):
    tok = _login(client)
    auth = {"Authorization": f"Bearer {tok['access_token']}"}

    assert client.get("/api/auth/me", headers=auth).status_code == 200
    assert client.post("/api/auth/logout", headers=auth).status_code == 204
    # The very same access token is now dead, though its signature/exp are still valid.
    r = client.get("/api/auth/me", headers=auth)
    assert r.status_code == 401
    assert "revoked" in r.text


def test_logout_revokes_refresh_token(client):
    tok = _login(client)
    auth = {"Authorization": f"Bearer {tok['access_token']}"}

    # Refresh works before logout.
    assert client.post("/api/auth/refresh", json={"refresh_token": tok["refresh_token"]}).status_code == 200

    assert client.post("/api/auth/logout", headers=auth).status_code == 204
    r = client.post("/api/auth/refresh", json={"refresh_token": tok["refresh_token"]})
    assert r.status_code == 401
    assert "revoked" in r.text


def test_relogin_issues_working_tokens_after_logout(client):
    """Logout must not brick the account: a fresh login mints tokens at the new
    epoch that validate again."""
    first = _login(client)
    client.post("/api/auth/logout", headers={"Authorization": f"Bearer {first['access_token']}"})

    second = _login(client)
    assert second["access_token"] != first["access_token"]
    ok = client.get("/api/auth/me", headers={"Authorization": f"Bearer {second['access_token']}"})
    assert ok.status_code == 200


def test_logout_is_per_user(client):
    """One user's logout leaves another user's session untouched."""
    alex = _login(client, "alex@ascme-labs.com")
    kate = _login(client, "kate@ascme-labs.com")

    client.post("/api/auth/logout", headers={"Authorization": f"Bearer {alex['access_token']}"})

    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {kate['access_token']}"}).status_code == 200
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {alex['access_token']}"}).status_code == 401


def test_logout_requires_auth(client):
    assert client.post("/api/auth/logout").status_code == 401
