"""Tier 3 命中率消融:對單一 AP 比 grep vs semantic 的 top-k 命中率(需人工標註題庫)。

只對 fleet_eval.py 標為「待 Tier 3」的 AP 跑。題庫格式同 eval/questions.yaml:
  - id / expected(top-k 任一結果含任一子字串即命中,lowercase)/ 各語言題目欄位(zh/en…)。

命中判定(對兩引擎對稱、反映 Claude 實際看到的內容):
  讀回傳區塊 file[start-1:end] 的原文 + 檔案路徑,expected 任一子字串出現即命中。

用法:
  .venv\\Scripts\\python.exe -X utf8 scripts\\eval_ablation.py --app NAME
      [--questions eval/questions-NAME.yaml] [--langs zh,en] [--top-k 3]
  題庫預設找 eval/questions-<app>.yaml,找不到退回 eval/questions.yaml。
輸出:eval/ABLATION-<app>.md
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "rosetta"))

import yaml
import glossary
import kb_config
import code_search
import script_args

EVAL_DIR = kb_config.ROOT_DIR / "eval"
_fc: dict = {}


def region(app, rel, start, end):
    if rel not in _fc:
        try:
            _fc[rel] = (app.repo_root / rel).read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            _fc[rel] = []
    ls = _fc[rel]
    return (rel + "\n" + "\n".join(ls[max(0, start - 1):min(len(ls), max(end, start))])).lower()


def grep_hits(app, query, extra, top_k):
    return [region(app, r, s, e) for _, r, s, e, _ in code_search.search(query, top_k, extra, app)], []


def semantic_hits(app, query, extra, top_k):
    import semantic_search
    hits = semantic_search.search(query, top_k, extra, app)
    return ([region(app, h.file_path, h.start_line, h.end_line) for h in hits],
            [h.qualified_name.lower() for h in hits])


def is_hit(expected, regions, names):
    return (any(e.lower() in r for e in expected for r in regions)
            or any(e.lower() in n for e in expected for n in names))


def main():
    name = script_args.flag_value("--app")
    app, err = kb_config.resolve_app(name or "")
    if app is None:
        print(err)
        return 1
    langs = (script_args.flag_value("--langs") or "zh,en").split(",")
    top_k = int(script_args.flag_value("--top-k") or "3")

    qpath = script_args.flag_value("--questions")
    path = Path(qpath) if qpath else EVAL_DIR / f"questions-{app.name}.yaml"
    if not path.is_file():
        fallback = EVAL_DIR / "questions.yaml"
        if not fallback.is_file():
            print(f"找不到題庫:{path}(也沒有 {fallback})。請先為 {app.name} 標註 10~30 題。")
            return 1
        print(f"提醒:{path} 不存在,退用共用題庫 {fallback.name}(建議為 {app.name} 專門標註)。")
        path = fallback
    questions = yaml.safe_load(path.read_text(encoding="utf-8"))

    import semantic_search
    if not semantic_search.available(app):
        print(f"[{app.name}] 語意索引未建,無法比對。先跑 index_all/semantic_index 建索引"
              "(或 fleet_eval.py --build-missing)。")
        return 1

    engines = {"grep": grep_hits, "semantic": semantic_hits}
    res = {e: {l: 0 for l in langs} for e in engines}
    per_q = []
    for q in questions:
        rec = {"id": q["id"], "type": q.get("type", ""), "exp": q["expected"], "e": {}}
        for en, fn in engines.items():
            rec["e"][en] = {}
            for lang in langs:
                query = q.get(lang)
                if not query:
                    rec["e"][en][lang] = None
                    continue
                extra, _ = glossary.expand_query(query, app.glossary_path)
                rg, nm = fn(app, query, extra, top_k)
                ok = is_hit(q["expected"], rg, nm)
                rec["e"][en][lang] = ok
                res[en][lang] += ok
        per_q.append(rec)

    n = len(questions)
    m = {True: "✅", False: "❌", None: "—"}
    lines = [f"# Tier 3 命中率:{app.name}(grep vs semantic)", "",
             f"- 題庫:{path.name}({n} 題)| top-k={top_k} | 語言:{', '.join(langs)}",
             f"- 命中 = top-k 任一回傳區塊(路徑+原文)含 expected 子字串", "",
             "| 引擎 | " + " | ".join(langs) + " | 合計 |", "|---|" + "---|" * (len(langs) + 1)]
    for e in engines:
        tot = sum(res[e].values())
        lines.append(f"| {e} | " + " | ".join(f"{res[e][l]}/{n}" for l in langs)
                     + f" | {tot}/{n*len(langs)} |")
    delta = sum(res["semantic"].values()) - sum(res["grep"].values())
    lines += ["", f"**semantic − grep = {delta:+d}**(合計 {n*len(langs)} 格)。"
              "決策規則:命中率提升 ≥ +10% 且 ≥ +3 絕對(≥30 題)才選 semantic,否則 grep。", ""]
    lines.append("| id | type | expected | " + " | ".join(f"grep/sem {l}" for l in langs) + " |")
    lines.append("|---|---|---|" + "---|" * len(langs))
    for rec in per_q:
        cells = []
        for l in langs:
            cells.append(f"{m[rec['e']['grep'][l]]}/{m[rec['e']['semantic'][l]]}")
        lines.append(f"| {rec['id']} | {rec['type']} | `{','.join(rec['exp'])}` | " + " | ".join(cells) + " |")

    out = EVAL_DIR / f"ABLATION-{app.name}.md"
    out.parent.mkdir(parents=True, exist_ok=True)  # 模板無 eval/ 目錄時自動建立
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines[:9]))
    print(f"\n→ {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
