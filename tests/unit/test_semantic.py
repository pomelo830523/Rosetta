"""semantic_search / semantic_index / semantic_common:不載模型,embed 一律 monkeypatch。"""

import json

import numpy as np
import pytest

import semantic_common
import semantic_index
import semantic_search


def _unit(vec):
    arr = np.array(vec, dtype=np.float32)
    return arr / np.linalg.norm(arr)


def _write_index(app, meta, vectors, model="fake-model"):
    app.index_dir.mkdir(parents=True, exist_ok=True)
    paths = semantic_common.index_paths(app)
    paths.meta.write_text(
        "\n".join(json.dumps(m, ensure_ascii=False) for m in meta), encoding="utf-8")
    np.save(paths.vectors, np.array(vectors, dtype=np.float32))
    paths.state.write_text(json.dumps(
        {"model": model, "built_at": "2026-07-08 00:00:00"}), encoding="utf-8")
    return paths


def _meta(name, qualified_name, file_path="src/A.java"):
    return {"node_id": name, "kind": "method", "name": name,
            "qualified_name": qualified_name, "file_path": file_path,
            "start_line": 1, "end_line": 2, "text": name}


class TestQueryWordsAndBoost:
    def test_query_words_min_length_and_split(self):
        assert semantic_search.query_words("calc 單價 ab price9") == {"calc", "price9"}

    def test_literal_boost_counts_and_caps(self):
        name = "calculatepriceperping"
        typed = {"calculate", "price", "per", "ping", "extra1", "extra2"}
        # 4 詞命中 × 0.08 = 0.32 → 封頂 0.24
        assert semantic_search.literal_boost(name, typed, set()) == pytest.approx(0.24)
        assert semantic_search.literal_boost(name, set(), {"price"}) == pytest.approx(0.04)

    def test_hybrid_rank_literal_boost_wins(self):
        scores = np.array([0.50, 0.52], dtype=np.float32)  # 純語意時 1 較高
        names = ["calcpriceperping", "totalprice"]
        ranked = semantic_search.hybrid_rank(
            scores, lambda i: names[i], 2, {"calc", "price", "per", "ping"}, set())
        assert [i for _, i in ranked] == [0, 1]  # boost 後 0 反超


class TestSearch:
    def test_search_hits_and_min_score(self, make_app, semantic_root, monkeypatch):
        app = make_app(name="semapp1")
        meta = [_meta("calcFee", "d::S::calcFee"), _meta("other", "d::S::other")]
        _write_index(app, meta, [_unit([1, 0]), _unit([0, 1])])
        monkeypatch.setattr(semantic_search, "embed_texts",
                            lambda texts, kind, model_name: np.array([_unit([1, 0.1])]))
        hits = semantic_search.search("怎麼算運費 calcFee", 3, set(), app)
        assert hits and hits[0].qualified_name == "d::S::calcFee"
        assert all(h.score >= semantic_search._MIN_SCORE for h in hits)

    def test_precomputed_query_vec_skips_embedding(self, make_app, semantic_root, monkeypatch):
        app = make_app(name="semapp2")
        _write_index(app, [_meta("a", "d::S::a")], [_unit([1, 0])])
        monkeypatch.setattr(semantic_search, "embed_texts",
                            lambda *a, **k: pytest.fail("不應呼叫 embed"))
        hits = semantic_search.search("q", 3, set(), app, query_vec=_unit([1, 0]))
        assert hits[0].name == "a"

    def test_meta_vector_mismatch_raises(self, make_app, semantic_root):
        app = make_app(name="semapp3")
        _write_index(app, [_meta("a", "x::a"), _meta("b", "x::b")], [_unit([1, 0])])
        with pytest.raises(ValueError, match="不一致"):
            semantic_search.search("q", 3, set(), app, query_vec=_unit([1, 0]))

    def test_index_info_and_model(self, make_app, semantic_root):
        app = make_app(name="semapp4")
        _write_index(app, [_meta("a", "x::a")], [_unit([1, 0])], model="m9")
        assert semantic_search.index_model(app) == "m9"
        assert "m9" in semantic_search.index_info(app)

    def test_available(self, make_app, semantic_root):
        app = make_app(name="semapp5")
        assert not semantic_search.available(app)
        _write_index(app, [_meta("a", "x::a")], [_unit([1, 0])])
        assert semantic_search.available(app)


