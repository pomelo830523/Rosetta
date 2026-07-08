"""db_config:URL 解析、filter 驗證、LIKE 跳脫、query_table(白名單/敏感表/假 driver)。"""

import sys
import types

import pytest

import db_config


class TestParseDatasourceUrl:
    def test_mariadb_with_port(self):
        assert db_config.parse_datasource_url(
            "jdbc:mysql://db:3307/x?useSSL=false", "mariadb") == ("db", 3307, "x")

    def test_mariadb_default_port(self):
        assert db_config.parse_datasource_url(
            "jdbc:mariadb://localhost/besthouse", "mariadb") == ("localhost", 3306, "besthouse")

    def test_oracle_default_port(self):
        assert db_config.parse_datasource_url(
            "jdbc:oracle:thin:@dbhost/XEPDB1", "oracle") == ("dbhost", 1521, "XEPDB1")

    def test_invalid_url_raises_with_original(self):
        with pytest.raises(ValueError, match="not-a-jdbc"):
            db_config.parse_datasource_url("not-a-jdbc", "mariadb")

    def test_empty_url_raises(self):
        with pytest.raises(ValueError, match="未設定"):
            db_config.parse_datasource_url("", "oracle")


class TestParseFilter:
    def test_all_empty_returns_none(self):
        assert db_config._parse_filter("", "eq", "") is None

    def test_value_without_column_rejected(self):
        with pytest.raises(db_config.FilterError, match="filter_column"):
            db_config._parse_filter("", "eq", "x")

    def test_column_without_value_rejected(self):
        with pytest.raises(db_config.FilterError, match="filter_value"):
            db_config._parse_filter("NAME", "eq", "")

    def test_unknown_op_rejected(self):
        with pytest.raises(db_config.FilterError, match="filter_op"):
            db_config._parse_filter("NAME", "between", "x")

    def test_valid_filter_normalized(self):
        flt = db_config._parse_filter(" NAME ", " EQ ", " 竹科 ")
        assert (flt.column, flt.op, flt.value) == ("NAME", "eq", "竹科")


class TestHelpers:
    def test_escape_like(self):
        assert db_config._escape_like(r"100%_a\b") == r"100\%\_a\\b"

    def test_match_column_case_insensitive(self):
        assert db_config._match_column("name", ["ID", "NAME"]) == "NAME"

    def test_match_column_missing_lists_available(self):
        with pytest.raises(db_config.FilterError, match="ID, NAME"):
            db_config._match_column("nope", ["ID", "NAME"])


class _FakeCursor:
    def __init__(self, rows):
        self._rows = rows
        self.executed = []
        self.description = None

    def execute(self, sql, args=None):
        self.executed.append((sql, args))
        if sql.startswith("SET SESSION max_statement_time"):
            raise _FAKE_PYMYSQL.err.Error("unknown variable")  # 走 MySQL fallback
        if "LIMIT 0" in sql:
            self.description = [("ID",), ("NAME",)]

    def fetchall(self):
        return self._rows

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class _FakeConnection:
    def __init__(self, rows):
        self.cursor_obj = _FakeCursor(rows)
        self.closed = False

    def cursor(self):
        return self.cursor_obj

    def close(self):
        self.closed = True


_FAKE_PYMYSQL = types.ModuleType("pymysql")
_FAKE_PYMYSQL.err = types.SimpleNamespace(Error=type("Error", (Exception,), {}))


@pytest.fixture
def fake_db(monkeypatch, make_app):
    """假 pymysql + 可解析的 datasource yml;回傳 (app, set_rows)。"""
    app = make_app()
    (app.resources_dir / "application.yml").write_text(
        "spring:\n  datasource:\n    url: jdbc:mariadb://h:3306/d\n"
        "    username: u\n    password: p\n", encoding="utf-8")
    holder = {}

    def connect(**kwargs):
        holder["conn"] = _FakeConnection(holder.get("rows", []))
        return holder["conn"]

    _FAKE_PYMYSQL.connect = connect
    monkeypatch.setitem(sys.modules, "pymysql", _FAKE_PYMYSQL)

    def set_rows(rows):
        holder["rows"] = rows

    return app, holder, set_rows


