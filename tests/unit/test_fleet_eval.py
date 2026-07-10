"""引擎決策實驗工具:fleet_eval 的度量/決策純函式 + eval_ablation 命中判定。"""

import pytest

import fleet_eval
import eval_ablation

_HEALTHY = {"median_tokens": 3, "opaque_frac": 0.1}


class TestPercentile:
    def test_interpolated_and_edges(self):
        assert fleet_eval._pct([10, 20, 30, 40], 0.5) == 25.0
        assert fleet_eval._pct([5], 0.95) == 5.0
        assert fleet_eval._pct([], 0.9) == 0.0


class TestOverlapJaccard:
    def test_overlap_needs_same_file_and_range_intersect(self):
        assert fleet_eval._overlap(("a.java", 10, 20), ("a.java", 15, 25))
        assert not fleet_eval._overlap(("a.java", 10, 20), ("a.java", 21, 30))
        assert not fleet_eval._overlap(("a.java", 10, 20), ("b.java", 10, 20))

    def test_jaccard(self):
        g = [("a", 1, 5), ("b", 1, 5)]
        s = [("a", 1, 5), ("c", 1, 5)]
        assert fleet_eval._jaccard(g, s) == pytest.approx(1 / 3)
        assert fleet_eval._jaccard([], []) == 1.0
        assert fleet_eval._jaccard([("a", 1, 5)], []) == 0.0


class TestDecide:
    def test_latency_driven_semantic(self):
        eng, _ = fleet_eval.decide(1500, 0.9, _HEALTHY, True)
        assert "semantic" in eng

    def test_grep_when_fast_and_equivalent(self):
        eng, _ = fleet_eval.decide(50, 0.8, _HEALTHY, True)
        assert eng == "grep"

    def test_tier3_when_divergent(self):
        eng, _ = fleet_eval.decide(50, 0.2, _HEALTHY, True)
        assert "Tier 3" in eng

    def test_tier3_when_naming_poor(self):
        poor = {"median_tokens": 1, "opaque_frac": 0.5}
        eng, _ = fleet_eval.decide(50, 0.9, poor, True)
        assert "Tier 3" in eng

    def test_grep_tentative_without_index(self):
        eng, _ = fleet_eval.decide(50, 0.0, _HEALTHY, False)
        assert eng.startswith("grep")


class TestAblationHit:
    def test_hits_on_region_or_name(self):
        assert eval_ablation.is_hit(["Foo"], ["... class foo ..."], [])
        assert eval_ablation.is_hit(["Bar"], [], ["pkg::bar::m"])
        assert not eval_ablation.is_hit(["Zed"], ["abc"], ["x::y"])

    def test_region_reads_line_range(self, make_app):
        app = make_app()
        (app.repo_root / "src" / "A.java").write_text("l1\nl2\nl3\nl4\n", encoding="utf-8")
        txt = eval_ablation.region(app, "src/A.java", 2, 3)
        assert "l2" in txt and "l3" in txt and "l1" not in txt


class TestWriteReport:
    def test_report_and_rollup(self, tmp_path):
        row = {
            "name": "x", "engine_cfg": "grep", "loc": 100, "symbols": 20,
            "grep": {"p50": 5, "p95": 9, "max": 12, "cold_ms": 3}, "sem": None,
            "jaccard": None, "top1_agree": None,
            "naming": {"median_tokens": 2, "opaque_frac": 0.2, "comment_frac": 0.3},
            "build_sec": 7, "build_note": "試算", "mem_mb": 1,
            "tentative": "grep(暫定)", "reason": "延遲 OK",
        }
        out = tmp_path / "rep.md"
        fleet_eval.write_report([row], out)
        text = out.read_text(encoding="utf-8")
        assert "全艦隊 rollup" in text and "| x |" in text


class TestEvalAppIntegration:
    def test_measures_and_decides(self, make_app, make_codegraph, semantic_root,
                                  monkeypatch):
        import json
        import numpy as np
        import semantic_common
        import semantic_search

        app = make_app(engine="auto")
        (app.repo_root / "src" / "A.java").write_text(
            "class A {\n  /** 計算運費 */\n  int computeFee() { return 1; }\n}\n",
            encoding="utf-8")
        app.glossary_path.write_text("- term: 運費\n  it_terms: [computeFee]\n",
                                     encoding="utf-8")
        make_codegraph(app, nodes=[
            ("n1", "method", "computeFee", "A::computeFee", "src/A.java", 3, 3, "")],
            files=[("src/A.java", "h1")])
        app.index_dir.mkdir(parents=True, exist_ok=True)
        paths = semantic_common.index_paths(app)
        paths.meta.write_text(json.dumps({
            "node_id": "n1", "kind": "method", "name": "computeFee",
            "qualified_name": "A::computeFee", "file_path": "src/A.java",
            "start_line": 3, "end_line": 3, "text": "compute fee"}), encoding="utf-8")
        np.save(paths.vectors, np.array([[1.0, 0.0]], dtype=np.float32))
        paths.state.write_text(json.dumps({"model": "fake", "built_at": "x"}),
                               encoding="utf-8")
        monkeypatch.setattr(semantic_common, "embed_texts",
                            lambda t, kind, model_name: np.array([[1.0, 0.0]]))
        monkeypatch.setattr(semantic_search, "embed_texts",
                            lambda t, kind, model_name: np.array([[1.0, 0.0]]))
        try:
            r = fleet_eval.eval_app(app, n_queries=4, build_missing=False,
                                    do_build=False, model_override="")
            assert r["symbols"] == 1
            assert r["semantic_available"] is True
            assert "p95" in r["grep"] and r["jaccard"] is not None
            assert r["tentative"]
        finally:
            semantic_search._caches.pop(app.name, None)
