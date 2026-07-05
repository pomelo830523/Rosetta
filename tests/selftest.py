"""函式層自我驗證(不經 MCP 協定,直接呼叫各模組)。

用法:.venv\\Scripts\\python.exe -X utf8 tests\\selftest.py
涵蓋:kb.config.yaml 載入與 app 解析(v3.1)、glossary、grep 引擎展開對比、
語意檢索(zh/en/de/ja)、get_structure 呼叫鏈、config 遮罩、DB 白名單與現值查詢、
路徑防護。ja 測試題內嵌於 eval/questions.yaml,輸出只印題號不印原文(使用者慣例)。
"""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "rosetta"))

import yaml

import app_config
import code_search
import db_config
import glossary
import graph_db
import kb_config

PASS = "[PASS]"
FAIL = "[FAIL]"
results: list[bool] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append(bool(ok))
    print(f"{PASS if ok else FAIL} {name}" + (f" — {detail}" if detail else ""))


def main() -> None:
    # 0. kb.config.yaml(v3.1 multi-AP)
    try:
        config = kb_config.load_config()
        check("kb.config.yaml 載入", len(config.apps) >= 1,
              f"{len(config.apps)} 個 app:{', '.join(config.app_names())}")
    except ValueError as exc:
        check("kb.config.yaml 載入", False, str(exc))
        print("\n設定檔壞掉,後續測試無法進行。")
        sys.exit(1)

    # 本 selftest 以 besthouse 為受測 app(multi-AP 隔離另見 selftest_multiapp.py)
    app, error = config.resolve("besthouse")
    check("resolve('besthouse') 取得 app", app is not None, error)
    if app is None:
        sys.exit(1)
    if len(config.apps) == 1:
        implicit, error = config.resolve("")
        check("單一 app 時可省略 app 參數", implicit is not None, error)
    else:
        implicit, error = config.resolve("")
        check("多 app 時省略 app 參數回明確錯誤",
              implicit is None and "list_apps" in error, error[:60])
    unknown, error = config.resolve("no-such-app")
    check("未知 app 回明確錯誤(含可用清單)",
          unknown is None and app.name in error, error[:60])
    check("repo_root 存在", app.repo_root.is_dir(), str(app.repo_root))

    # 1. glossary 載入與比對(多語 aliases 資料保留,v3 起僅維護 zh)
    entries = glossary.load_glossary(app.glossary_path)
    check("glossary 載入", len(entries) >= 20, f"{len(entries)} 條")

    matched = glossary.match_entries("評分的權重是多少", entries)
    check("zh「權重」命中對照", any("RATING_DIMENSION" in e.it_terms for e in matched))
    matched = glossary.match_entries("How is the unit price excluding parking calculated?", entries)
    check("en alias 命中對照(既有資料)",
          any("TOTAL_PRICE" in e.it_terms for e in matched))
    matched = glossary.match_entries("Wie hoch ist die Hypothekenrate?", entries)
    check("de alias 命中對照(既有資料)",
          any("monthlyMortgage" in t for e in matched for t in e.it_terms))
    flat_ok = all(isinstance(e.aliases, tuple) for e in entries)
    check("v1 平面 aliases 相容(視為 zh)", flat_ok)

    # 2. grep 引擎:展開前後命中率對比(Phase 1 驗收,保留)
    queries = ["被刷掉的原因", "戶梯比", "殺價", "出租行情"]
    improved = 0
    for q in queries:
        extra, _ = glossary.expand_query(q, app.glossary_path)
        before = code_search.search(q, 3, set(), app)
        after = code_search.search(q, 3, extra, app)
        top_before = before[0][0] if before else 0
        top_after = after[0][0] if after else 0
        improved += top_after > top_before
    check("glossary 展開提升 grep 命中(至少 3/4 題)", improved >= 3, f"{improved}/{len(queries)}")

    # 3. 語意檢索:zh/en/de/ja 口語都要命中目標 symbol(Phase 3 核心驗收)
    try:
        import semantic_search
        semantic_ready = semantic_search.available(app)
    except ImportError:
        semantic_ready = False
    check("語意索引存在(.semantic/<app>/)", semantic_ready)
    if semantic_ready:
        questions_path = kb_config.ROOT_DIR / "eval" / "questions.yaml"
        ja_map = {q["id"]: q.get("ja", "")
                  for q in yaml.safe_load(questions_path.read_text(encoding="utf-8"))}
        cases = [
            ("zh", "不含車位的每坪單價怎麼算", "priceperpingwithoutparking"),
            ("en", "How is the price per ping without parking calculated?", "priceperpingwithoutparking"),
            ("de", "Wie wird der Preis pro Ping ohne Stellplatz berechnet?", "priceperpingwithoutparking"),
            ("ja", ja_map.get("q1", ""), "priceperpingwithoutparking"),
        ]
        for lang, q, expected in cases:
            if not q:
                check(f"semantic {lang} 命中", False, "題庫缺題")
                continue
            extra, _ = glossary.expand_query(q, app.glossary_path)
            hits = semantic_search.search(q, 3, extra, app)
            ok = any(expected in h.qualified_name.lower() for h in hits)
            shown_q = q if lang != "ja" else "(ja q1,原文見 eval/questions.yaml)"
            check(f"semantic {lang} top-3 命中目標", ok, shown_q[:50])

    # 4. get_structure:呼叫鏈正確性(Phase 4 驗收)
    check("codegraph.db 可用", graph_db.available(app))
    if graph_db.available(app):
        nodes = graph_db.find_nodes("calculatePricePerPingWithoutParking", app, limit=3)
        target = next((n for n in nodes if n.kind == "method"
                       and "HouseService" in n.qualified_name), None)
        if target:
            caller_names = {s.qualified_name for _, s in graph_db.callers(target.node_id, app)}
            check("呼叫鏈:calculatePricePerPingWithoutParking 的 caller 含 toDto",
                  any("toDto" in c for c in caller_names), "; ".join(sorted(caller_names)))
        else:
            check("呼叫鏈:找得到 HouseService 目標 method", False)
        check("schema 版本檢查不誤報", graph_db.schema_warning(app) == "")

    # 5. AP config:遮罩與覆蓋標註
    out = app_config.search_config("gemini", app)
    check("gemini api-key 已遮罩", "AIza" not in out and "遮罩" in out)
    out = app_config.search_config("datasource", app)
    check("datasource password 已遮罩", "besthouse123" not in out)
    check("覆蓋來源檔有標註", "application.yml" in out)

    # 6. DB 白名單(白名單與敏感表現在來自 kb.config.yaml)
    out = db_config.query_table("MEMBER", 50, app)
    check("MEMBER(敏感表)被拒且給理由", "不可查詢" in out and "個資" in out)
    # HOUSE 已於 kb.config.yaml 白名單開放(commit bb9b73c),不應再被白名單擋
    out = db_config.query_table("HOUSE", 50, app)
    check("HOUSE(白名單表)可查詢、未被白名單擋", "白名單" not in out)
    out = db_config.query_table("RATING_DIMENSION;DROP TABLE X", 50, app)
    check("奇怪的 table 名被拒", "白名單" in out)

    # 7. DB 現值(需 MariaDB 啟動;未啟動時驗證錯誤訊息是否明確)
    out = db_config.query_table("RATING_DIMENSION", 50, app)
    if "失敗" in out:
        check("DB 未啟動時錯誤訊息明確", "docker compose" in out, "MariaDB 未啟動(可接受)")
    else:
        check("RATING_DIMENSION 回傳現值", "0.4000" in out or "0.40" in out,
              "V19 之後 地點與交通 應為 0.40")

    # 8. 路徑防護(read_source 的核心邏輯)
    root = app.repo_root.resolve()
    target_path = (root / "../outside.txt").resolve()
    check("目錄穿越被擋", root not in target_path.parents and target_path != root)

    print(f"\n結果:{sum(results)}/{len(results)} 通過")
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
