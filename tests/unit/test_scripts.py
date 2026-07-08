"""scripts:script_args、log_report 解析/報表、glossary_lint、kb_log。"""

import logging
import logging.handlers
import sys

import pytest

import kb_log
import script_args


class TestScriptArgs:
    def test_flag_absent_returns_default(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["prog"])
        assert script_args.flag_value("--app", "dft") == "dft"

    def test_flag_with_value(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["prog", "--app", "demo"])
        assert script_args.flag_value("--app") == "demo"

    def test_flag_missing_value_exits_with_hint(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["prog", "--app"])
        with pytest.raises(SystemExit, match="--app 後面要接值"):
            script_args.flag_value("--app")


class TestKbLog:
    def test_brief_truncates(self):
        assert kb_log.brief("a" * 100) == "a" * 60 + "…"
        assert kb_log.brief("多行\n變一行") == "多行 變一行"

    def test_setup_uses_rotating_file_handler(self, tmp_path, monkeypatch):
        logger = logging.getLogger("rosetta")
        saved = logger.handlers[:]
        logger.handlers.clear()
        try:
            monkeypatch.setenv("KB_LOG_FILE", str(tmp_path / "kb.log"))
            out = kb_log.setup()
            rotating = [h for h in out.handlers
                        if isinstance(h, logging.handlers.RotatingFileHandler)]
            assert rotating and rotating[0].maxBytes == 5_000_000
            for h in out.handlers:
                h.close()
        finally:
            logger.handlers.clear()
            logger.handlers.extend(saved)


_SAMPLE_LOG = """\
2026-07-06 10:00:00 INFO [rosetta] tool=search_code(app=demo)→ 500 字元,120ms
2026-07-06 10:00:01 INFO [rosetta] tool=search_code(app=demo)→ 300 字元,80ms
2026-07-06 10:00:02 INFO [rosetta] tool=lookup_term(app=demo)→ 100 字元,5ms
2026-07-06 10:00:03 INFO [rosetta] S1 歧義訊號 app=demo query=規則 concepts=甲、乙
2026-07-06 10:00:04 INFO [rosetta] S2 結果分散 classes=A、B、C(top1-top3=0.010)
2026-07-06 10:00:05 INFO [rosetta] S3 檢索空手 app=demo engine=grep query=神秘詞
2026-07-06 10:00:06 WARNING [rosetta] query_db_config 白名單外被拒 app=demo table=X
2026-07-06 10:00:07 ERROR [rosetta] DB 連線或查詢失敗 app=demo
2026-07-05 09:00:00 INFO [rosetta] tool=list_apps()→ 50 字元,1ms
"""


class TestLogReport:
    def _stats(self, tmp_path, since=""):
        import log_report
        path = tmp_path / "kb.log"
        path.write_text(_SAMPLE_LOG, encoding="utf-8")
        return log_report.parse(path, since), log_report

    def test_parse_counts_tools_and_signals(self, tmp_path):
        stats, _ = self._stats(tmp_path)
        assert stats["calls"]["search_code"] == 2
        assert stats["ms"]["search_code"] == [120, 80]
        assert len(stats["s1"]) == 1 and stats["s2"] == 1 and len(stats["s3"]) == 1
        assert stats["warnings"]["query_db_config 白名單外被拒"] == 1
        assert len(stats["errors"]) == 1

    def test_since_filters_old_lines(self, tmp_path):
        stats, _ = self._stats(tmp_path, since="2026-07-06")
        assert stats["calls"].get("list_apps", 0) == 0

    def test_report_sections(self, tmp_path):
        stats, log_report = self._stats(tmp_path)
        out = log_report.report(stats)
        assert "## tool 用量與耗時" in out
        assert "S3 空手 query" in out and "神秘詞" in out
        assert "拒絕/警告事件" in out and "## 錯誤" in out
        assert "觸發率 50%" in out  # S2 1 次 / search_code 2 次


class TestGlossaryLint:
    def test_no_entries_skipped(self, make_app):
        import glossary_lint
        dead, lines = glossary_lint.lint_app(make_app())
        assert dead == 0 and "無條目" in lines[0]

    def test_no_codegraph_skipped(self, make_app):
        import glossary_lint
        app = make_app()
        app.glossary_path.write_text(
            "- term: 甲\n  it_terms: [A]\n", encoding="utf-8")
        dead, lines = glossary_lint.lint_app(app)
        assert dead == 0 and "缺 codegraph" in lines[0]

    def test_empty_it_terms_reported_dead(self, make_app, make_codegraph):
        import glossary_lint
        app = make_app()
        make_codegraph(app, nodes=[("n1", "method", "calcFee",
                                    "d::S::calcFee", "src/A.java", 1, 2, "")])
        app.glossary_path.write_text(
            "- term: 寫錯欄位\n  maps_to: [X]\n", encoding="utf-8")
        dead, lines = glossary_lint.lint_app(app)
        assert dead == 1
        assert any("未填 it_terms" in l for l in lines)

    def test_alive_via_codegraph_and_dead_detected(self, make_app, make_codegraph):
        import glossary_lint
        app = make_app()
        make_codegraph(app, nodes=[("n1", "method", "calcFee",
                                    "d::S::calcFee", "src/A.java", 1, 2, "")])
        app.glossary_path.write_text(
            "- term: 運費\n  it_terms: [OrderService.calcFee]\n"
            "- term: 亡者\n  it_terms: [GhostService.gone]\n",
            encoding="utf-8")
        dead, lines = glossary_lint.lint_app(app)
        assert dead == 1
        assert any("DEAD「亡者」" in l for l in lines)
        assert any("共 2 條:DEAD 1" in l for l in lines)

    def test_whitelist_and_config_keys_resolve(self, make_app, make_codegraph):
        import glossary_lint
        app = make_app()
        make_codegraph(app, nodes=[("n1", "method", "m", "d::S::m",
                                    "src/A.java", 1, 2, "")])
        (app.resources_dir / "application.yml").write_text(
            "gemini:\n  api-key: x\n", encoding="utf-8")
        app.glossary_path.write_text(
            "- term: 白名單表\n  it_terms: [CFG]\n"
            "- term: 設定鍵\n  it_terms: [gemini.api-key]\n",
            encoding="utf-8")
        dead, _ = glossary_lint.lint_app(app)
        assert dead == 0