class TestSemanticCommon:
    def test_e5_prefix_applied(self):
        out = semantic_common._apply_prefix(["t"], "query", "intfloat/multilingual-e5-large")
        assert out == ["query: t"]
        out = semantic_common._apply_prefix(["t"], "passage", "e5-small")
        assert out == ["passage: t"]

    def test_non_e5_untouched(self):
        assert semantic_common._apply_prefix(["t"], "query", "minilm") == ["t"]

    def test_model_priority_env_first(self, make_app, monkeypatch):
        app = make_app(embed_model="from-config")
        monkeypatch.setenv("KB_EMBED_MODEL", "from-env")
        assert semantic_common.get_model_name(app) == "from-env"
        monkeypatch.delenv("KB_EMBED_MODEL")
        assert semantic_common.get_model_name(app) == "from-config"


_JAVA = """public class OrderService {
    // 計算運費:滿千免運
    @Deprecated
    public int calcFee(int total) { // 行尾註解
        return 0;
    }
}
"""


class TestIndexHelpers:
    def test_search_prefixes(self, make_app):
        app = make_app()
        assert semantic_index.search_prefixes(app) == ("src/",)

    def test_extract_context_lines(self):
        lines = _JAVA.splitlines()
        annotations, comments = semantic_index._extract_context_lines(lines, 4)
        assert annotations == ["@Deprecated"]
        assert comments == ["計算運費:滿千免運"]

    def test_build_nl_text_includes_signals(self, make_app):
        app = make_app()
        sym = __import__("graph_db").Symbol(
            node_id="n1", kind="method", name="calcFee",
            qualified_name="demo::OrderService::calcFee",
            file_path="src/A.java", start_line=4, end_line=6, signature="")
        text = semantic_index.build_nl_text(sym, _JAVA.splitlines(), {"calcfee": "運費"})
        assert "calc" in text and "fee" in text          # identifier 拆詞
        assert "OrderService" in text                     # class 部分
        assert "計算運費" in text and "行尾註解" in text  # 註解 + 行尾
        assert "運費" in text                             # glossary 注入

    def test_glossary_injection(self, make_app, tmp_path):
        app = make_app(glossary_path=tmp_path / "g.yaml")
        app.glossary_path.write_text(
            "- term: 運費\n  aliases: [運送費用]\n"
            "  it_terms: [OrderService.calcFee]\n  note: 滿千免運\n",
            encoding="utf-8")
        injection = semantic_index.glossary_injection(app)
        assert "運費" in injection["calcfee"] and "滿千免運" in injection["calcfee"]


class TestBuild:
    def _setup(self, make_app, make_codegraph, semantic_root, monkeypatch, name="idxapp"):
        app = make_app(name=name)
        (app.repo_root / "src" / "A.java").write_text(_JAVA, encoding="utf-8")
        make_codegraph(
            app,
            nodes=[("n1", "method", "calcFee", "demo::OrderService::calcFee",
                    "src/A.java", 4, 6, ""),
                   ("n9", "method", "outside", "x::outside",
                    "other/B.java", 1, 2, "")],  # search_dirs 外,應排除
            files=[("src/A.java", "h1"), ("other/B.java", "h9")])

        def fake_embed(texts, kind, model_name):
            return np.ones((len(texts), 4), dtype=np.float32) / 2.0

        monkeypatch.setattr(semantic_index, "embed_texts", fake_embed)
        return app

    def test_no_codegraph_message(self, make_app):
        out = semantic_index.build(make_app())
        assert "找不到" in out

    def test_empty_search_dirs_skipped(self, make_app, make_codegraph):
        app = make_app(search_dirs=())
        make_codegraph(app)
        assert "未設定 search_dirs" in semantic_index.build(app)

    def test_full_build_then_up_to_date(self, make_app, make_codegraph,
                                        semantic_root, monkeypatch):
        app = self._setup(make_app, make_codegraph, semantic_root, monkeypatch)
        out = semantic_index.build(app)
        assert "全量重建" in out and "1 symbols" in out  # search_dirs 外的排除
        paths = semantic_common.index_paths(app)
        assert paths.all_exist()
        state = json.loads(paths.state.read_text(encoding="utf-8"))
        assert state["files"] == {"src/A.java": "h1"}
        out2 = semantic_index.build(app)
        assert "已是最新" in out2

    def test_rebuild_flag_forces_full(self, make_app, make_codegraph,
                                      semantic_root, monkeypatch):
        app = self._setup(make_app, make_codegraph, semantic_root, monkeypatch,
                          name="idxapp2")
        semantic_index.build(app)
        assert "全量重建" in semantic_index.build(app, rebuild=True)
