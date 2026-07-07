"""HTTP transport(集中部署用):Bearer 認證、GET /health、uvicorn 啟動。

stdio 模式用不到本模組;kb_server 於 KB_TRANSPORT=http 時呼叫 run(mcp)。
/health 刻意免認證(監控用;僅索引狀態,無敏感資料),在 token guard 外層。
"""

import json
import os

import graph_db
import kb_config
import kb_log

log = kb_log.setup()


class BearerTokenGuard:
    """極簡 ASGI middleware:KB_AUTH_TOKEN 設定時強制 Bearer token。

    比對用 hmac.compare_digest(常數時間),失敗回 401;不做使用者/權限概念
    ——本 server 全域唯讀,token 只擋「不是團隊的人」。
    """

    def __init__(self, app, token: str):
        self._app = app
        self._token = token

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        import hmac
        # 全程 bytes 比對:str 版 compare_digest 遇非 ASCII 會 raise,
        # decode 遇非 UTF-8 也會 raise——惡意 header 應得到 401 而非 500
        header = dict(scope.get("headers") or []).get(b"authorization", b"")
        expected = f"Bearer {self._token}".encode()
        if not hmac.compare_digest(header, expected):
            client = (scope.get("client") or ("?", 0))[0]
            log.warning("HTTP 401 Bearer 驗證失敗 client=%s path=%s",
                        client, scope.get("path", ""))
            await send({"type": "http.response.start", "status": 401,
                        "headers": [(b"content-type", b"text/plain; charset=utf-8"),
                                    (b"www-authenticate", b"Bearer")]})
            await send({"type": "http.response.body",
                        "body": "缺少或錯誤的 Authorization Bearer token。".encode()})
            return
        await self._app(scope, receive, send)


def health_payload() -> dict:
    """GET /health 的內容:server 存活 + 各 AP 索引狀態(監控/排程檢查用)。"""
    try:
        config = kb_config.load_config()
    except ValueError as exc:
        return {"status": "config-error", "detail": str(exc)}
    from semantic_common import index_paths
    apps = []
    for app in config.apps:
        paths = index_paths(app)
        entry = {
            "name": app.name,
            "repo": app.repo_root.is_dir(),
            "codegraph": graph_db.available(app),
            "semantic": paths.all_exist(),
            "built_at": None,
        }
        if entry["semantic"]:
            try:
                entry["built_at"] = json.loads(
                    paths.state.read_text(encoding="utf-8")).get("built_at")
            except (OSError, ValueError):
                pass
        apps.append(entry)
    return {"status": "ok", "apps": apps}


class HealthEndpoint:
    """GET /health:免認證(刻意,監控用;僅索引狀態,無敏感資料),其餘透傳。"""

    def __init__(self, app):
        self._app = app

    async def __call__(self, scope, receive, send):
        if (scope["type"] == "http" and scope.get("path") == "/health"
                and scope.get("method") == "GET"):
            body = json.dumps(health_payload(), ensure_ascii=False).encode()
            await send({"type": "http.response.start", "status": 200,
                        "headers": [(b"content-type", b"application/json; charset=utf-8")]})
            await send({"type": "http.response.body", "body": body})
            return
        await self._app(scope, receive, send)


def run(mcp) -> None:
    """集中部署:streamable HTTP(使用者端的 Connector URL 指到 /mcp)。"""
    import uvicorn
    app = mcp.streamable_http_app()
    token = os.environ.get("KB_AUTH_TOKEN", "")
    if token:
        app = BearerTokenGuard(app, token)
    else:
        log.warning("KB_AUTH_TOKEN 未設定,HTTP 模式無認證——僅限信任內網使用。")
    app = HealthEndpoint(app)  # health 在 token guard 外層,監控不需帶 token
    log.info("啟動 transport=http %s:%d auth=%s",
             mcp.settings.host, mcp.settings.port, "bearer" if token else "無")
    uvicorn.run(app, host=mcp.settings.host, port=mcp.settings.port)
