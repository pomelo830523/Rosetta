"""NL Query KB MCP server:一台唯讀 server 服務 N 個 AP(kb.config.yaml)。

7 個 tools;查詢工作流慣例寫在 MCP instructions(SPEC §4.6)。

環境變數:
  KB_ENGINE     = auto | semantic | grep(覆蓋設定檔)
  KB_TRANSPORT  = stdio(預設)| http(集中部署用 streamable HTTP)
  KB_HTTP_HOST / KB_HTTP_PORT = http 綁定位址(預設 127.0.0.1:8600)
  KB_AUTH_TOKEN = http 模式的 Bearer 認證;未設定 = 無認證,僅限信任內網
啟動:python kb_server.py
"""

import functools
import os
import time

from mcp.server.fastmcp import FastMCP

import app_config
import code_search
import db_config
import glossary
import graph_db
import kb_config
import kb_log

log = kb_log.setup()

# 設定壞掉時 fail fast,錯誤訊息進 MCP log。
# 注意:instructions 內的 AP 清單在這裡烘進字串,新增/移除 AP 後需重啟 server
# (tools 本身每次呼叫都重讀設定,編輯白名單/路徑等仍即時生效)。
_config = kb_config.load_config()
log.info("設定載入:%d 個 AP(%s)", len(_config.apps), ", ".join(_config.app_names()))

_INSTRUCTIONS = f"""本 server 是唯讀的「系統邏輯知識庫」,服務多個 AP。回答使用者問題時遵守:

1. 先判斷問題屬於哪個 AP,tools 都要帶 app 參數;不確定時先呼叫 list_apps
   看各系統描述,仍不確定就問使用者,不要跨 AP 亂猜。
   目前管理的 AP:{"、".join(f"{a.name}({a.description})" for a in _config.apps)}
2. 檢索前先把使用者問題改寫成兩組檢索詞:zh 業務詞 + en IT 詞
   (語料是英文 identifier + 中文註解;使用者用任何語言提問都先這樣歸一化)。
3. 業務用語先用 lookup_term 取得精確的 IT 對應(class/欄位/config key),
   再用 search_code 找實作。
4. 公式散在呼叫鏈上時,用 get_structure 追 callers/callees。
5. 權重、規則、門檻、連線這類「現值」必查 query_db_config / get_app_config,
   不得引用程式碼或 migration 裡的舊值。
6. 回答一律附依據(app 名 + 檔名:行號 / config key / DB 現值),
   用使用者提問的語言作答;查不到就明說,不要編造。
7. 遇到歧義先向使用者做「選項式釐清」再繼續查。歧義訊號包括:
   (a) 工具回傳標註「歧義訊號」(lookup_term 命中多個概念、search_code 結果
       分散或無結果附選項素材);
   (b) query_db_config 回傳的資料中,符合使用者所指對象的有**多筆**
       (如同名房屋)——以識別欄位(ID/名稱/樓層/價格等)列選項請使用者確認是哪一筆,
       不要自行挑一筆作答。
   選項一律取自工具回傳的真實候選,最多問一次、1~2 個問題;問題清楚時不反問。"""

mcp = FastMCP(
    _config.server_name,
    instructions=_INSTRUCTIONS,
    host=os.environ.get("KB_HTTP_HOST", "127.0.0.1"),
    port=int(os.environ.get("KB_HTTP_PORT", "8600")),
)


_resolve = kb_config.resolve_app


def _logged(fn):
    """tool 呼叫記錄:參數摘要、結果大小、耗時;未預期例外記完整 traceback。

    functools.wraps 保留簽名與型別註記,FastMCP 產生 tool schema 不受影響。
    """
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        summary = ", ".join(
            f"{k}={kb_log.brief(str(v))}" for k, v in kwargs.items() if v not in ("", None)
        ) or kb_log.brief(", ".join(str(a) for a in args))
        started = time.perf_counter()
        try:
            result = fn(*args, **kwargs)
        except Exception:
            log.exception("tool=%s(%s)未預期例外", fn.__name__, summary)
            raise
        elapsed_ms = (time.perf_counter() - started) * 1000
        log.info("tool=%s(%s)→ %d 字元,%.0fms", fn.__name__, summary, len(result), elapsed_ms)
        return result
    return wrapper


