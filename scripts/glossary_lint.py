"""glossary 防腐化檢測:it_terms 是否仍能在 codegraph / config keys / DB 白名單解析。

AP rename 後對照表會默默失效(檢索 boost 與語意反向注入跟著失效)。本腳本讓
「改了 code 忘了改對照表」在索引排程就被看見,而不是等使用者查不到才發現。

判定規則(寬鬆,避免噪音):
  - 一個條目只要有**任一** it_term 可解析 → 存活;全部無法解析 → DEAD(exit 1)
  - 個別 it_term 無法解析 → warn 供人工檢視(可能是概念性名詞如 MariaDB,可接受)
  - it_term 為 A.B 形式時任一段可解析即算命中;比對不分大小寫、忽略非英數字元
    (TOTAL_PRICE 可對上 entity 欄位 totalPrice)

用法:.venv\\Scripts\\python.exe -X utf8 scripts\\glossary_lint.py [--app NAME]
索引排程整合:index_all.py 於每個 AP 索引後自動附帶執行(dead 不擋索引,只警示)。
"""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "rosetta"))

import app_config
import glossary
import graph_db
import kb_config
import script_args


def _normalize(text: str) -> str:
    return "".join(c for c in text.lower() if c.isalnum())


def known_names(app: kb_config.AppContext) -> set[str]:
    """收集該 AP 所有可解析的名字:codegraph symbol、config key、白名單/敏感表。"""
    names: set[str] = set()
    for sym in graph_db.iter_symbols(app):
        names.add(_normalize(sym.name))
        for part in sym.qualified_name.replace("::", ".").split("."):
            names.add(_normalize(part))
    for key in app_config.load_effective_config(app):
        names.add(_normalize(key))
        for part in key.split("."):
            names.add(_normalize(part))
    for table in app.db.table_whitelist:
        names.add(_normalize(table))
    for table, _reason in app.db.sensitive_tables:
        names.add(_normalize(table))
    names.discard("")
    return names


def lint_app(app: kb_config.AppContext) -> tuple[int, list[str]]:
    """回傳 (dead 條目數, 報告行)。codegraph 缺席時無法可靠判定,跳過。"""
    entries = glossary.load_glossary(app.glossary_path)
    if not entries:
        return 0, [f"[{app.name}] glossary 無條目,略過"]
    if not graph_db.available(app):
        return 0, [f"[{app.name}] 缺 codegraph 圖,無法可靠檢測,略過"
                   "(先跑 codegraph init)"]

    names = known_names(app)
    lines: list[str] = []
    dead = 0
    warned = 0
    for entry in entries:
        if not entry.it_terms:
            # 常見成因:欄位名寫錯(如寫成 maps_to),load_glossary 會靜默略過
            dead += 1
            lines.append(f"[{app.name}] DEAD「{entry.term}」:未填 it_terms"
                         "(檢查該條目欄位名是否寫錯,應為 it_terms)")
            continue
        misses = []
        hits = 0
        for term in entry.it_terms:
            segments = [term, *term.replace("::", ".").split(".")]
            if any(_normalize(s) in names for s in segments if s):
                hits += 1
            else:
                misses.append(term)
        if hits == 0:
            dead += 1
            lines.append(f"[{app.name}] DEAD「{entry.term}」:"
                         f"所有 it_terms 皆無法解析:{', '.join(entry.it_terms)}")
        elif misses:
            warned += 1
            lines.append(f"[{app.name}] warn「{entry.term}」:"
                         f"{', '.join(misses)} 無法解析(另有 {hits} 詞正常)")
    lines.append(f"[{app.name}] 共 {len(entries)} 條:DEAD {dead}、warn {warned}")
    return dead, lines


def main() -> int:
    only = script_args.flag_value("--app")
    config = kb_config.load_config()
    apps = [a for a in config.apps if not only or a.name.lower() == only.lower()]
    if not apps:
        print(f"沒有名為「{only}」的 app。可用:{', '.join(config.app_names())}")
        return 1

    total_dead = 0
    for app in apps:
        dead, lines = lint_app(app)
        total_dead += dead
        print("\n".join(lines))
    return 1 if total_dead else 0


if __name__ == "__main__":
    raise SystemExit(main())
