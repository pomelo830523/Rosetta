"""code_search:區塊切分、評分、行窗、截斷、走訪去重與端到端搜尋。"""

import code_search

_JAVA = """public class HouseService {
    /** 計算單價 */
    public double calcUnitPrice(double total, double area) {
        if (area <= 0) {
            return 0;
        }
        return total / area;
    }
}
"""


class TestExtractBlocks:
    def test_method_and_class_extracted(self):
        blocks = code_search.extract_blocks(_JAVA)
        signatures = [b[2] for b in blocks]
        assert any("calcUnitPrice" in s for s in signatures)
        assert any("class HouseService" in s for s in signatures)

    def test_control_keyword_block_excluded(self):
        signatures = [b[2] for b in code_search.extract_blocks(_JAVA)]
        assert not any(s.startswith("if") for s in signatures)

    def test_oversized_block_dropped(self):
        big = "void big() {\n" + "x;\n" * 4000 + "}\n"
        assert code_search.extract_blocks(big) == []


class TestScore:
    def test_english_term_in_signature_beats_body(self):
        in_sig = code_search.score("price", "double calcPrice()", "{}", set())
        in_body = code_search.score("price", "void x()", "{ price }", set())
        assert in_sig > in_body > 0

    def test_extra_terms_counted_lower_than_typed(self):
        typed = code_search.score("price", "calcPrice()", "{}", set())
        extra = code_search.score("零命中", "calcPrice()", "{}", {"price"})
        assert typed > extra > 0

    def test_chinese_bigram_matches_comment(self):
        assert code_search.score("單價怎麼算", "calc()", "{ // 單價計算 }", set()) > 0

    def test_no_match_zero(self):
        assert code_search.score("nothing", "a()", "{}", set()) == 0


class TestWindowsAndTruncate:
    def test_window_blocks_cover_whole_file(self):
        text = "\n".join(f"<div>{i}</div>" for i in range(1, 101))
        blocks = code_search.window_blocks(text)
        assert blocks[0][0] == 1 and blocks[-1][1] == 100

    def test_truncate_body_appends_marker(self):
        body = "\n".join(str(i) for i in range(200))
        out = code_search.truncate_body(body)
        assert "已截斷" in out
        assert len(out.splitlines()) == code_search.MAX_BODY_LINES + 1

    def test_truncate_body_short_untouched(self):
        assert code_search.truncate_body("a\nb") == "a\nb"


class TestIterAndSearch:
    def test_overlapping_search_dirs_deduped(self, make_app):
        app = make_app()
        sub = app.repo_root / "src" / "sub"
        sub.mkdir()
        (sub / "A.java").write_text("class A { void run() { } }", encoding="utf-8")
        app = make_app(search_dirs=(app.repo_root / "src", sub))
        files = list(code_search.iter_source_files(app))
        assert len(files) == 1

    def test_skip_dirs_excluded(self, make_app):
        app = make_app()
        skip = app.repo_root / "src" / "node_modules"
        skip.mkdir()
        (skip / "x.ts").write_text("export const a = 1;", encoding="utf-8")
        assert list(code_search.iter_source_files(app)) == []

    def test_search_returns_scored_hits(self, make_app):
        app = make_app()
        (app.repo_root / "src" / "A.java").write_text(_JAVA, encoding="utf-8")
        results = code_search.search("unit price 單價", 3, set(), app)
        assert results and results[0][1] == "src/A.java"

    def test_search_html_uses_windows(self, make_app):
        app = make_app()
        (app.repo_root / "src" / "t.html").write_text(
            "<div>訂單清單</div>", encoding="utf-8")
        results = code_search.search("訂單清單", 3, set(), app)
        assert results and results[0][1] == "src/t.html"