@mcp.tool()
@_logged
def list_apps() -> str:
    """列出本 server 管理的所有 AP(系統)與描述。

    不確定使用者的問題屬於哪個系統時先呼叫本工具,再帶正確的 app 參數查詢。
    """
    config = kb_config.load_config()
    lines = []
    for app in config.apps:
        status = []
        if not app.repo_root.is_dir():
            status.append("repo 路徑不存在,請通知管理員")
        if not glossary.load_glossary(app.glossary_path):
            status.append("尚無對照表")
        suffix = f"({'; '.join(status)})" if status else ""
        lines.append(f"- {app.name}:{app.description}{suffix}")
    return f"共 {len(config.apps)} 個 AP:\n" + "\n".join(lines)


def _independent_concepts(query: str, matched: list) -> list:
    """S1 輔助:去除「命中字串被其他條目更長命中包含」的條目。

    例:「不含車位單價怎麼算」同時命中「不含車位單價」與「車位」,
    但「車位」只是前者的子字串,不構成獨立歧義。
    """
    longest = {
        e.term: max(glossary.matched_candidates(query, e), key=len)
        for e in matched
    }
    independent = []
    for entry in matched:
        mine = longest[entry.term].lower()
        covered = any(
            mine != other.lower() and mine in other.lower()
            for other in longest.values()
        )
        if not covered:
            independent.append(entry)
    return independent


@mcp.tool()
@_logged
def lookup_term(query: str, app: str = "") -> str:
    """查指定 AP 的「業務用語 ↔ IT 用語」對照表。輸入使用者口語(如「權重」「被刷掉」),
    回傳對應的 class/method/DB 欄位/config key 與說明,作為後續搜尋的錨點。

    找不到對照時建議直接用 search_code 以原詞搜尋。
    """
    ctx, error = _resolve(app)
    if ctx is None:
        return error
    entries = glossary.load_glossary(ctx.glossary_path)
    if not entries:
        return f"app「{ctx.name}」的 glossary({ctx.glossary_path.name})不存在或無條目。"
    matched = glossary.match_entries(query, entries)
    if not matched:
        all_terms = "、".join(e.term for e in entries)
        return f"沒有符合「{query}」的對照條目。已收錄的業務用語:{all_terms}"
    hint = ""
    concepts = _independent_concepts(query, matched)
    if len(concepts) >= 2:
        names = "、".join(e.term for e in concepts)
        log.info("S1 歧義訊號 app=%s query=%s concepts=%s",
                 ctx.name, kb_log.brief(query), names)
        hint = (f"(歧義訊號:「{query}」命中 {len(concepts)} 個不同概念——{names}。"
                "若無法從使用者的問題判斷是哪一個,請先以這些概念為選項向使用者確認,"
                "再繼續檢索;若問題本身已可區分則直接繼續。)\n\n")
    return hint + glossary.format_entries(matched)


def _engine(ctx: kb_config.AppContext) -> str:
    forced = os.environ.get("KB_ENGINE", "") or ctx.engine
    if forced in ("semantic", "grep"):
        return forced
    try:
        import semantic_search
        return "semantic" if semantic_search.available(ctx) else "grep"
    except ImportError:
        return "grep"


def _call_chain_summary(qualified_name: str, ctx: kb_config.AppContext) -> str:
    """一層呼叫鏈摘要(GraphRAG:語意命中的「點」接上「線」)。"""
    if not graph_db.available(ctx):
        return ""
    nodes = graph_db.find_nodes(qualified_name.split("::")[-1], ctx, limit=3)
    exact = [n for n in nodes if n.qualified_name == qualified_name]
    if not exact:
        return ""
    node = exact[0]
    callers = {s.qualified_name for _, s in graph_db.callers(node.node_id, ctx)}
    callees = {s.qualified_name for _, s in graph_db.callees(node.node_id, ctx)}
    parts = []
    if callers:
        parts.append(f"被誰用:{', '.join(sorted(callers)[:5])}")
    if callees:
        parts.append(f"用了誰:{', '.join(sorted(callees)[:5])}")
    return ";".join(parts)


def _read_body(file_path: str, start_line: int, end_line: int,
               ctx: kb_config.AppContext) -> str:
    target = ctx.repo_root / file_path
    try:
        lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return "(讀不到原始碼)"
    start = max(0, start_line - 1)
    end = min(len(lines), max(end_line, start_line))
    return code_search.truncate_body("\n".join(lines[start:end]))


