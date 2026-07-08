"""http_transport:Bearer 認證(401/通過/非 http 透傳)、/health。"""

import asyncio
import json

import http_transport
import kb_config


class _InnerApp:
    def __init__(self):
        self.called = False

    async def __call__(self, scope, receive, send):
        self.called = True


async def _noop_receive():
    return {}


def _run_asgi(app, scope):
    sent = []

    async def send(message):
        sent.append(message)

    asyncio.run(app(scope, _noop_receive, send))
    return sent


class TestBearerTokenGuard:
    def _scope(self, token=None):
        headers = []
        if token is not None:
            headers.append((b"authorization", f"Bearer {token}".encode()))
        return {"type": "http", "headers": headers, "path": "/mcp",
                "client": ("1.2.3.4", 1)}

    def test_missing_token_401(self):
        inner = _InnerApp()
        guard = http_transport.BearerTokenGuard(inner, "s3cret")
        sent = _run_asgi(guard, self._scope())
        assert sent[0]["status"] == 401
        assert not inner.called

    def test_wrong_token_401(self):
        inner = _InnerApp()
        guard = http_transport.BearerTokenGuard(inner, "s3cret")
        sent = _run_asgi(guard, self._scope("wrong"))
        assert sent[0]["status"] == 401

    def test_correct_token_passes_through(self):
        inner = _InnerApp()
        guard = http_transport.BearerTokenGuard(inner, "s3cret")
        sent = _run_asgi(guard, self._scope("s3cret"))
        assert inner.called and sent == []

    def test_non_http_scope_passthrough(self):
        inner = _InnerApp()
        guard = http_transport.BearerTokenGuard(inner, "s3cret")
        _run_asgi(guard, {"type": "lifespan"})
        assert inner.called


class TestHealthEndpoint:
    def test_health_served_without_auth(self, demo_config):
        endpoint = http_transport.HealthEndpoint(_InnerApp())
        sent = _run_asgi(endpoint, {"type": "http", "path": "/health",
                                    "method": "GET"})
        assert sent[0]["status"] == 200
        payload = json.loads(sent[1]["body"])
        assert payload["status"] == "ok"
        assert payload["apps"][0]["name"] == "demo"

    def test_other_paths_passthrough(self, demo_config):
        inner = _InnerApp()
        endpoint = http_transport.HealthEndpoint(inner)
        _run_asgi(endpoint, {"type": "http", "path": "/mcp", "method": "POST"})
        assert inner.called


class TestHealthPayload:
    def test_ok_with_fixture_app(self, demo_config):
        payload = http_transport.health_payload()
        app = payload["apps"][0]
        assert app["repo"] is True          # fixture-app 存在
        assert app["codegraph"] is False    # fixture 沒建圖
        assert app["semantic"] is False

    def test_config_error_reported(self, tmp_path, monkeypatch):
        monkeypatch.setattr(kb_config, "CONFIG_PATH", tmp_path / "nope.yaml")
        kb_config._cache["stamp"] = None
        payload = http_transport.health_payload()
        assert payload["status"] == "config-error"
        kb_config._cache["stamp"] = None
