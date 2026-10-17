"""Deterministic test identity provider used by protocol and browser tests."""

lazy import base64
lazy import hashlib
lazy import html
lazy import secrets
lazy import time
lazy from typing import Any
lazy from urllib.parse import parse_qs, urlencode

lazy import httpx2
lazy from joserfc import jwt
lazy from joserfc.jwk import ECKey, RSAKey


class TestOIDCProvider:
    """Serve discovery, one-use codes, PKCE checks, and real signed ID tokens."""

    __test__ = False

    def __init__(self, issuer: str = "https://idp.example.test") -> None:
        self.issuer = issuer
        self.key: RSAKey | ECKey = RSAKey.generate_key(
            2048, parameters={"kid": "first"}
        )
        self.claim_overrides: dict[str, Any] = {}
        self.metadata_overrides: dict[str, Any] = {}
        self.codes: dict[str, dict[str, str]] = {}
        self.requests: list[httpx2.Request] = []
        self.fail_path = ""

    def authorize(self, url: str) -> tuple[str, str]:
        params = {
            key: values[0]
            for key, values in parse_qs(httpx2.URL(url).query.decode()).items()
        }
        code = secrets.token_urlsafe(24)
        self.codes[code] = params
        return code, params["state"]

    def handle(self, request: httpx2.Request) -> httpx2.Response:
        """HTTPX mock transport and local HTTP server share these protocol handlers."""
        self.requests.append(request)
        path = request.url.path
        if path.endswith(self.fail_path) and self.fail_path:
            return httpx2.Response(503)
        if path.endswith("/.well-known/openid-configuration"):
            return httpx2.Response(
                200,
                json={
                    "issuer": self.issuer,
                    "authorization_endpoint": f"{self.issuer}/authorize",
                    "token_endpoint": f"{self.issuer}/token",
                    "jwks_uri": f"{self.issuer}/jwks",
                    "end_session_endpoint": f"{self.issuer}/logout",
                    "code_challenge_methods_supported": ["S256"],
                    "id_token_signing_alg_values_supported": ["RS256", "ES256"],
                    **self.metadata_overrides,
                },
            )
        if path.endswith("/jwks"):
            return httpx2.Response(
                200, json={"keys": [self.key.as_dict(private=False)]}
            )
        if path.endswith("/authorize"):
            code, state = self.authorize(str(request.url))
            params = self.codes[code]
            callback = (
                params["redirect_uri"] + "?" + urlencode({"code": code, "state": state})
            )
            return httpx2.Response(
                200,
                text=(
                    f'<html><a href="{html.escape(callback)}">'
                    "Approve sign-in</a></html>"
                ),
                headers={"content-type": "text/html"},
            )
        if path.endswith("/token"):
            return self._token(request)
        if path.endswith("/logout"):
            params = parse_qs(request.url.query.decode())
            return httpx2.Response(
                302, headers={"location": params["post_logout_redirect_uri"][0]}
            )
        return httpx2.Response(404)

    def _token(self, request: httpx2.Request) -> httpx2.Response:
        form = parse_qs(request.content.decode())
        basic = "Basic " + base64.b64encode(b"overture:test-client-secret").decode()
        if request.headers.get("authorization") != basic:
            return httpx2.Response(401, json={"error": "invalid_client"})
        params = self.codes.pop(form.get("code", [""])[0], None)
        if params is None:
            return httpx2.Response(400, json={"error": "invalid_grant"})
        verifier = form.get("code_verifier", [""])[0]
        challenge = base64.urlsafe_b64encode(
            hashlib.sha256(verifier.encode()).digest(), padded=False
        ).decode()
        if challenge != params["code_challenge"] or form.get("redirect_uri") != [
            params["redirect_uri"]
        ]:
            return httpx2.Response(400, json={"error": "invalid_grant"})
        claims = {
            "iss": self.issuer,
            "sub": "admin-123",
            "aud": "overture",
            "iat": int(time.time()),
            "exp": int(time.time()) + 300,
            "nonce": params["nonce"],
            "groups": ["overture-admins"],
            **self.claim_overrides,
        }
        return httpx2.Response(
            200,
            json={
                "access_token": "test-access",
                "token_type": "Bearer",
                "id_token": jwt.encode(
                    {
                        "alg": "RS256" if isinstance(self.key, RSAKey) else "ES256",
                        "kid": self.key.kid,
                    },
                    claims,
                    self.key,
                ),
            },
        )
