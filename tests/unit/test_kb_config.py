"""kb_config:解析驗證(fail fast)、預設繼承、resolve 路由、mtime 快取。"""

import pytest

import kb_config

_MINIMAL = """\
apps:
  - name: alpha
    description: 甲系統
    repo_root: ../alpha
"""


class TestParse:
    def test_minimal_app_with_defaults(self):
        config = kb_config._parse(_MINIMAL + "engine: grep\nembed_model: m1\n")
        app = config.apps[0]
        assert app.engine == "grep" and app.embed_model == "m1"
        assert app.glossary_path.name == "alpha.yaml"

    def test_app_overrides_global_engine(self):
        config = kb_config._parse(
            "apps:\n  - name: a\n    repo_root: ../a\n    engine: semantic\n"
            "engine: grep\n")
        assert config.apps[0].engine == "semantic"

    @pytest.mark.parametrize("text, message", [
        ("[]", "apps 清單"),
        ("apps: []", "至少要設定一個"),
        ("apps:\n  - repo_root: x\n", "缺少 name"),
        ("apps:\n  - name: all\n    repo_root: x\n", "保留字"),
        ("apps:\n  - name: a\n", "缺少 repo_root"),
        ("apps:\n  - name: a\n    repo_root: x\n    engine: bad\n", "engine"),
    ])
    def test_invalid_configs_raise(self, text, message):
        with pytest.raises(ValueError, match=message):
            kb_config._parse(text)

    def test_duplicate_names_raise(self):
        text = ("apps:\n  - name: a\n    repo_root: x\n"
                "  - name: A\n    repo_root: y\n")
        with pytest.raises(ValueError, match="重複"):
            kb_config._parse(text)

    def test_db_settings_parsed(self):
        text = ("apps:\n  - name: a\n    repo_root: x\n    db:\n"
                "      driver: oracle\n      table_whitelist: [t1]\n"
                "      sensitive_tables:\n        SEC: 理由\n")
        db = kb_config._parse(text).apps[0].db
        assert db.driver == "oracle"
        assert db.table_whitelist == ("T1",)
        assert db.sensitive_reason("SEC") == "理由"
        assert db.sensitive_reason("OTHER") == ""

    def test_bad_driver_raises(self):
        text = "apps:\n  - name: a\n    repo_root: x\n    db: {driver: mssql}\n"
        with pytest.raises(ValueError, match="driver"):
            kb_config._parse(text)


class TestResolve:
    def _config(self, n):
        apps = "".join(f"  - name: app{i}\n    repo_root: ../x{i}\n" for i in range(n))
        return kb_config._parse("apps:\n" + apps)

    def test_empty_name_single_app_ok(self):
        app, error = self._config(1).resolve("")
        assert app is not None and error == ""

    def test_empty_name_multi_app_rejected(self):
        app, error = self._config(2).resolve("")
        assert app is None and "list_apps" in error

    def test_unknown_name_lists_available(self):
        app, error = self._config(2).resolve("nope")
        assert app is None and "app0" in error

    def test_case_insensitive(self):
        app, _ = self._config(1).resolve("APP0")
        assert app is not None


class TestLoadConfig:
    def test_missing_file_raises(self, tmp_path, monkeypatch):
        monkeypatch.setattr(kb_config, "CONFIG_PATH", tmp_path / "nope.yaml")
        kb_config._cache["stamp"] = None
        with pytest.raises(ValueError, match="找不到設定檔"):
            kb_config.load_config()
        kb_config._cache["stamp"] = None

    def test_invalid_yaml_raises(self, tmp_path, monkeypatch):
        path = tmp_path / "kb.yaml"
        path.write_text("apps: [unclosed", encoding="utf-8")
        monkeypatch.setattr(kb_config, "CONFIG_PATH", path)
        kb_config._cache["stamp"] = None
        with pytest.raises(ValueError, match="不是合法 YAML"):
            kb_config.load_config()
        kb_config._cache["stamp"] = None

    def test_mtime_cache_reload(self, demo_config):
        first = kb_config.load_config()
        assert kb_config.load_config() is first  # 快取命中
        demo_config.write_text(
            demo_config.read_text(encoding="utf-8").replace("unit-kb", "unit-kb2"),
            encoding="utf-8")
        import os
        os.utime(demo_config, ns=(1, 1))  # 保證 mtime_ns 改變
        assert kb_config.load_config().server_name in ("unit-kb", "unit-kb2")

    def test_resolve_app_wraps_error(self, tmp_path, monkeypatch):
        monkeypatch.setattr(kb_config, "CONFIG_PATH", tmp_path / "nope.yaml")
        kb_config._cache["stamp"] = None
        app, error = kb_config.resolve_app("x")
        assert app is None and "找不到設定檔" in error
        kb_config._cache["stamp"] = None