_SCATTER_DELTA = 0.03      # S2:top1 − top3 分數差小於此值視為「沒有明確贏家」
_SCATTER_MIN_CLASSES = 3   # S2:命中散在 ≥ 此數量的 class 才視為分散


def _scatter_note(hits) -> str:
    """S2 檢索分散訊號(SPEC §4.8):分數平坦且命中散在多個 class 時建議釐清。"""
    if len(hits) < 3 or hits[0].score - hits[2].score >= _SCATTER_DELTA:
        return ""
    classes: list[str] = []
    for h in hits:
        parts = h.qualified_name.split("::")
        cls = parts[-2] if len(parts) >= 2 else h.file_path
        if cls not in classes:
            classes.append(cls)
    if len(classes) < _SCATTER_MIN_CLASSES:
        return ""
    log.info("S2 結果分散 classes=%s(top1-top3=%.3f)",
             "、".join(classes[:5]), hits[0].score - hits[2].score)
    return (f"\n\n(歧義訊號:結果分散——前幾名分數接近且散在 {len(classes)} 個模組:"
            f"{'、'.join(classes[:5])}。若不確定使用者要問哪個功能,"
            "請先以這些模組對應的功能為選項向使用者釐清。)")


def _glossary_domain_hint(ctx: kb_config.AppContext) -> str:
    """S3 檢索空手訊號(SPEC §4.8):附該 AP 的業務概念清單當釐清選項素材。"""
    entries = glossary.load_glossary(ctx.glossary_path)
    if not entries:
        return ""
    terms = "、".join(e.term for e in entries)
    return (f"\n(選項素材:此 AP 已收錄的業務概念——{terms}。"
            "可挑貼近使用者問題的幾個概念為選項,向使用者確認方向後再查。)")


def _search_semantic(query: str, top_k: int, extra_terms, matched_entries,
                     ctx: kb_config.AppContext, include_call_chain: bool) -> str:
    import semantic_search
    hits = semantic_search.search(query, top_k, extra_terms, ctx)
    if not hits:
        log.info("S3 檢索空手 app=%s engine=semantic query=%s",
                 ctx.name, kb_log.brief(query))
        return ("語意索引無足夠相關的結果。可先用 lookup_term 確認業務用語,"
                "或以 IT 詞重查。" + _glossary_domain_hint(ctx))
    log.info("search app=%s engine=semantic hits=%d top=%s(%.3f)",
             ctx.name, len(hits), hits[0].qualified_name, hits[0].score)
    parts = [f"(app={ctx.name},engine=semantic,{semantic_search.index_info(ctx)})"]
    if matched_entries:
        expanded = "、".join(f"{e.term}→{'/'.join(e.it_terms[:3])}" for e in matched_entries)
        parts.append(f"(glossary 展開:{expanded})")
    for h in hits:
        header = (f"### {h.file_path}:{h.start_line}-{h.end_line} — "
                  f"{h.qualified_name}({h.kind},score={h.score})")
        body = _read_body(h.file_path, h.start_line, h.end_line, ctx)
        block = f"{header}\n```\n{body}\n```"
        if include_call_chain:
            chain = _call_chain_summary(h.qualified_name, ctx)
            if chain:
                block += f"\n呼叫鏈:{chain}"
        parts.append(block)
    return "\n\n".join(parts) + _scatter_note(hits)


def _search_grep(query: str, top_k: int, extra_terms, matched_entries,
                 ctx: kb_config.AppContext) -> str:
    results = code_search.search(query, top_k, extra_terms, ctx)
    if not results:
        log.info("S3 檢索空手 app=%s engine=grep query=%s", ctx.name, kb_log.brief(query))
        return ("找不到相關程式碼。可先用 lookup_term 確認業務用語的 IT 對照,"
                "再以 IT 詞重查。" + _glossary_domain_hint(ctx))
    log.info("search app=%s engine=grep(墊檔)hits=%d", ctx.name, len(results))
    parts = [f"(app={ctx.name},engine=grep,全掃描 fallback)"]
    if matched_entries:
        hits = "、".join(f"{e.term}→{'/'.join(e.it_terms[:3])}" for e in matched_entries)
        parts.append(f"(glossary 展開:{hits})")
    for _, rel, start, end, body in results:
        parts.append(f"### {rel}:{start}-{end}\n```\n{code_search.truncate_body(body)}\n```")
    return "\n\n".join(parts)


