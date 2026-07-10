"""kb_server:tools 行為(fixture app、grep 引擎)、遮罩、防護、歧義訊號、路由。"""

import pytest

import kb_server
from semantic_search import SemanticHit


@pytest.fixture(autouse=True)
def _config(demo_config):
    """本檔全部測試都跑在 demo(fixture-app)設定上。"""


def _hit(score, qualified_name):
    return SemanticHit(score=score, kind="method", name="x",
                       qualified_name=qualified_name, file_path="f.java",
                       start_line=1, end_line=2)


class TestListAppsAndRouting:
    def test_list_apps_shows_description(self):
        out = kb_server.list_apps()
        assert "demo" in out and "運費" in out

    def test_unknown_app_error(self):
        out = kb_server.lookup_term("運費", app="nope")
        assert "沒有名為" in out and "demo" in out

    def test_single_app_param_optional(self):
        out = kb_server.lookup_term("運費", app="")
        assert "calculateShippingFee" in out

    def test_is_all(self):
        assert kb_server._is_all(" ALL ")
        assert not kb_server._is_all("demo")


class TestLookupTerm:
    def test_hit_formats_entry(self):
        out = kb_server.lookup_term("運費怎麼算", app="demo")
        assert "calculateShippingFee" in out

    def test_no_match_lists_known_terms(self):
        out = kb_server.lookup_term("不存在的詞", app="demo")
        assert "沒有符合" in out and "運費" in out

    def test_all_mode_groups_by_app(self):
        out = kb_server.lookup_term("運費", app="all")
        assert "## demo" in out and "discovery" in out

    def test_all_mode_no_hit_suggests_search(self):
        out = kb_server.lookup_term("完全無關詞", app="all")
        assert "search_code" in out


_FLEET_YAML = """
fleet:
  - server: rosetta-logistics
    team: 物流組(聯絡人:小王)
    endpoint: http://10.0.0.1:8600/mcp
    apps:
      - name: wms
        description: 倉儲管理系統——庫存與出貨
        keywords: [庫存, 出貨]
  - team: 帳務組(聯絡人:小李)
    docs: http://wiki/billing
    apps:
      - name: billing
        description: 請款對帳系統
        keywords: [請款, 對帳]
"""


@pytest.fixture
def fleet_config(demo_config):
    """在 demo 設定上追加 fleet 轉介目錄。"""
    import kb_config
    demo_config.write_text(
        demo_config.read_text(encoding="utf-8") + _FLEET_YAML, encoding="utf-8")
    kb_config._cache["stamp"] = None
    return demo_config


class TestFleetReferral:
    def test_list_apps_shows_fleet_section(self, fleet_config):
        out = kb_server.list_apps()
        assert "其他團隊的系統" in out
        assert "wms" in out and "rosetta-logistics" in out
        assert "http://10.0.0.1:8600/mcp" in out

    def test_list_apps_without_fleet_has_no_section(self):
        assert "其他團隊的系統" not in kb_server.list_apps()

    def test_entry_without_server_gives_contact(self, fleet_config):
        out = kb_server.list_apps()
        assert "尚無 Rosetta server" in out
        assert "帳務組" in out and "http://wiki/billing" in out

    def test_lookup_miss_with_keyword_returns_referral(self, fleet_config):
        out = kb_server.lookup_term("請款單怎麼開", app="demo")
        assert "轉介訊號" in out and "帳務組" in out

    def test_search_miss_with_keyword_returns_referral(self, fleet_config):
        out = kb_server.search_code("倉庫的庫存夠不夠", app="demo")
        assert "轉介訊號" in out and "rosetta-logistics" in out

    def test_miss_without_keyword_points_to_list_apps(self, fleet_config):
        out = kb_server.search_code("魔法蘑菇咒語", app="demo")
        assert "轉介訊號" not in out and "其他團隊的系統" in out

    def test_no_fleet_no_hint_on_miss(self):
        out = kb_server.search_code("魔法蘑菇咒語", app="demo")
        assert "其他團隊" not in out


class TestSearchCode:
    def test_grep_hit_fixture(self):
        out = kb_server.search_code("運費怎麼算", app="demo")
        assert "OrderService.java" in out and "engine=grep" in out

    def test_huge_top_k_clamped_no_error(self):
        out = kb_server.search_code("運費", top_k=999, app="demo")
        assert out.count("### ") <= kb_server._MAX_TOP_K

    def test_empty_result_offers_glossary_terms(self):
        out = kb_server.search_code("魔法蘑菇咒語", app="demo")
        assert "找不到相關程式碼" in out and "運費" in out

    def test_all_mode_skips_unindexed(self):
        out = kb_server.search_code("運費", app="all")
        assert "demo:略過" in out


