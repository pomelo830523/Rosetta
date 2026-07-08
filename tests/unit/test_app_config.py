"""app_config:攤平、遮罩(含 mask_text 的 yml/properties/block scalar/flow)、檔案排序。"""

import app_config


class TestFlatten:
    def test_nested_dict(self):
        flat = app_config._flatten({"a": {"b": {"c": 1}}, "d": "x"})
        assert flat == {"a.b.c": "1", "d": "x"}

    def test_list_with_index(self):
        flat = app_config._flatten({"a": [{"b": 1}, "s"]})
        assert flat == {"a[0].b": "1", "a[1]": "s"}

    def test_none_value_becomes_empty(self):
        assert app_config._flatten({"a": None}) == {"a": ""}


class TestMaskValue:
    def test_sensitive_keys_masked(self):
        for key in ("spring.datasource.password", "gemini.api-key", "x.secret",
                    "auth.token", "svc.credential", "tls.private-key"):
            assert app_config.mask_value(key, "raw") == app_config._MASK

    def test_normal_key_untouched(self):
        assert app_config.mask_value("server.port", "8080") == "8080"

    def test_password_inside_url_masked(self):
        out = app_config.mask_value("url", "jdbc:mariadb://h/db?password=abc&x=1")
        assert "abc" not in out and "password=****" in out


class TestMaskText:
    def test_yml_kv_masked_and_line_count_kept(self):
        text = "spring:\n  datasource:\n    password: s3cret\n    username: u\n"
        out = app_config.mask_text(text)
        assert "s3cret" not in out
        assert "username: u" in out
        assert out.count("\n") == text.rstrip("\n").count("\n")

    def test_properties_equals_form_masked(self):
        text = ("db.password=secret1\n"
                "gemini.api-key=AIzaFake2\n"
                "auth.token=tok3\n"
                "normal.key=hello")
        out = app_config.mask_text(text)
        assert "secret1" not in out
        assert "AIzaFake2" not in out
        assert "tok3" not in out
        assert "normal.key=hello" in out

    def test_yml_block_scalar_continuation_masked(self):
        text = ("cfg:\n"
                "  password: |\n"
                "    line1secret\n"
                "    line2secret\n"
                "  next: ok")
        out = app_config.mask_text(text)
        assert "line1secret" not in out and "line2secret" not in out
        assert "next: ok" in out
        assert out.count("\n") == text.count("\n")  # 行數不變

    def test_yml_flow_style_masked(self):
        text = "datasource: {url: jdbc:x, password: pw123, username: u}"
        out = app_config.mask_text(text)
        assert "pw123" not in out
        assert "username" in out

    def test_env_style_masked(self):
        out = app_config.mask_text("API_KEY=abc\nPORT=80")
        assert "abc" not in out and "PORT=80" in out


class TestConfigFiles:
    def test_ordering_base_first_local_last(self, make_app):
        app = make_app()
        for name in ("application-local.yml", "application.yml",
                     "application-prod.yaml"):
            (app.resources_dir / name).write_text("a: 1", encoding="utf-8")
        names = [p.name for p in app_config.config_files(app)]
        assert names[0] == "application.yml"
        assert names[-1] == "application-local.yml"

    def test_missing_dir_returns_empty(self, make_app, tmp_path):
        app = make_app(resources_dir=tmp_path / "no-such")
        assert app_config.config_files(app) == []


class TestEffectiveConfigAndSearch:
    def test_profile_overrides_base(self, make_app):
        app = make_app()
        (app.resources_dir / "application.yml").write_text(
            "server: {port: 1}", encoding="utf-8")
        (app.resources_dir / "application-local.yml").write_text(
            "server: {port: 2}", encoding="utf-8")
        config = app_config.load_effective_config(app)
        assert config["server.port"] == ("2", "application-local.yml")

    def test_parse_error_recorded_not_raised(self, make_app):
        app = make_app()
        (app.resources_dir / "application.yml").write_text(
            "a: [unclosed", encoding="utf-8")
        config = app_config.load_effective_config(app)
        assert any(k.startswith("(parse-error:") for k in config)

    def test_search_config_no_files(self, make_app, tmp_path):
        app = make_app(resources_dir=tmp_path / "no-such")
        assert "讀不到任何 config 檔" in app_config.search_config("", app)

    def test_search_config_mask_and_source(self, make_app):
        app = make_app()
        (app.resources_dir / "application.yml").write_text(
            "spring:\n  datasource:\n    password: raw-pw\n    url: jdbc:x\n",
            encoding="utf-8")
        out = app_config.search_config("datasource", app)
        assert "raw-pw" not in out and "遮罩" in out
        assert "application.yml" in out

    def test_search_config_no_match(self, make_app):
        app = make_app()
        (app.resources_dir / "application.yml").write_text("a: 1", encoding="utf-8")
        assert "沒有符合" in app_config.search_config("zzz", app)
