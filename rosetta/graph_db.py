"""codegraph.db 唯讀存取層(結構查詢 + 語意索引的 symbol 目錄)。

只讀 `.codegraph/codegraph.db`(SQLite),不寫入、不觸發重建索引。
版本鎖定:實測 schema version 6(codegraph CLI 1.2.0);版本不符時工具仍可用,但回傳警告字串。

注意:codegraph 在 Windows 上存的中文 docstring 已知是亂碼(編碼問題,不可逆),
因此 NL 訊號(註解)一律由 semantic_index 直接從原始碼以 UTF-8 抽取,
本模組只提供 symbol 名稱、位置與呼叫關係。
"""

import contextlib
from dataclasses import dataclass
import sqlite3

from kb_config import AppContext

TESTED_SCHEMA_VERSION = 6

# 進語意索引的 symbol 種類(import/file/namespace 等雜訊排除)
INDEXABLE_KINDS = (
    "method", "function", "class", "interface", "enum", "enum_member",
    "field", "property", "route", "constant",
)


@dataclass(frozen=True)
class Symbol:
    node_id: str
    kind: str
    name: str
    qualified_name: str
    file_path: str
    start_line: int
    end_line: int
    signature: str


def available(app: AppContext) -> bool:
    return app.codegraph_db.is_file()


def _connect(app: AppContext) -> sqlite3.Connection:
    # URI mode=ro:確保唯讀,絕不寫入 codegraph 的索引。
    # 注意:sqlite3 連線的 with 只管 transaction 不管 close,
    # 呼叫端一律用 contextlib.closing 包住。
    return sqlite3.connect(f"file:{app.codegraph_db.as_posix()}?mode=ro", uri=True)


def schema_warning(app: AppContext) -> str:
    """schema 版本不在測試範圍時回傳警告字串;正常時回空字串。"""
    with contextlib.closing(_connect(app)) as con:
        version = con.execute("SELECT MAX(version) FROM schema_versions").fetchone()[0]
    if version != TESTED_SCHEMA_VERSION:
        return (
            f"(警告:codegraph schema version={version},"
            f"本工具實測於 version={TESTED_SCHEMA_VERSION},結果可能不完整)"
        )
    return ""


def _to_symbol(row) -> Symbol:
    return Symbol(
        node_id=row[0], kind=row[1], name=row[2] or "",
        qualified_name=row[3] or "", file_path=row[4] or "",
        start_line=row[5] or 0, end_line=row[6] or 0, signature=row[7] or "",
    )


_SYMBOL_COLS = "id, kind, name, qualified_name, file_path, start_line, end_line, signature"


def iter_symbols(app: AppContext) -> list[Symbol]:
    """回傳所有可索引 symbol(語意索引的母體)。"""
    placeholders = ",".join("?" for _ in INDEXABLE_KINDS)
    with contextlib.closing(_connect(app)) as con:
        rows = con.execute(
            f"SELECT {_SYMBOL_COLS} FROM nodes WHERE kind IN ({placeholders})",
            INDEXABLE_KINDS,
        ).fetchall()
    return [_to_symbol(r) for r in rows]


def find_nodes(name: str, app: AppContext, limit: int = 10) -> list[Symbol]:
    """依 name 或 qualified_name(子字串、不分大小寫)找 symbol。"""
    needle = f"%{name.strip()}%"
    with contextlib.closing(_connect(app)) as con:
        rows = con.execute(
            f"SELECT {_SYMBOL_COLS} FROM nodes "
            "WHERE (name LIKE ? OR qualified_name LIKE ?) "
            f"AND kind IN ({','.join('?' for _ in INDEXABLE_KINDS)}) "
            "ORDER BY LENGTH(name) LIMIT ?",
            (needle, needle, *INDEXABLE_KINDS, limit),
        ).fetchall()
    return [_to_symbol(r) for r in rows]


def _related(node_id: str, app: AppContext, direction: str) -> list[tuple[str, Symbol]]:
    """direction='callers' 找誰指向我;'callees' 找我指向誰。含 calls/references/instantiates。"""
    if direction == "callers":
        join_on, where_on = "e.source = n.id", "e.target = ?"
    else:
        join_on, where_on = "e.target = n.id", "e.source = ?"
    with contextlib.closing(_connect(app)) as con:
        rows = con.execute(
            f"SELECT e.kind, {', '.join('n.' + c.strip() for c in _SYMBOL_COLS.split(','))} "
            f"FROM edges e JOIN nodes n ON {join_on} "
            f"WHERE {where_on} AND e.kind IN ('calls', 'references', 'instantiates')",
            (node_id,),
        ).fetchall()
    return [(r[0], _to_symbol(r[1:])) for r in rows]


def callers(node_id: str, app: AppContext) -> list[tuple[str, Symbol]]:
    return _related(node_id, app, "callers")


def callees(node_id: str, app: AppContext) -> list[tuple[str, Symbol]]:
    return _related(node_id, app, "callees")


def file_hashes(app: AppContext) -> dict[str, str]:
    """{repo 相對路徑: content_hash} —— 語意索引增量更新的依據。"""
    with contextlib.closing(_connect(app)) as con:
        rows = con.execute("SELECT path, content_hash FROM files").fetchall()
    return {path: h for path, h in rows}
