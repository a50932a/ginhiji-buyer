"""HTTP 用戶端測試。不連到正式訂單服務。"""

from __future__ import annotations

import socket
from pathlib import Path

import httpx
import pytest

from sync.client import USER_AGENT, OrdersClient
from sync.errors import AuthError, SourceError


def resolver(host, *_args, **_kwargs):
    address = "127.0.0.1" if host == "evil.example" else "1.1.1.1"
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 0))]


def test_user_agent_and_redirect_do_not_carry_token():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.url.host, request.headers.get("authorization"), request.headers.get("user-agent"), request.method))
        if request.url.host == "money.klab.tw":
            return httpx.Response(302, headers={"location": "https://cdn.example/a.jpg"})
        return httpx.Response(200, content=b"\xff\xd8\xff\xd9", headers={"content-type": "image/jpeg", "etag": '"img"'})

    client = OrdersClient("secret-token-value", transport=httpx.MockTransport(handler), resolver=resolver)
    body, etag = client.get_image("/api/images/abc123def456")
    assert body.startswith(b"\xff\xd8")
    assert etag == '"img"'
    assert seen[0][0] == "money.klab.tw"
    assert seen[0][1] == "Bearer secret-token-value"
    assert seen[0][2] == USER_AGENT
    assert seen[0][3] == "GET"
    assert seen[1][0] == "cdn.example"
    assert seen[1][1] is None
    assert "secret-token-value" not in repr(client)
    client.close()


def test_private_redirect_is_blocked_before_the_second_request():
    hosts = []

    def handler(request: httpx.Request) -> httpx.Response:
        hosts.append(request.url.host)
        return httpx.Response(302, headers={"location": "https://evil.example/secret.jpg"})

    client = OrdersClient("secret-token-value", transport=httpx.MockTransport(handler), resolver=resolver)
    with pytest.raises(SourceError, match="公開位址"):
        client.get_image("/api/images/abc123def456")
    assert hosts == ["money.klab.tw"]
    client.close()


def test_unauthorized_error_hides_body():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "unauthorized", "token": "secret-token-value"})

    client = OrdersClient("secret-token-value", transport=httpx.MockTransport(handler), resolver=resolver)
    with pytest.raises(AuthError) as caught:
        client.list_groups()
    assert "secret-token-value" not in str(caught.value)
    assert caught.value.__cause__ is None
    client.close()


def test_client_source_is_read_only_and_does_not_read_home_token():
    root = Path(__file__).resolve().parents[1]
    source = (root / "sync" / "client.py").read_text(encoding="utf-8")
    package = "\n".join(path.read_text(encoding="utf-8") for path in (root / "sync").glob("*.py"))
    assert '"POST"' not in source
    assert '"PATCH"' not in source
    assert '"DELETE"' not in source
    assert "urllib.request" not in package
    assert ".config/money-orders" not in package