@mcp.tool()
@_logged
def search_code(query: str, top_k: int = 3, app: str = "",
                include_call_chain: bool = True) -> str:
    """用自然語言搜尋指定 AP 的原始碼,回傳最相關的 symbol(method/class/欄位)
    原文,含檔名與行號。建議查詢詞同時含中文業務詞與英文 IT 詞。

    語意引擎:embedding 檢索,口語提問可命中英文 identifier 與中文註解;
    會先用該 AP 的 glossary 把業務用語展開成 IT 詞加權。
    include_call_chain=True 時每個命中另附一層呼叫鏈摘要(不需要可關,省輸出)。
    適合問「某公式怎麼算」「某規則的實作在哪」。
    """
    ctx, error = _resolve(app)
    if ctx is None:
        return error
    extra_terms, matched_entries = glossary.expand_query(query, ctx.glossary_path)
    if _engine(ctx) == "semantic":
        return _search_semantic(query, top_k, extra_terms, matched_entries,
                                ctx, include_call_chain)
    return _search_grep(query, top_k, extra_terms, matched_entries, ctx)


@mcp.tool()
@_logged
def get_structure(symbol: str, app: str = "") -> str:
    """查指定 AP 中 symbol 的結構關係:誰呼叫它(callers)、它呼叫誰(callees)、
    定義位置。輸入 method/class/欄位名稱(可含 class 前綴,如 HouseService.toDto)。

    適合問「這個公式被哪些地方使用」「改了會影響誰」;資料來自 codegraph 圖索引。
    """
    ctx, error = _resolve(app)
    if ctx is None:
        return error
    if not graph_db.available(ctx):
        return (f"app「{ctx.name}」找不到 {ctx.codegraph_db.name};"
                "請管理員在該 repo 跑 codegraph 建索引。")
    needle = symbol.strip().replace(".", "::").split("::")[-1]
    nodes = graph_db.find_nodes(needle, ctx, limit=8)
    # 有 class 前綴時縮小到 qualified_name 也吻合的
    if "." in symbol or "::" in symbol:
        qualifier = symbol.strip().replace(".", "::").lower()
        narrowed = [n for n in nodes if qualifier in n.qualified_name.lower()]
        nodes = narrowed or nodes
    if not nodes:
        return f"codegraph 裡找不到 symbol「{symbol}」。可先用 search_code 找正確名稱。"

    def dedupe(pairs):
        seen, out = set(), []
        for kind, s in pairs:
            key = (kind, s.qualified_name)
            if key not in seen:
                seen.add(key)
                out.append((kind, s))
        return out

    warning = graph_db.schema_warning(ctx)
    parts = [warning] if warning else []
    for node in nodes[:3]:
        lines = [
            f"### {node.qualified_name}({node.kind})",
            f"- 位置:{node.file_path}:{node.start_line}-{node.end_line}",
        ]
        callers = dedupe(graph_db.callers(node.node_id, ctx))
        callees = dedupe(graph_db.callees(node.node_id, ctx))
        if callers:
            lines.append("- 被誰用(callers):")
            lines += [f"  - {kind}:{s.qualified_name}({s.file_path}:{s.start_line})"
                      for kind, s in callers[:10]]
        else:
            lines.append("- 被誰用:codegraph 圖上沒有進邊(可能是入口點或動態呼叫)")
        if callees:
            lines.append("- 用了誰(callees):")
            lines += [f"  - {kind}:{s.qualified_name}({s.file_path}:{s.start_line})"
                      for kind, s in callees[:10]]
        parts.append("\n".join(lines))
    if len(nodes) > 3:
        parts.append(f"(另有 {len(nodes) - 3} 個同名候選,可加 class 前綴縮小)")
    return "\n\n".join(parts)


_MAX_SOURCE_CHARS = 100_000  # read_source 單檔回傳上限,防超大檔灌爆對話 context


