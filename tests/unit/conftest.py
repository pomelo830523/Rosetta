"""unit tests 共用 fixtures。

原則:不碰真實 AP repo、不碰 .semantic/、不連 DB、不載 embedding model——
一律用 tmp_path 假資產與 monkeypatch;唯一的真實檔案依賴是 eval/fixture-app
(專案自帶的隔離測試 fixture)。
"""

from pathlib import Path
import sqlite3
import sys

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "rosetta"))
sys.path.insert(0, str(ROOT / "scripts"))

import kb_config  # noqa: E402(需先設 sys.path)


@pytest.fixture
def make_app(tmp_path):
    """回傳工廠:建立指向 tmp 目錄的 AppContext(目錄實際建立)。"""
    def _make(name="testapp", **overrides):
        repo = tmp_path / name
        (repo / "src").mkdir(parents=True, exist_ok=True)
        (repo / "res").mkdir(exist_ok=True)
        fields = dict(
            name=name, description="測試 app", repo_root=repo,
            search_dirs=(repo / "src",), resources_dir=repo / "res",
            entity_dir=None, glossary_path=tmp_path / f"{name}-glossary.yaml",
            db=kb_config.DbSettings(
                driver="mariadb", table_whitelist=("CFG",),
                sensitive_tables=(("MEMBER", "含個資,排除。"),)),
            engine="auto", embed_model="",
        )
        fields.update(overrides)
        return kb_config.AppContext(**fields)
    return _make


@pytest.fixture
def semantic_root(tmp_path, monkeypatch):
    """把語意索引根目錄導到 tmp,避免測試寫進真實 .semantic/。"""
    root = tmp_path / ".semantic"
    monkeypatch.setattr(kb_config, "SEMANTIC_ROOT", root)
    return root


_CODEGRAPH_SCHEMA = """
CREATE TABLE schema_versions(version INTEGER);
CREATE TABLE nodes(id TEXT, kind TEXT, name TEXT, qualified_name TEXT,
                   file_path TEXT, start_line INTEGER, end_line INTEGER, signature TEXT);
CREATE TABLE edges(source TEXT, target TEXT, kind TEXT);
CREATE TABLE files(path TEXT, content_hash TEXT);
"""


@pytest.fixture
def make_codegraph():
    """回傳工廠:替 AppContext 建一顆假的 codegraph.db。"""
    def _make(app, nodes=(), edges=(), files=(), schema_version=6):
        db_path = app.codegraph_db
        db_path.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(db_path)
        con.executescript(_CODEGRAPH_SCHEMA)
        con.execute("INSERT INTO schema_versions VALUES (?)", (schema_version,))
        con.executemany("INSERT INTO nodes VALUES (?,?,?,?,?,?,?,?)", nodes)
        con.executemany("INSERT INTO edges VALUES (?,?,?)", edges)
        con.executemany("INSERT INTO files VALUES (?,?)", files)
        con.commit()
        con.close()
        return db_path
    return _make


@pytest.fixture
def demo_config(tmp_path, monkeypatch):
    """以 eval/fixture-app 為唯一 AP 的暫時 kb.config(engine=grep,無外部依賴)。"""
    cfg = tmp_path / "kb.config.unit.yaml"
    cfg.write_text(
        "server_name: unit-kb\n"
        "apps:\n"
        "  - name: demo\n"
        "    description: 訂單系統(fixture)——運費與會員折扣\n"
        "    repo_root: eval/fixture-app\n"
        "    search_dirs: [src]\n"
        "    resources_dir: src/main/resources\n"
        "    glossary: ../eval/fixture-app/glossary.yaml\n"
        "    engine: grep\n"
        "    db:\n"
        "      driver: mariadb\n"
        "      table_whitelist: [SHIPPING_RULE]\n"
        "      sensitive_tables:\n"
        "        MEMBER: 含個資,排除。\n",
        encoding="utf-8")
    monkeypatch.setattr(kb_config, "CONFIG_PATH", cfg)
    kb_config._cache["stamp"] = None
    yield cfg
    kb_config._cache["stamp"] = None
