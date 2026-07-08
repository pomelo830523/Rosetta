"""extract_glossary:entity/enum 檔的骨架萃取與 YAML 輸出。"""

import extract_glossary

_ENTITY = '''import jakarta.persistence.*;

@Table(name = "HOUSE")
public class House {
    /** 總價(萬) */
    @Column(name = "TOTAL_PRICE")
    private Long totalPrice;

    @Column(name = "NICKNAME")
    private String nickname;
}
'''

_ENUM = """public enum HouseStatus {
    ACTIVE,   // 追蹤中
    ELIMINATED;
}
"""


class TestExtractFile:
    def test_table_and_columns_extracted(self, tmp_path):
        path = tmp_path / "House.java"
        path.write_text(_ENTITY, encoding="utf-8")
        items = extract_glossary.extract_file(path)
        terms = [i["term"] for i in items]
        assert "(待命名:HOUSE)" in terms
        assert "總價(萬)" in terms                 # JavaDoc 中文當 term 候選
        assert "(待命名:NICKNAME)" in terms       # 無 JavaDoc → 待命名
        table = items[0]
        assert table["it_terms"] == ["HOUSE", "House"]

    def test_enum_constants_with_comment(self, tmp_path):
        path = tmp_path / "HouseStatus.java"
        path.write_text(_ENUM, encoding="utf-8")
        items = extract_glossary.extract_file(path)
        by_term = {i["it_terms"][0]: i for i in items}
        assert by_term["HouseStatus.ACTIVE"]["note"] == "追蹤中"
        assert "HouseStatus.ELIMINATED" in by_term


class TestToYaml:
    def test_skeleton_format(self):
        out = extract_glossary.to_yaml([{
            "term": "總價", "aliases": [],
            "it_terms": ["TOTAL_PRICE", "House"], "note": "含 ' 引號",
        }])
        assert "- term: 總價" in out
        assert "it_terms: [TOTAL_PRICE, House]" in out
        assert "note: '含 '' 引號'" in out          # 單引號跳脫
        assert "TODO 人工補使用者口語" in out