@mcp.tool()
@_logged
def read_source(relative_path: str, app: str = "") -> str:
    """讀取指定 AP 原始碼檔案的完整內容。relative_path 以該 AP 的專案根為基準,
    例如 besthouse-backend/src/main/java/com/besthouse/service/HouseService.java"""
    ctx, error = _resolve(app)
    if ctx is None:
        return error
    root = ctx.repo_root.resolve()
    target = (root / relative_path).resolve()
    # 防目錄穿越:限制在該 AP 的專案根內
    if root not in target.parents and target != root:
        log.warning("read_source 路徑穿越被擋 app=%s path=%s", ctx.name, relative_path)
        return "路徑超出專案範圍,拒絕讀取。"
    if not target.is_file():
        return f"找不到檔案:{relative_path}(app={ctx.name})"
    text = target.read_text(encoding="utf-8", errors="replace")
    if len(text) > _MAX_SOURCE_CHARS:
        log.info("read_source 截斷 app=%s path=%s(%d 字元)",
                 ctx.name, relative_path, len(text))
        total_lines = text.count("\n") + 1
        return (text[:_MAX_SOURCE_CHARS]
                + f"\n\n(檔案過大,已截斷:共 {total_lines} 行/{len(text)} 字元,"
                f"僅回傳前 {_MAX_SOURCE_CHARS} 字元。建議改用 search_code 或 "
                "get_structure 鎖定目標 symbol。)")
    return text


@mcp.tool()
@_logged
def get_app_config(key_pattern: str = "", app: str = "") -> str:
    """查詢指定 AP 的 config(application.yml / application-local.yml)設定值。

    key_pattern 為 key 的子字串(不分大小寫),如 "datasource"、"gemini";
    空字串列出全部。敏感值(password / api-key 等)自動遮罩。
    適合問「系統連哪個 DB」「port 是多少」「有沒有設定某功能」。
    """
    ctx, error = _resolve(app)
    if ctx is None:
        return error
    return app_config.search_config(key_pattern, ctx)


@mcp.tool()
@_logged
def query_db_config(table: str, limit: int = 50, app: str = "",
                    filter_column: str = "", filter_op: str = "eq",
                    filter_value: str = "") -> str:
    """查詢指定 AP 的 DB 設定表「現值」(白名單表,見 list_apps 或錯誤訊息)。

    權重、規則門檻這類邏輯存在 DB,程式碼與 migration 都看不到現值——
    問「權重是多少」「篩選門檻是多少」必須用本工具,不要從程式碼推測。
    白名單以外的表(含個資敏感表)一律拒絕。

    受限過濾:查特定對象(如某間房)時用 filter_column + filter_value 縮小範圍,
    避免整表超過 limit 上限漏資料。filter_op:eq(精確)| contains(子字串)。
    欄位名必須存在於該表(錯誤訊息會列可用欄位);單一條件,不支援 AND/OR。
    回傳中若有多筆符合使用者所指的對象(如同名資料),先以識別欄位列選項
    向使用者確認是哪一筆,不要自行挑一筆作答;確認後可用主鍵 eq 精準取回。
    """
    ctx, error = _resolve(app)
    if ctx is None:
        return error
    return db_config.query_table(table, limit, ctx, filter_column=filter_column,
                                 filter_op=filter_op, filter_value=filter_value)


class _BearerTokenGuard:
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
        header = dict(scope.get("headers") or []).get(b"authorization", b"").decode()
        expected = f"Bearer {self._token}"
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


def _run_http() -> None:
    """集中部署:streamable HTTP(使用者端的 Connector URL 指到 /mcp)。"""
    import uvicorn
    app = mcp.streamable_http_app()
    token = os.environ.get("KB_AUTH_TOKEN", "")
    if token:
        app = _BearerTokenGuard(app, token)
    else:
        log.warning("KB_AUTH_TOKEN 未設定,HTTP 模式無認證——僅限信任內網使用。")
    log.info("啟動 transport=http %s:%d auth=%s",
             mcp.settings.host, mcp.settings.port, "bearer" if token else "無")
    uvicorn.run(app, host=mcp.settings.host, port=mcp.settings.port)


if __name__ == "__main__":
    if os.environ.get("KB_TRANSPORT", "stdio").lower() == "http":
        _run_http()
    else:
        log.info("啟動 transport=stdio")
        mcp.run()  # stdio:開發者本機模式
