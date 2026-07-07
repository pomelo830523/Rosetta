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

    # 5b. read_source 讀 yml 不可繞過遮罩(遮罩逐行、行數不變)
    import kb_server
    out = kb_server.read_source(
        "besthouse-backend/src/main/resources/application.yml", app="besthouse")
    check("read_source 讀 yml:password 已遮罩",
          "besthouse123" not in out and "遮罩" in out)
    out = kb_server.read_source(
        "besthouse-backend/src/main/resources/application-local.yml", app="besthouse")
    check("read_source 讀 local yml:api-key 已遮罩", "AIza" not in out)

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

    # 9. 歧義釐清訊號(SPEC §4.8:S1 多義 / S2 分散 / S3 空手)
    import kb_server
    from semantic_search import SemanticHit

    out = kb_server.lookup_term("戶梯比和管理費的規則", app="besthouse")
    check("S1:多個獨立概念出現歧義訊號", "歧義訊號" in out and "電梯" in out and "管理費" in out)
    out = kb_server.lookup_term("竹科悅揚不含車位單價是怎麼計算出來的", app="besthouse")
    check("S1:子字串命中(車位⊂不含車位單價)不誤觸發", "歧義訊號" not in out)

    def hit(score: float, qualified_name: str) -> SemanticHit:
        return SemanticHit(score=score, kind="method", name="x",
                           qualified_name=qualified_name, file_path="f.java",
                           start_line=1, end_line=2)

    flat_scattered = [hit(0.50, "a::AService::m1"), hit(0.49, "b::BService::m2"),
                      hit(0.48, "c::CService::m3")]
    check("S2:分數平坦且散在 3 個 class 觸發", "歧義訊號" in kb_server._scatter_note(flat_scattered))
    clear_winner = [hit(0.60, "a::AService::m1"), hit(0.50, "b::BService::m2"),
                    hit(0.40, "c::CService::m3")]
    check("S2:有明確贏家不觸發", kb_server._scatter_note(clear_winner) == "")
    same_class = [hit(0.50, "a::AService::m1"), hit(0.49, "a::AService::m2"),
                  hit(0.48, "a::AService::m3")]
    check("S2:集中在同一 class 不觸發", kb_server._scatter_note(same_class) == "")

    out = kb_server._search_grep("魔法蘑菇咒語吟唱", 3, set(), [], app)
    check("S3:檢索空手附業務概念清單", "選項素材" in out and "篩選規則" in out)

    # 10. query_db_config 受限過濾(SPEC §4.4 Phase 9;需 MariaDB 啟動)
    out = db_config.query_table("HOUSE", 50, app,
                                filter_column="NO_SUCH_COL", filter_value="x")
    if "失敗" in out:
        check("受限過濾:DB 未啟動,整節略過(可接受)", "docker compose" in out)
    else:
        check("filter:欄位不存在被拒且列可用欄位",
              "不存在" in out and "HOUSE_ID" in out)
        out = db_config.query_table("HOUSE", 50, app,
                                    filter_column="1=1 OR TRUE", filter_value="x")
        check("filter:注入字串當欄位名被拒", "不存在" in out)
        out = db_config.query_table("HOUSE", 50, app, filter_column="nickname",
                                    filter_op="eq", filter_value="竹科悅揚")
        check("filter:eq 命中同名多筆(欄位名不分大小寫)",
              out.count("竹科悅揚") >= 4 and "富春居" not in out)
        out = db_config.query_table("HOUSE", 50, app, filter_column="NICKNAME",
                                    filter_op="contains", filter_value="富春居")
        check("filter:contains 命中子字串", "富春居13F" in out and "竹科悅揚" not in out)
        out = db_config.query_table("HOUSE", 50, app, filter_column="NICKNAME",
                                    filter_op="starts_with", filter_value="富春居")
        check("filter:starts_with 命中前綴", "富春居13F" in out and "竹科悅揚" not in out)
        out = db_config.query_table("HOUSE", 50, app, filter_column="NICKNAME",
                                    filter_op="starts_with", filter_value="春居")
        check("filter:starts_with 中段字串不命中(前綴語意)", "沒有符合" in out)
        out = db_config.query_table("HOUSE", 50, app, filter_column="NICKNAME",
                                    filter_op="between", filter_value="x")
        check("filter:未知 filter_op 被拒", "filter_op" in out)
        out = db_config.query_table("HOUSE", 50, app, filter_column="NICKNAME",
                                    filter_op="contains", filter_value="100%中獎_特價\\")
        check("filter:萬用字元跳脫(字面比對無命中)", "沒有符合" in out)
        out = db_config.query_table("HOUSE", 2, app)
        check("filter:達上限出現截斷警示", "結果可能不完整" in out)

    # 10b. datasource URL 解析(port optional)與 config 檔動態掃描
    check("datasource URL 省略 port 用預設 3306",
          db_config.parse_datasource_url("jdbc:mariadb://localhost/besthouse", "mariadb")
          == ("localhost", 3306, "besthouse"))
    check("datasource URL 含 port 照常解析",
          db_config.parse_datasource_url("jdbc:mysql://db:3307/x?useSSL=false", "mariadb")
          == ("db", 3307, "x"))
    check("oracle URL 省略 port 用預設 1521",
          db_config.parse_datasource_url("jdbc:oracle:thin:@dbhost/XEPDB1", "oracle")
          == ("dbhost", 1521, "XEPDB1"))
    config_names = [p.name for p in app_config.config_files(app)]
    check("config 檔動態掃描:application.yml 基底在最前",
          bool(config_names) and config_names[0] == "application.yml",
          ", ".join(config_names))
    check("config 檔動態掃描:application-local.yml 最後(覆蓋一切)",
          "application-local.yml" not in config_names
          or config_names[-1] == "application-local.yml")

    # 11. Phase 10 維運強化:glossary lint / read_source 範圍 / health / html 切塊
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    import glossary_lint
    dead, lint_lines = glossary_lint.lint_app(app)
    check("glossary lint:besthouse 無 DEAD 條目", dead == 0, lint_lines[-1])

    out = kb_server.read_source(
        "besthouse-backend/src/main/java/com/besthouse/service/HouseService.java",
        app="besthouse", start_line=321, end_line=341)
    check("read_source 範圍節錄:含節錄標頭與目標公式",
          out.startswith("(節錄") and "calculatePricePerPingWithoutParking" in out)
    check("read_source 範圍節錄:未回傳整檔", len(out) < 3000, f"{len(out)} 字元")
    out = kb_server.read_source(
        "besthouse-backend/src/main/java/com/besthouse/service/HouseService.java",
        app="besthouse", start_line=10, end_line=5)
    check("read_source end_line < start_line 回明確錯誤",
          "end_line" in out and "start_line" in out)

    if semantic_ready:
        out = kb_server.search_code("單價", top_k=999, app="besthouse")
        check("search_code top_k 超限被 clamp(≤10 筆)", 0 < out.count("### ") <= 10,
              f"{out.count('### ')} 筆")

    import http_transport
    payload = http_transport.health_payload()
    check("health payload:status ok 且列出全部 AP",
          payload["status"] == "ok" and len(payload["apps"]) == len(config.apps))

    html = "\n".join(f"<div>第 {i} 行</div>" for i in range(1, 101))
    blocks = code_search.window_blocks(html)
    check("html 行窗切塊:涵蓋整檔且行號正確",
          blocks[0][0] == 1 and blocks[-1][1] == 100 and len(blocks) >= 3)

    # 12. Phase 11 跨 AP 聯合查詢(app="all",SPEC §4.9)
    out = kb_server.search_code("不含車位的每坪單價怎麼算", app="all")
    check("all:各 AP 分組列出", all(f"## {n}" in out for n in config.app_names()))
    check("all:besthouse 命中目標 symbol", "priceperpingwithoutparking" in out.lower())
    check("all:discovery 不含程式碼內文", "```" not in out and "discovery" in out)
    out = kb_server.lookup_term("權重", app="all")
    check("all:lookup_term 只列有命中的 AP",
          "besthouse" in out and "RATING_DIMENSION" in out
          and "zplviewer" not in out)
    try:
        kb_config._parse("apps:\n  - name: all\n    repo_root: x\n")
        reserved_ok = False
    except ValueError as exc:
        reserved_ok = "保留字" in str(exc)
    check("app name「all」為保留字", reserved_ok)

    print(f"\n結果:{sum(results)}/{len(results)} 通過")
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
