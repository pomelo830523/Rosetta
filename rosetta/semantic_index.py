"""語意索引建置:symbol 級「NL 訊號」→ embedding → .semantic/<app>/ 單檔索引。

**餵 NL 訊號,不餵整段 code**:每個 symbol 的輸入 = identifier 拆詞
+ 註解(UTF-8 直讀原始碼,codegraph 的 docstring 在 Windows 是亂碼不可用)
+ annotation(@Table/@Column 含 DB 欄位名)+ glossary 反向注入。

增量:以 codegraph files 表的 content_hash 判斷;model 或 glossary 變更則全量重建。
用法:.venv\\Scripts\\python.exe -X utf8 rosetta\\semantic_index.py [--app NAME] [--rebuild]
(--app 省略時:設定檔只有一個 AP 就用它,否則列出可選的 AP)
"""

import hashlib
import json
import sys
import time

import numpy as np

import glossary
import graph_db
import kb_config
from kb_config import AppContext
from semantic_common import embed_texts, get_model_name, index_paths

_COMMENT_PREFIXES = ("//", "/*", "/**", "*", "*/", "#")
_MAX_COMMENT_LINES = 12


def _normalize(identifier: str) -> str:
    return "".join(c for c in identifier.lower() if c.isalnum())


def _extract_context_lines(lines: list[str], start_line: int) -> tuple[list[str], list[str]]:
    """從宣告行往上收 annotation 與註解(UTF-8 原文)。回傳 (annotations, comments)。"""
    annotations: list[str] = []
    comments: list[str] = []
    idx = start_line - 2  # 0-based:宣告行的上一行
    taken = 0
    while idx >= 0 and taken < _MAX_COMMENT_LINES:
        stripped = lines[idx].strip()
        if stripped.startswith("@"):
            annotations.append(stripped)
        elif any(stripped.startswith(p) for p in _COMMENT_PREFIXES):
            text = stripped.lstrip("/*#").rstrip("*/").strip()
            if text:
                comments.append(text)
        elif stripped == "":
            break
        else:
            break
        idx -= 1
        taken += 1
    comments.reverse()
    annotations.reverse()
    return annotations, comments


def glossary_injection(app: AppContext) -> dict[str, str]:
    """{normalized_it_segment: 業務詞文字}。symbol 名相符時把業務用語注入其 NL 訊號。"""
    injection: dict[str, str] = {}
    for entry in glossary.load_glossary(app.glossary_path):
        text_parts = [entry.term, *entry.all_aliases()]
        if entry.note:
            text_parts.append(entry.note)
        text = " ".join(text_parts)
        for it_term in entry.it_terms:
            segment = it_term.split(".")[-1]
            key = _normalize(segment)
            if key:
                injection[key] = (injection.get(key, "") + " " + text).strip()
    return injection


def build_nl_text(sym: graph_db.Symbol, lines: list[str], injection: dict[str, str]) -> str:
    """組一個 symbol 的 embedding 輸入文字(NL 訊號,非整段 code)。"""
    name_words = " ".join(sorted(glossary.split_identifier(sym.name)))
    class_part = sym.qualified_name.rsplit("::", 2)[-2] if "::" in sym.qualified_name else ""
    class_words = " ".join(sorted(glossary.split_identifier(class_part)))
    annotations, comments = _extract_context_lines(lines, sym.start_line)
    decl = lines[sym.start_line - 1].strip() if 0 < sym.start_line <= len(lines) else ""
    # 宣告行的行尾註解也是訊號(// 不含車位單價 這種)
    trailing = decl.split("//", 1)[1].strip() if "//" in decl else ""
    injected = injection.get(_normalize(sym.name), "")

    parts = [
        sym.name, name_words, sym.kind, class_part, class_words,
        " ".join(annotations), " ".join(comments), trailing, injected,
    ]
    return " | ".join(p for p in parts if p)


def _glossary_hash(app: AppContext) -> str:
    if not app.glossary_path.is_file():
        return "none"
    return hashlib.sha256(app.glossary_path.read_bytes()).hexdigest()[:16]


