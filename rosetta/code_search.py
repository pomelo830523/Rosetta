"""原始碼即時搜尋:走訪檔案、大括號切區塊、中英雙語評分。

不建索引、不快取,每次查詢讀當下磁碟上的程式碼,因此永不 drift。
掃描範圍(repo 根與目錄)來自 AppContext(kb.config.yaml,per-app)。
"""

import re

from kb_config import AppContext

SOURCE_GLOBS = ("*.java", "*.ts", "*.html")
SKIP_DIRS = {"node_modules", "target", "dist", ".git", ".venv", ".angular"}
CONTROL_KEYWORDS = (
    "if", "for", "while", "switch", "catch", "else",
    "try", "do", "return", "new", "synchronized",
)
MAX_BODY_CHARS = 6000   # 只用來丟棄「超大型別宣告」(整個 class body);大方法照收
MAX_BODY_LINES = 90     # 單一區塊回傳行數上限

_TYPE_DECL_RE = re.compile(r"\b(class|enum|interface|record)\s+\w+")


def iter_source_files(app: AppContext):
    """走訪 app 的所有原始碼檔案,跳過 node_modules / target / dist 等。

    search_dirs 巢狀/重疊時同一檔案只回一次(避免重複掃描與重複命中)。
    """
    seen: set = set()
    for base in app.search_dirs:
        if not base.exists():
            continue
        for pattern in SOURCE_GLOBS:
            for path in base.rglob(pattern):
                if path in seen or any(part in SKIP_DIRS for part in path.parts):
                    continue
                seen.add(path)
                yield path


def extract_blocks(text: str) -> list[tuple[int, int, str, str]]:
    """用大括號配對切出 method/function/型別宣告區塊。

    回傳 [(start_line, end_line, signature, body), ...]。
    """
    blocks = []
    stack = []          # (start_line, signature, open_index)
    sig_start = 0       # 目前 signature 文字的起點(上一個 ; { } 之後)
    line = 1
    for idx, ch in enumerate(text):
        if ch == "\n":
            line += 1
        elif ch == "{":
            raw = text[sig_start:idx].strip().splitlines()
            signature = raw[-1].strip() if raw else ""
            stack.append((line, signature, idx))
            sig_start = idx + 1
        elif ch == "}":
            if stack:
                start_line, signature, open_idx = stack.pop()
                body = text[open_idx:idx + 1]
                head = signature.split("(")[0].strip()
                name = head.split()[-1] if head.split() else ""
                is_control = any(signature.startswith(k) for k in CONTROL_KEYWORDS)
                is_method = "(" in signature and bool(name) and not is_control
                is_type_decl = _TYPE_DECL_RE.search(signature) is not None
                # 大方法照收(輸出時 truncate_body 截斷顯示);只有超大「型別宣告」
                # (整個 class body)才丟棄——那不是有用的檢索單位,要的是它裡面的方法
                if is_method or (is_type_decl and len(body) <= MAX_BODY_CHARS):
                    blocks.append((start_line, line, signature, body))
            sig_start = idx + 1
        elif ch == ";":
            sig_start = idx + 1
    return blocks


def score(query: str, signature: str, body: str, extra_terms: set[str]) -> int:
    """中文 bigram 比對註解 + 英文 identifier 比對;glossary 展開詞一併計分。

    extra_terms 是 glossary 由業務用語展開出的英文詞(權重略低於使用者親打的詞)。
    """
    q = query.lower()
    sig_l = signature.lower()
    body_l = body.lower()
    total = 0

    # 使用者親打的英文詞:命中 signature 加重
    for term in set(re.findall(r"[a-z]{3,}", q)):
        if term in sig_l:
            total += 5
        elif term in body_l:
            total += 2

    # glossary 展開詞:讓純中文查詢也能比對英文 identifier
    for term in extra_terms:
        if term in sig_l:
            total += 3
        elif term in body_l:
            total += 1

    # 中文:query 取 bigram,比對程式碼(含中文註解)
    haystack = sig_l + "\n" + body_l
    bigrams = {q[i:i + 2] for i in range(len(q) - 1)}
    chinese_bigrams = {bg for bg in bigrams if any("一" <= c <= "鿿" for c in bg)}
    for bg in chinese_bigrams:
        if bg in sig_l:
            total += 3
        elif bg in haystack:
            total += 1
    return total


WINDOW_LINES = 40   # 無 {} 區塊結構的檔案(html template)以固定行窗切塊
WINDOW_STEP = 30    # 相鄰視窗重疊 10 行,避免命中內容剛好被切在邊界


def window_blocks(text: str) -> list[tuple[int, int, str, str]]:
    """html 等無大括號結構的檔案:固定行窗切塊;首個非空行充當 signature。"""
    lines = text.splitlines()
    blocks = []
    for start in range(0, len(lines), WINDOW_STEP):
        chunk = lines[start:start + WINDOW_LINES]
        signature = next((l.strip() for l in chunk if l.strip()), "")
        if signature:
            blocks.append((start + 1, min(start + WINDOW_LINES, len(lines)),
                           signature, "\n".join(chunk)))
        if start + WINDOW_LINES >= len(lines):
            break
    return blocks


def truncate_body(body: str) -> str:
    lines = body.splitlines()
    if len(lines) <= MAX_BODY_LINES:
        return body
    kept = lines[:MAX_BODY_LINES]
    kept.append(f"    // ...(區塊過長,已截斷,共 {len(lines)} 行;可用 read_source 取完整檔案)")
    return "\n".join(kept)


# 檔案切塊快取:str(path) → (mtime_ns, blocks)。grep 是預設引擎、每次查詢都會走訪
# 全部檔案,快取避免「檔案沒變卻每次重讀重解析」;以 mtime 失效,故仍永不 drift。
_block_cache: dict[str, tuple[int, list[tuple[int, int, str, str]]]] = {}
_CACHE_MAX_FILES = 20000  # 防呆上限:刪除/更名的檔案項不會被主動清,累積到上限即整個重建


def blocks_for(path) -> list[tuple[int, int, str, str]] | None:
    """讀檔 + 切塊,以 mtime 快取;讀不到回 None。檔案一改動 mtime 就變、快取自動失效。"""
    key = str(path)
    try:
        mtime = path.stat().st_mtime_ns
    except OSError:
        _block_cache.pop(key, None)
        return None
    cached = _block_cache.get(key)
    if cached and cached[0] == mtime:
        return cached[1]
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return None
    blocks = (window_blocks(text) if path.suffix.lower() == ".html"
              else extract_blocks(text))
    if key not in _block_cache and len(_block_cache) >= _CACHE_MAX_FILES:
        _block_cache.clear()  # 代價 = 重掃一輪,換取殘留項不無限累積
    _block_cache[key] = (mtime, blocks)
    return blocks


def search(query: str, top_k: int, extra_terms: set[str],
           app: AppContext) -> list[tuple[int, str, int, int, str]]:
    """回傳 [(score, relative_path, start_line, end_line, body), ...] 取前 top_k。"""
    candidates = []
    for path in iter_source_files(app):
        blocks = blocks_for(path)
        if blocks is None:
            continue
        rel = path.relative_to(app.repo_root).as_posix()
        for start, end, signature, body in blocks:
            s = score(query, signature, body, extra_terms)
            if s > 0:
                candidates.append((s, rel, start, end, body))
    candidates.sort(key=lambda c: c[0], reverse=True)
    return candidates[:top_k]
