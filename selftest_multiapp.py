"""multi-AP 路由與隔離驗證(TODO Phase 6「掛第二個 AP 實測」)。

用臨時設定檔(besthouse + demo fixture)覆蓋 kb_config.CONFIG_PATH,
驗證:多 AP 時 app 必帶、search/glossary/config/DB 各層隔離、跨 AP 讀檔被擋。
fixture 在 eval/fixture-app/(自帶,不依賴其他 repo,模板使用者也能跑)。

用法:.venv\\Scripts\\python.exe -X utf8 selftest_multiapp.py
"""

from pathlib import Path
import sys
import tempfile

import kb_config

PASS = "[PASS]"
FAIL = "[FAIL]"
results: list[bool] = []

_TEST_CONFIG = """\
server_name: test-kb
apps:
  - name: besthouse
    description: 房屋喜好評估系統
    repo_root: ..
    search_dirs: [besthouse-backend/src, besthouse-frontend/src]
    resources_dir: besthouse-backend/src/main/resources
    glossary: glossary.yaml
    db:
      driver: mariadb
      table_whitelist: [RATING_DIMENSION, FILTER_RULE]
      sensitive_tables:
        MEMBER: 含個資,排除。
  - name: demo
    description: 訂單系統(fixture)——運費與會員折扣
    repo_root: eval/fixture-app
    search_dirs: [src]
    resources_dir: src/main/resources
    glossary: eval/fixture-app/glossary.yaml
    engine: grep
    db:
      driver: mariadb
      table_whitelist: []
engine: auto
"""


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append(bool(ok))
    print(f"{PASS if ok else FAIL} {name}" + (f" — {detail}" if detail else ""))


def main() -> None:
    original_path = kb_config.CONFIG_PATH
    temp = Path(tempfile.mkdtemp()) / "kb.config.test.yaml"
    temp.write_text(_TEST_CONFIG, encoding="utf-8")
    kb_config.CONFIG_PATH = temp
    kb_config._cache["stamp"] = None
    try:
        import kb_server  # 在覆蓋後 import,其 tools 會走測試設定

        config = kb_config.load_config()
        check("測試設定載入 2 個 app", config.app_names() == ("besthouse", "demo"))

        # 1. 多 AP 時 app 參數必帶
        app, error = config.resolve("")
        check("多 AP 時省略 app 會被拒且提示 list_apps",
              app is None and "list_apps" in error, error[:60])

        # 2. list_apps 給 Claude 路由的資訊
        out = kb_server.list_apps()
        check("list_apps 列出兩個系統與描述",
              "besthouse" in out and "訂單系統" in out and "運費" in out)

        # 3. search_code 路由:同一個問題在兩個 app 命中各自的程式碼
        out_demo = kb_server.search_code("運費怎麼算", app="demo")
        check("demo 搜尋命中 fixture 程式碼",
              "OrderService.java" in out_demo and "calculateShippingFee" in out_demo)
        check("demo 搜尋不含 besthouse 程式碼", "besthouse-backend" not in out_demo)
        out_bh = kb_server.search_code("不含車位的每坪單價怎麼算", app="besthouse")
        check("besthouse 搜尋不受 fixture 污染",
              "OrderService" not in out_bh and "besthouse" in out_bh.lower())

        # 4. glossary 隔離
        out = kb_server.lookup_term("運費", app="demo")
        check("demo glossary 命中「運費」", "calculateShippingFee" in out)
        out = kb_server.lookup_term("運費", app="besthouse")
        check("besthouse glossary 無「運費」(隔離)", "calculateShippingFee" not in out)
        out = kb_server.lookup_term("權重", app="demo")
        check("demo glossary 無 besthouse 的「權重」(隔離)", "RATING_DIMENSION" not in out)

        # 5. config 隔離 + 遮罩
        out = kb_server.get_app_config("datasource", app="demo")
        check("demo config 讀到 fixture 的 yml", "3307/demodb" in out)
        check("demo config 密碼已遮罩", "demo-fake-password" not in out)

        # 6. DB 白名單 per-app
        out = kb_server.query_db_config("RATING_DIMENSION", app="demo")
        check("demo 查 besthouse 的表被拒(白名單 per-app)",
              "白名單" in out and "demo" in out)

        # 7. 跨 AP 讀檔被目錄穿越防護擋下
        out = kb_server.read_source(
            "../../../../besthouse-backend/src/main/resources/application.yml", app="demo")
        check("demo 跨 AP 讀 besthouse 檔案被擋", "超出專案範圍" in out)

    finally:
        kb_config.CONFIG_PATH = original_path
        kb_config._cache["stamp"] = None

    print(f"\n結果:{sum(results)}/{len(results)} 通過")
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