def _load_state(app: AppContext) -> dict:
    state_path = index_paths(app).state
    if state_path.is_file():
        try:
            return json.loads(state_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def build(app: AppContext, rebuild: bool = False) -> str:
    """建/更新該 app 的語意索引;回傳人類可讀的結果摘要。"""
    if not graph_db.available(app):
        return (f"[{app.name}] 找不到 {app.codegraph_db},無法建語意索引"
                "(先在該 repo 跑 codegraph 建圖)。")

    paths = index_paths(app)
    model_name = get_model_name(app)
    # codegraph 掃整個 repo;語意索引只收 search_dirs 內的 symbol,避免跨界污染
    prefixes = tuple(
        d.relative_to(app.repo_root).as_posix() + "/" for d in app.search_dirs)
    file_hashes = {p: h for p, h in graph_db.file_hashes(app).items()
                   if p.startswith(prefixes)}
    glossary_sha = _glossary_hash(app)
    state = _load_state(app)

    full = (
        rebuild
        or state.get("model") != model_name
        or state.get("glossary_sha") != glossary_sha
        or not (paths.meta.is_file() and paths.vectors.is_file())
    )

    old_meta: list[dict] = []
    old_vectors = None
    changed_files: set[str] = set()
    if not full:
        old_meta = [json.loads(l) for l in paths.meta.read_text(encoding="utf-8").splitlines() if l]
        old_vectors = np.load(paths.vectors)
        old_files = state.get("files", {})
        changed_files = {p for p, h in file_hashes.items() if old_files.get(p) != h}
        changed_files |= {p for p in old_files if p not in file_hashes}
        if not changed_files:
            return f"[{app.name}] 索引已是最新({len(old_meta)} symbols,model={model_name})。"

    symbols = [s for s in graph_db.iter_symbols(app) if s.file_path.startswith(prefixes)]
    injection = glossary_injection(app)
    file_cache: dict[str, list[str]] = {}

    def lines_of(rel_path: str) -> list[str]:
        if rel_path not in file_cache:
            try:
                file_cache[rel_path] = (app.repo_root / rel_path).read_text(
                    encoding="utf-8", errors="replace").splitlines()
            except OSError:
                file_cache[rel_path] = []
        return file_cache[rel_path]

    keep_meta: list[dict] = []
    keep_vectors: list[np.ndarray] = []
    if not full and old_vectors is not None:
        for i, m in enumerate(old_meta):
            if m["file_path"] not in changed_files:
                keep_meta.append(m)
                keep_vectors.append(old_vectors[i])

    todo = [s for s in symbols
            if full or s.file_path in changed_files]
    new_meta: list[dict] = []
    texts: list[str] = []
    for sym in todo:
        text = build_nl_text(sym, lines_of(sym.file_path), injection)
        new_meta.append({
            "node_id": sym.node_id, "kind": sym.kind, "name": sym.name,
            "qualified_name": sym.qualified_name, "file_path": sym.file_path,
            "start_line": sym.start_line, "end_line": sym.end_line, "text": text,
        })
        texts.append(text)

    started = time.time()
    new_vectors = (embed_texts(texts, kind="passage", model_name=model_name)
                   if texts else np.zeros((0, 1), np.float32))
    elapsed = time.time() - started

    all_meta = keep_meta + new_meta
    if keep_vectors:
        all_vectors = np.vstack([np.array(keep_vectors), new_vectors]) if len(new_vectors) else np.array(keep_vectors)
    else:
        all_vectors = new_vectors

    app.index_dir.mkdir(parents=True, exist_ok=True)
    paths.meta.write_text(
        "\n".join(json.dumps(m, ensure_ascii=False) for m in all_meta), encoding="utf-8")
    np.save(paths.vectors, all_vectors.astype(np.float32))
    paths.state.write_text(json.dumps({
        "model": model_name,
        "dim": int(all_vectors.shape[1]) if len(all_vectors) else 0,
        "glossary_sha": glossary_sha,
        "files": file_hashes,
        "built_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "codegraph_schema": graph_db.TESTED_SCHEMA_VERSION,
    }, ensure_ascii=False, indent=1), encoding="utf-8")

    mode = "全量重建" if full else f"增量({len(changed_files)} 檔變更)"
    return (f"[{app.name}] {mode}:{len(all_meta)} symbols(本次嵌入 {len(new_meta)},"
            f"{elapsed:.1f}s,model={model_name})")


def _app_from_argv() -> AppContext:
    name = ""
    if "--app" in sys.argv:
        idx = sys.argv.index("--app")
        if idx + 1 >= len(sys.argv):
            raise SystemExit("--app 後面要接 app 名稱。")
        name = sys.argv[idx + 1]
    app, error = kb_config.resolve_app(name)
    if app is None:
        raise SystemExit(error)
    return app


if __name__ == "__main__":
    print(build(_app_from_argv(), rebuild="--rebuild" in sys.argv))