class TestEngineSelection:
    def test_config_engine_respected(self):
        ctx, _ = kb_server._resolve("demo")
        assert kb_server._engine(ctx) == "grep"

    def test_invalid_env_does_not_override(self, monkeypatch):
        ctx, _ = kb_server._resolve("demo")
        monkeypatch.setenv("KB_ENGINE", "sematic")  # 打錯字
        assert kb_server._engine(ctx) == "grep"

    def test_valid_env_overrides(self, monkeypatch):
        ctx, _ = kb_server._resolve("demo")
        monkeypatch.setenv("KB_ENGINE", "grep")
        assert kb_server._engine(ctx) == "grep"


class TestReadSource:
    def test_read_java_file(self):
        out = kb_server.read_source("src/main/java/demo/OrderService.java", app="demo")
        assert "calculateShippingFee" in out

    def test_yml_password_masked(self):
        out = kb_server.read_source("src/main/resources/application.yml", app="demo")
        assert "demo-fake-password" not in out and "遮罩" in out

    def test_traversal_blocked(self):
        out = kb_server.read_source("../../../rosetta/kb_server.py", app="demo")
        assert "超出專案範圍" in out

    def test_missing_file(self):
        out = kb_server.read_source("src/Nope.java", app="demo")
        assert "找不到檔案" in out

    def test_excerpt_with_header(self):
        out = kb_server.read_source("src/main/java/demo/OrderService.java",
                                    app="demo", start_line=1, end_line=3)
        assert out.startswith("(節錄") and "全檔共" in out

    def test_end_before_start_rejected(self):
        out = kb_server.read_source("src/main/java/demo/OrderService.java",
                                    app="demo", start_line=10, end_line=5)
        assert "end_line" in out and "start_line" in out

    def test_start_beyond_eof(self):
        out = kb_server.read_source("src/main/java/demo/OrderService.java",
                                    app="demo", start_line=9999)
        assert "超過檔案行數" in out

    def test_cap_source_truncates(self):
        ctx, _ = kb_server._resolve("demo")
        text = "x" * (kb_server._MAX_SOURCE_CHARS + 10)
        out = kb_server._cap_source(text, "p", ctx)
        assert "已截斷" in out and len(out) < len(text) + 300


class TestAmbiguitySignals:
    def test_independent_concepts_subset_removed(self):
        import glossary
        entries = [
            glossary.GlossaryEntry("不含車位單價", (("zh", "不含車位單價"),),
                                   ("A",), ""),
            glossary.GlossaryEntry("車位", (("zh", "車位"),), ("B",), ""),
        ]
        result = kb_server._independent_concepts("不含車位單價怎麼算", entries)
        assert [e.term for e in result] == ["不含車位單價"]

    def test_scatter_note_triggers_on_flat_spread(self):
        hits = [_hit(0.50, "a::A::m1"), _hit(0.49, "b::B::m2"), _hit(0.48, "c::C::m3")]
        assert "歧義訊號" in kb_server._scatter_note(hits)

    def test_scatter_note_quiet_with_clear_winner(self):
        hits = [_hit(0.60, "a::A::m1"), _hit(0.50, "b::B::m2"), _hit(0.40, "c::C::m3")]
        assert kb_server._scatter_note(hits) == ""

    def test_scatter_note_quiet_same_class(self):
        hits = [_hit(0.50, "a::A::m1"), _hit(0.49, "a::A::m2"), _hit(0.48, "a::A::m3")]
        assert kb_server._scatter_note(hits) == ""


class TestDbAndConfigTools:
    def test_query_db_config_sensitive_rejected(self):
        out = kb_server.query_db_config("MEMBER", app="demo")
        assert "不可查詢" in out and "個資" in out

    def test_query_db_config_whitelist_rejected(self):
        out = kb_server.query_db_config("OTHER_TABLE", app="demo")
        assert "白名單" in out and "SHIPPING_RULE" in out

    def test_get_app_config_masks(self):
        out = kb_server.get_app_config("datasource", app="demo")
        assert "demo-fake-password" not in out and "3307/demodb" in out


class TestGetStructure:
    def test_no_codegraph_message(self):
        out = kb_server.get_structure("calculateShippingFee", app="demo")
        assert "codegraph" in out
