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

    def test_oversized_type_decl_dropped(self):
        # 超大型別宣告(整個 class body)丟棄——不是有用的檢索單位,要的是裡面的方法
        big_class = "class Big {\n" + "int x;\n" * 4000 + "}\n"
        sigs = [b[2] for b in code_search.extract_blocks(big_class)]
        assert not any("class Big" in s for s in sigs)

    def test_oversized_method_kept(self):
        # 大方法照收(輸出時 truncate_body 截斷顯示),否則 legacy 大方法會搜不到
        big_method = "void big() {\n" + "x();\n" * 4000 + "}\n"
        sigs = [b[2] for b in code_search.extract_blocks(big_method)]
        assert any("big" in s for s in sigs)


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

    def test_large_method_is_searchable(self, make_app):
        # A1:大方法(body > MAX_BODY_CHARS)也要能被 grep 找到
        app = make_app()
        big = ("class C {\n  void computeShippingFee() {\n"
               + "    log();\n" * 3000 + "  }\n}\n")
        (app.repo_root / "src" / "C.java").write_text(big, encoding="utf-8")
        code_search._block_cache.clear()
        results = code_search.search("computeShippingFee", 3, set(), app)
        assert results and results[0][1] == "src/C.java"


class TestBlockCache:
    def test_caches_by_mtime_and_invalidates_on_edit(self, make_app):
        import os
        app = make_app()
        f = app.repo_root / "src" / "A.java"
        f.write_text("class A { void run() { } }", encoding="utf-8")
        code_search._block_cache.pop(str(f), None)

        b1 = code_search.blocks_for(f)
        assert code_search.blocks_for(f) is b1            # mtime 未變 → 命中快取(同物件)

        st = f.stat()
        f.write_text("class A { void renamed() { } }", encoding="utf-8")
        os.utime(f, ns=(st.st_mtime_ns + 1_000_000, st.st_mtime_ns + 1_000_000))
        b2 = code_search.blocks_for(f)
        assert b2 is not b1                                # mtime 前進 → 重新解析
        assert any("renamed" in blk[2] for blk in b2)

    def test_missing_file_returns_none(self, make_app):
        app = make_app()
        assert code_search.blocks_for(app.repo_root / "src" / "nope.java") is None

    def test_cache_capped_rebuilds_when_full(self, make_app, monkeypatch):
        # 刪除/更名的檔案項不會被主動清:累積到上限即整個重建,不無限成長
        app = make_app()
        monkeypatch.setattr(code_search, "_CACHE_MAX_FILES", 2)
        monkeypatch.setattr(code_search, "_block_cache", {})
        for i in range(3):
            f = app.repo_root / "src" / f"F{i}.java"
            f.write_text("class F { void m() { } }", encoding="utf-8")
            code_search.blocks_for(f)
        assert len(code_search._block_cache) <= 2
