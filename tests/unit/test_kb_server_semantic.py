"""kb_server 的 semantic 引擎路徑與 get_structure 圖查詢(假索引 + 假 codegraph)。"""

import json

import numpy as np
import pytest

import kb_config
import kb_server
import semantic_common
import semantic_search

_JAVA = "class S {\n    int calcFee() {\n        return 1;\n    }\n}\n"


@pytest.fixture
def graph_config(tmp_path, monkeypatch, make_codegraph, semantic_root, make_app):
    """tmp config:sem(semantic 引擎 + 假索引 + 假圖)+ demo(fixture,grep)。"""
    repo = tmp_path / "semrepo"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "A.java").write_text(_JAVA, encoding="utf-8")

    cfg = tmp_path / "kb.config.sem.yaml"
    cfg.write_text(
        "server_name: unit-kb\n"
        "apps:\n"
        "  - name: sem\n"
        "    description: 語意測試 app\n"
        f"    repo_root: {repo.as_posix()}\n"
        "    search_dirs: [src]\n"
        "    resources_dir: src\n"
        "    engine: semantic\n"
        "  - name: demo\n"
        "    description: 訂單系統(fixture)\n"
        "    repo_root: eval/fixture-app\n"
        "    search_dirs: [src]\n"
        "    resources_dir: src/main/resources\n"
        "    glossary: ../eval/fixture-app/glossary.yaml\n"
        "    engine: grep\n",
        encoding="utf-8")
    monkeypatch.setattr(kb_config, "CONFIG_PATH", cfg)
    kb_config._cache["stamp"] = None

    app, _ = kb_config.resolve_app("sem")
    # 假語意索引:單一 symbol 指向 src/A.java:2-4
    app.index_dir.mkdir(parents=True, exist_ok=True)
    paths = semantic_common.index_paths(app)
    meta = {"node_id": "n1", "kind": "method", "name": "calcFee",
            "qualified_name": "S::calcFee", "file_path": "src/A.java",
            "start_line": 2, "end_line": 4, "text": "calc fee"}
    paths.meta.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    np.save(paths.vectors, np.array([[1.0, 0.0]], dtype=np.float32))
    paths.state.write_text(json.dumps({"model": "fake", "built_at": "x"}),
                           encoding="utf-8")
    # 假 codegraph:calcFee 有一個 caller
    make_codegraph(app, nodes=[
        ("n1", "method", "calcFee", "S::calcFee", "src/A.java", 2, 4, ""),
        ("n2", "method", "toDto", "S::toDto", "src/A.java", 10, 12, ""),
    ], edges=[("n2", "n1", "calls")])

    qv = np.array([1.0, 0.0], dtype=np.float32)
    monkeypatch.setattr(semantic_search, "embed_texts",
                        lambda texts, kind, model_name: np.array([qv]))
    monkeypatch.setattr(semantic_common, "embed_texts",
                        lambda texts, kind, model_name: np.array([qv]))
    yield
    kb_config._cache["stamp"] = None
    semantic_search._caches.pop("sem", None)


class TestSemanticSearchPath:
    def test_hit_includes_source_and_call_chain(self, graph_config):
        out = kb_server.search_code("calc fee", app="sem")
        assert "engine=semantic" in out
        assert "src/A.java:2-4" in out and "calcFee" in out
        assert "```" in out                      # 附原始碼
        assert "呼叫鏈:" in out and "toDto" in out

    def test_call_chain_can_be_disabled(self, graph_config):
        out = kb_server.search_code("calc fee", app="sem", include_call_chain=False)
        assert "呼叫鏈:" not in out

    def test_missing_fastembed_falls_back_to_grep(self, graph_config, monkeypatch):
        # A2:engine=semantic + 索引在,但缺 fastembed → 優雅降級 grep(不報錯)
        def _raise(*a, **k):
            raise ImportError("No module named 'fastembed'")
        monkeypatch.setattr(semantic_search, "search", _raise)
        out = kb_server.search_code("calc fee", app="sem")
        assert "engine=grep" in out and "calcFee" in out

    def test_all_mode_semantic_app_participates(self, graph_config):
        out = kb_server.search_code("calc fee", app="all")
        assert "## sem" in out and "S::calcFee" in out
        assert "demo:略過" in out              # 無索引 AP 標註略過
        assert "```" not in out                 # discovery 不含內文

    def test_engine_locked_semantic_but_index_missing(self, graph_config, tmp_path,
                                                      monkeypatch):
        import shutil
        app, _ = kb_config.resolve_app("sem")
        shutil.rmtree(app.index_dir)
        semantic_search._caches.pop("sem", None)
        out = kb_server.search_code("calc fee", app="sem")
        assert "engine 改回 auto" in out or "index_all" in out


class TestGetStructure:
    def test_callers_and_callees_listed(self, graph_config):
        out = kb_server.get_structure("calcFee", app="sem")
        assert "S::calcFee" in out and "位置:src/A.java:2-4" in out
        assert "被誰用(callers):" in out and "toDto" in out

    def test_class_prefix_narrows(self, graph_config):
        out = kb_server.get_structure("S.calcFee", app="sem")
        assert "S::calcFee" in out

    def test_leaf_without_edges_notes_entry_point(self, graph_config):
        out = kb_server.get_structure("toDto", app="sem")
        assert "沒有進邊" in out

    def test_unknown_symbol_suggests_search(self, graph_config):
        out = kb_server.get_structure("noSuchThing", app="sem")
        assert "找不到 symbol" in out
