"""glossary:載入(平面/分語言/壞檔)、比對、展開、排版。"""

import glossary


def _write(tmp_path, content):
    path = tmp_path / "glossary.yaml"
    path.write_text(content, encoding="utf-8")
    return path


class TestLoadGlossary:
    def test_flat_aliases_treated_as_zh(self, tmp_path):
        path = _write(tmp_path, "- term: 權重\n  aliases: [比重]\n  it_terms: [WEIGHT]\n")
        entries = glossary.load_glossary(path)
        assert entries[0].aliases == (("zh", "比重"),)
        assert entries[0].it_terms == ("WEIGHT",)

    def test_dict_aliases_by_lang_unknown_ignored(self, tmp_path):
        path = _write(tmp_path,
                      "- term: 權重\n  aliases:\n    zh: [比重]\n    en: [weight]\n"
                      "    fr: [poids]\n  it_terms: [WEIGHT]\n")
        entry = glossary.load_glossary(path)[0]
        assert entry.aliases_of("zh") == ("比重",)
        assert entry.aliases_of("en") == ("weight",)
        assert "poids" not in entry.all_aliases()

    def test_missing_file_returns_empty(self, tmp_path):
        assert glossary.load_glossary(tmp_path / "nope.yaml") == []

    def test_broken_yaml_returns_empty(self, tmp_path):
        path = _write(tmp_path, "- term: [unclosed")
        assert glossary.load_glossary(path) == []

    def test_entry_without_term_skipped(self, tmp_path):
        path = _write(tmp_path, "- aliases: [x]\n- term: ok\n  it_terms: [A]\n")
        entries = glossary.load_glossary(path)
        assert [e.term for e in entries] == ["ok"]


class TestMatching:
    def _entries(self, tmp_path):
        return glossary.load_glossary(_write(
            tmp_path,
            "- term: 權重\n  aliases:\n    zh: [比重]\n    en: [weight]\n"
            "  it_terms: [WEIGHT]\n"
            "- term: 單價\n  aliases: [每坪]\n  it_terms: [UNIT_PRICE]\n"))

    def test_match_by_term_substring(self, tmp_path):
        matched = glossary.match_entries("評分的權重是多少", self._entries(tmp_path))
        assert [e.term for e in matched] == ["權重"]

    def test_match_en_alias_case_insensitive(self, tmp_path):
        matched = glossary.match_entries("What is the Weight?", self._entries(tmp_path))
        assert [e.term for e in matched] == ["權重"]

    def test_matched_candidates(self, tmp_path):
        entry = self._entries(tmp_path)[0]
        assert glossary.matched_candidates("權重跟比重", entry) == ["權重", "比重"]

    def test_no_match(self, tmp_path):
        assert glossary.match_entries("完全無關", self._entries(tmp_path)) == []


class TestExpandAndFormat:
    def test_split_identifier(self):
        words = glossary.split_identifier("HouseService.calculateScore")
        assert words == {"house", "service", "calculate", "score"}

    def test_split_identifier_snake_and_short_dropped(self):
        assert glossary.split_identifier("TOTAL_PRICE_x") == {"total", "price"}

    def test_expand_query(self, tmp_path):
        path = _write(tmp_path,
                      "- term: 單價\n  aliases: [每坪]\n"
                      "  it_terms: [HouseService.calcUnitPrice, TOTAL_PRICE]\n")
        extra, matched = glossary.expand_query("每坪多少錢", path)
        assert "price" in extra and "calc" in extra
        assert [e.term for e in matched] == ["單價"]

    def test_format_entries_ja_hidden(self, tmp_path):
        path = _write(tmp_path,
                      "- term: 權重\n  aliases:\n    zh: [比重]\n    ja: [重み]\n"
                      "  it_terms: [WEIGHT]\n  note: 存 DB\n")
        out = glossary.format_entries(glossary.load_glossary(path))
        assert "比重" in out and "重み" not in out
        assert "ja 同義詞 1 則" in out
        assert "存 DB" in out