class TestQueryTable:
    def test_sensitive_table_rejected_with_reason(self, make_app):
        out = db_config.query_table("member", 50, make_app())
        assert "不可查詢" in out and "個資" in out

    def test_non_whitelisted_rejected(self, make_app):
        out = db_config.query_table("OTHER;DROP TABLE X", 50, make_app())
        assert "白名單" in out and "CFG" in out

    def test_connection_params_failure_message(self, make_app):
        # 沒有任何 application.yml → datasource url 解析失敗
        out = db_config.query_table("CFG", 50, make_app())
        assert "連線參數解析失敗" in out

    def test_filter_error_returned_before_connect(self, make_app):
        out = db_config.query_table("CFG", 50, make_app(),
                                    filter_column="", filter_value="x")
        assert "filter_column" in out

    def test_rows_rendered_as_markdown(self, fake_db):
        app, holder, set_rows = fake_db
        set_rows([(1, "甲"), (2, None)])
        out = db_config.query_table("CFG", 50, app)
        assert "| ID | NAME |" in out
        assert "| 2 |  |" in out          # None → 空字串
        assert "共回傳 2 筆" in out
        assert holder["conn"].closed

    def test_limit_reached_warns(self, fake_db):
        app, _, set_rows = fake_db
        set_rows([(1, "a"), (2, "b")])
        out = db_config.query_table("CFG", 2, app)
        assert "結果可能不完整" in out

    def test_eq_filter_binds_value(self, fake_db):
        app, holder, set_rows = fake_db
        set_rows([(1, "竹科")])
        out = db_config.query_table("CFG", 50, app,
                                    filter_column="name", filter_value="竹科")
        sql, args = holder["conn"].cursor_obj.executed[-1]
        assert "WHERE NAME = %s" in sql and args == ("竹科", 50)
        assert "filter: name eq「竹科」" in out  # 註記回顯使用者輸入的欄位名

    def test_starts_with_filter_escapes_and_appends_percent(self, fake_db):
        app, holder, set_rows = fake_db
        set_rows([])
        out = db_config.query_table("CFG", 50, app, filter_column="NAME",
                                    filter_op="starts_with", filter_value="a%b")
        _, args = holder["conn"].cursor_obj.executed[-1]
        assert args[0] == r"a\%b%"
        assert "沒有符合" in out

    def test_contains_filter_wraps_both_sides(self, fake_db):
        app, holder, set_rows = fake_db
        set_rows([(1, "x")])
        db_config.query_table("CFG", 50, app, filter_column="NAME",
                              filter_op="contains", filter_value="v_1")
        _, args = holder["conn"].cursor_obj.executed[-1]
        assert args[0] == r"%v\_1%"

    def test_unknown_column_lists_available(self, fake_db):
        app, _, set_rows = fake_db
        set_rows([])
        out = db_config.query_table("CFG", 50, app,
                                    filter_column="NOPE", filter_value="x")
        assert "不存在" in out and "ID, NAME" in out

    def test_limit_clamped_to_max(self, fake_db):
        app, holder, set_rows = fake_db
        set_rows([])
        db_config.query_table("CFG", 999, app)
        _, args = holder["conn"].cursor_obj.executed[-1]
        assert args == (db_config.MAX_ROWS,)

    def test_oracle_driver_missing_reported(self, make_app, monkeypatch):
        app = make_app(db=__import__("kb_config").DbSettings(
            driver="oracle", table_whitelist=("CFG",), sensitive_tables=()))
        (app.resources_dir / "application.yml").write_text(
            "spring:\n  datasource:\n    url: jdbc:oracle:thin:@h/S\n",
            encoding="utf-8")
        monkeypatch.setitem(sys.modules, "oracledb", None)  # import 觸發 ImportError
        out = db_config.query_table("CFG", 50, app)
        assert "缺少 oracle" in out
