"""艦隊級引擎決策實驗(Tier 1+2):逐 AP 量規模/延遲/建置成本/引擎分歧,
   套決策規則產出「每 AP 用 grep 還是要建語意索引」的暫定判定 + 全艦隊 rollup。

設計與門檻見 eval/FLEET-EVAL.md。品質命中率(Tier 3)用 scripts/eval_ablation.py。

量什麼(逐 AP,全自動、免標註):
  A 規模    :LOC、symbol 數
  B 延遲    :grep vs semantic 查詢 p50/p95/max(model 冷載另計)—— 50 AP 的關鍵訊號
  C 建置成本:語意索引首建時間(--build 才實測,否則以單位成本試算)、記憶體、磁碟
  D① 分歧度 :grep/semantic top-k 重疊(Jaccard、top-1 一致)—— 免標註的品質探針
  D  命名   :identifier 資訊量(中位詞數、opaque 佔比)、註解覆蓋(抽樣)

用法:
  .venv\\Scripts\\python.exe -X utf8 scripts\\fleet_eval.py [--app NAME] [--queries N]
      [--build-missing] [--build] [--model NAME]
  --app          只跑指定 AP(省略=全部)
  --queries N    每 AP 查詢數(預設 40;愈多延遲統計愈穩)
  --build-missing 對沒有語意索引的 AP 先建一次(否則其 semantic 指標標「略過」)
  --build        對每個 AP 實測首建時間(rebuild;很慢,大艦隊慎用)
  --model NAME   覆蓋 embedding model(如測 MiniLM 首建加速)
輸出:eval/FLEET-REPORT.md(+ 終端摘要)
"""
from pathlib import Path
import random
import statistics
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "rosetta"))

import code_search
import glossary
import graph_db
import kb_config
import script_args
import semantic_index
from semantic_common import get_model_name, index_paths

# ---- 決策門檻(可依團隊需求調整;對應 FLEET-EVAL.md 決策規則)----
LATENCY_P95_BUDGET_MS = 1000.0   # grep p95 超過即「延遲驅動」需 semantic(SPEC search_code < 1s)
JACCARD_EQUIVALENT = 0.60        # top-k 重疊 ≥ 此值視為兩引擎等價 → grep 足矣
NAMING_MIN_MEDIAN_TOKENS = 2     # symbol 名中位拆詞數 < 2 視為命名貧弱
NAMING_MAX_OPAQUE_FRAC = 0.30    # opaque 名(單字母/純縮寫/拆不出 2 詞)佔比上限
TOP_K = 3
E5_SEC_PER_SYMBOL = 0.35         # 首建試算單價(ENTERPRISE-GAP §0 實測)
MINILM_SEC_PER_SYMBOL = 0.021
EVAL_DIR = kb_config.ROOT_DIR / "eval"


def _pct(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = (len(s) - 1) * q
    lo = int(k)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def _file_lines_cache() -> dict:
    return {}


def loc_and_symbols(app) -> tuple[int, list[graph_db.Symbol]]:
    """LOC(search_dirs 內原始碼行數)與可索引 symbol(過 search_dirs)。"""
    loc = 0
    for path in code_search.iter_source_files(app):
        try:
            loc += sum(1 for _ in path.open("r", encoding="utf-8", errors="replace"))
        except OSError:
            pass
    prefixes = semantic_index.search_prefixes(app)
    symbols = [s for s in graph_db.iter_symbols(app)
               if s.file_path.startswith(prefixes)] if graph_db.available(app) else []
    return loc, symbols


def build_queries(app, symbols, n: int) -> list[str]:
    """免標註查詢集:glossary 業務詞(中文)+ 抽樣 identifier(英文)。"""
    rng = random.Random(0)
    zh = []
    for e in glossary.load_glossary(app.glossary_path):
        zh.append(e.term)
        zh.extend(e.all_aliases())
    rng.shuffle(zh)
    ids = [s.name for s in symbols if s.name and len(s.name) >= 4]
    rng.shuffle(ids)
    half = max(1, n // 2)
    queries = zh[:half] + ids[:n - len(zh[:half])]
    return [q for q in queries if q][:n] or ids[:n]


def _hit_ranges_grep(app, query):
    et, _ = glossary.expand_query(query, app.glossary_path)
    return [(rel, s, e) for _, rel, s, e, _ in code_search.search(query, TOP_K, et, app)]


def _hit_ranges_semantic(app, query, search):
    et, _ = glossary.expand_query(query, app.glossary_path)
    return [(h.file_path, h.start_line, h.end_line) for h in search(query, TOP_K, et, app)]


def _overlap(a, b) -> bool:
    """兩個 (file, start, end) 是否指向同一段(同檔且行範圍相交)。"""
    return a[0] == b[0] and a[1] <= b[2] and b[1] <= a[2]


def _jaccard(g: list, s: list) -> float:
    if not g and not s:
        return 1.0
    inter = sum(1 for x in g if any(_overlap(x, y) for y in s))
    union = len(g) + len(s) - inter
    return inter / union if union else 0.0


def time_engine(fn, queries: list[str]) -> dict:
    """回傳 {p50, p95, max, cold_ms}(ms);第一次呼叫含冷啟另計。"""
    if not queries:
        return {"p50": 0, "p95": 0, "max": 0, "cold_ms": 0}
    t0 = time.perf_counter()
    fn(queries[0])                       # 冷啟(含 model 載入 / OS 檔案 cache)
    cold_ms = (time.perf_counter() - t0) * 1000
    lat = []
    for q in queries[1:] or queries:
        t = time.perf_counter()
        fn(q)
        lat.append((time.perf_counter() - t) * 1000)
    return {"p50": _pct(lat, 0.5), "p95": _pct(lat, 0.95), "max": max(lat), "cold_ms": cold_ms}


def naming_quality(app, symbols) -> dict:
    """命名資訊量 proxy:拆詞中位數、opaque 佔比、註解覆蓋(抽樣)。"""
    if not symbols:
        return {"median_tokens": 0, "opaque_frac": 1.0, "comment_frac": 0.0}
    token_counts, opaque = [], 0
    for s in symbols:
        toks = glossary.split_identifier(s.name)
        token_counts.append(len(toks))
        if len(toks) < 2 or len(s.name) <= 3:
            opaque += 1
    # 註解覆蓋:抽樣讀原始碼,看宣告上方是否有可用註解
    rng = random.Random(1)
    sample = rng.sample(symbols, min(100, len(symbols)))
    lines_cache: dict = {}
    with_comment = 0
    for s in sample:
        if s.file_path not in lines_cache:
            try:
                lines_cache[s.file_path] = (app.repo_root / s.file_path).read_text(
                    encoding="utf-8", errors="replace").splitlines()
            except OSError:
                lines_cache[s.file_path] = []
        _, comments = semantic_index._extract_context_lines(lines_cache[s.file_path], s.start_line)
        with_comment += bool(comments)
    return {
        "median_tokens": statistics.median(token_counts),
        "opaque_frac": opaque / len(symbols),
        "comment_frac": with_comment / len(sample) if sample else 0.0,
    }


def decide(grep_p95, jaccard, naming, semantic_available) -> tuple[str, str]:
    """回傳 (暫定引擎, 註記)。jaccard/semantic 不可得時只用延遲 + 命名。"""
    naming_ok = (naming["median_tokens"] >= NAMING_MIN_MEDIAN_TOKENS
                 and naming["opaque_frac"] < NAMING_MAX_OPAQUE_FRAC)
    if grep_p95 > LATENCY_P95_BUDGET_MS:
        return "semantic/auto", f"延遲驅動(grep p95 {grep_p95:.0f}ms > {LATENCY_P95_BUDGET_MS:.0f})"
    if not semantic_available:
        base = "grep(暫定)"
        if not naming_ok:
            return base, "命名貧弱且無語意索引可比 → 建索引後跑 Tier 3(--build-missing)"
        return base, "grep 延遲 OK;無語意索引可比分歧,命名健康暫定 grep"
    if jaccard >= JACCARD_EQUIVALENT and naming_ok:
        return "grep", f"grep 延遲 OK、與 semantic 高度重疊(Jaccard {jaccard:.2f})、命名健康"
    reason = []
    if jaccard < JACCARD_EQUIVALENT:
        reason.append(f"分歧大(Jaccard {jaccard:.2f})")
    if not naming_ok:
        reason.append(f"命名貧弱(中位詞 {naming['median_tokens']:.0f}、opaque {naming['opaque_frac']:.0%})")
    return "待 Tier 3", "、".join(reason) + " → 標註 10~30 題跑 eval_ablation.py 定奪"


def eval_app(app, n_queries, build_missing, do_build, model_override) -> dict:
    r = {"name": app.name, "engine_cfg": app.engine}
    loc, symbols = loc_and_symbols(app)
    r["loc"], r["symbols"] = loc, len(symbols)
    r["naming"] = naming_quality(app, symbols)

    queries = build_queries(app, symbols, n_queries)
    r["n_queries"] = len(queries)

    # grep 延遲(永遠可測)
    r["grep"] = time_engine(lambda q: _hit_ranges_grep(app, q), queries)

    # 語意索引:必要時先建
    import semantic_search
    if not semantic_search.available(app) and build_missing:
        if model_override:
            import os
            os.environ["KB_EMBED_MODEL"] = model_override
        print(f"  [{app.name}] --build-missing:建語意索引中…")
        print("   " + semantic_index.build(app, rebuild=True))
    sem_ok = semantic_search.available(app)
    r["semantic_available"] = sem_ok

    if sem_ok:
        r["sem"] = time_engine(lambda q: _hit_ranges_semantic(app, q, semantic_search.search), queries)
        # 分歧度
        jac, top1 = [], 0
        for q in queries:
            g = _hit_ranges_grep(app, q)
            s = _hit_ranges_semantic(app, q, semantic_search.search)
            jac.append(_jaccard(g, s))
            if g and s and _overlap(g[0], s[0]):
                top1 += 1
        r["jaccard"] = statistics.mean(jac) if jac else 0.0
        r["top1_agree"] = top1 / len(queries) if queries else 0.0
        r["model"] = semantic_search.index_model(app)
        r["dim"] = 1024 if "e5-large" in r["model"] else (
            384 if "MiniLM" in r["model"] else 768)
        r["vectors_mb"] = index_paths(app).vectors.stat().st_size / 1e6
    else:
        r["sem"] = None
        r["jaccard"] = None
        r["top1_agree"] = None
        r["model"] = model_override or get_model_name(app)
        r["dim"] = 1024 if "e5-large" in r["model"] else (384 if "MiniLM" in r["model"] else 768)
        r["vectors_mb"] = None

    # C 建置成本
    if do_build:
        t0 = time.perf_counter()
        semantic_index.build(app, rebuild=True)
        r["build_sec"] = time.perf_counter() - t0
        r["build_note"] = "實測"
    else:
        unit = MINILM_SEC_PER_SYMBOL if "MiniLM" in r["model"] else E5_SEC_PER_SYMBOL
        r["build_sec"] = len(symbols) * unit
        r["build_note"] = "試算"
    r["mem_mb"] = len(symbols) * r["dim"] * 4 / 1e6

    jac = r["jaccard"] if r["jaccard"] is not None else 0.0
    r["tentative"], r["reason"] = decide(r["grep"]["p95"], jac, r["naming"], sem_ok)
    return r


def _fmt_ms(d):
    return f"{d['p50']:.0f}/{d['p95']:.0f}/{d['max']:.0f}" if d else "—"


def write_report(rows: list[dict], out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)  # 模板無 eval/ 目錄時自動建立
    lines = ["# 艦隊引擎決策報告(Tier 1+2,fleet_eval.py)", ""]
    lines.append(f"- AP 數:{len(rows)} | 門檻:grep p95 ≤ {LATENCY_P95_BUDGET_MS:.0f}ms、"
                 f"Jaccard ≥ {JACCARD_EQUIVALENT}、中位詞 ≥ {NAMING_MIN_MEDIAN_TOKENS}、"
                 f"opaque < {NAMING_MAX_OPAQUE_FRAC:.0%}")
    lines.append("- 延遲為 p50/p95/max(ms);semantic 指標需已建索引(否則以 --build-missing 先建)")
    lines.append("")

    lines.append("## A 規模 + B 延遲")
    lines.append("| AP | engine | LOC | symbols | grep p50/95/max | sem p50/95/max | sem 冷載 |")
    lines.append("|---|---|--:|--:|---|---|--:|")
    for r in rows:
        lines.append(f"| {r['name']} | {r['engine_cfg']} | {r['loc']:,} | {r['symbols']:,} "
                     f"| {_fmt_ms(r['grep'])} | {_fmt_ms(r['sem'])} "
                     f"| {r['sem']['cold_ms']:.0f}ms |" if r['sem'] else
                     f"| {r['name']} | {r['engine_cfg']} | {r['loc']:,} | {r['symbols']:,} "
                     f"| {_fmt_ms(r['grep'])} | — | — |")
    lines.append("")

    lines.append("## C 成本 + D 品質探針 + 判定")
    lines.append("| AP | 首建 | 記憶體 | Jaccard | top1一致 | 中位詞 | opaque | 註解覆蓋 | 暫定引擎 | 依據 |")
    lines.append("|---|--:|--:|--:|--:|--:|--:|--:|---|---|")
    for r in rows:
        nm = r["naming"]
        jac = f"{r['jaccard']:.2f}" if r["jaccard"] is not None else "—"
        t1 = f"{r['top1_agree']:.0%}" if r["top1_agree"] is not None else "—"
        lines.append(
            f"| {r['name']} | {r['build_sec']:.0f}s({r['build_note']}) | {r['mem_mb']:.0f}MB "
            f"| {jac} | {t1} | {nm['median_tokens']:.0f} | {nm['opaque_frac']:.0%} "
            f"| {nm['comment_frac']:.0%} | **{r['tentative']}** | {r['reason']} |")
    lines.append("")

    # rollup(依 tentative 前綴/關鍵字分桶)
    grep_rows = [r for r in rows if r["tentative"].startswith("grep")]
    semantic_rows = [r for r in rows if "semantic" in r["tentative"]]
    tier3 = [r for r in rows if "Tier 3" in r["tentative"]]
    index_rows = semantic_rows + tier3   # 這些「可能」要建索引,取成本上界
    tot_build = sum(r["build_sec"] for r in index_rows)
    tot_mem = sum(r["mem_mb"] for r in index_rows)
    lines.append("## 全艦隊 rollup")
    lines.append(f"- 暫定 **grep**(零建置/零常駐):{len(grep_rows)} 個 AP")
    lines.append(f"- 判定 **要語意索引**(延遲驅動或品質):{len(semantic_rows)} 個 AP")
    lines.append(f"- 需人工標註跑 Tier 3(eval_ablation.py)才能定奪:{len(tier3)} 個 AP —— "
                 f"{', '.join(r['name'] for r in tier3) or '無'}")
    lines.append(f"- 成本上界(若上述要索引的 AP 全建 semantic):首建合計 ≈ "
                 f"**{tot_build/3600:.1f} 小時**(一次性)、常駐記憶體 ≈ **{tot_mem:.0f} MB**")
    lines.append(f"- 判定:{'首建可過夜' if tot_build < 12*3600 else '首建過長,大 AP 建議改 MiniLM 或 GPU'}"
                 f";記憶體 {'單機無壓力' if tot_mem < 4000 else '注意單機預算(考慮 int8 或分片)'}")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    only = script_args.flag_value("--app")
    n = int(script_args.flag_value("--queries") or "40")
    model_override = script_args.flag_value("--model")
    build_missing = "--build-missing" in sys.argv
    do_build = "--build" in sys.argv

    config = kb_config.load_config()
    apps = [a for a in config.apps if not only or a.name.lower() == only.lower()]
    if not apps:
        print(f"沒有名為「{only}」的 app。可用:{', '.join(config.app_names())}")
        return 1

    rows = []
    for app in apps:
        if not graph_db.available(app):
            print(f"[{app.name}] 無 codegraph 圖,略過(symbol 數/語意索引無法量;先 codegraph init)")
            continue
        print(f"[{app.name}] 量測中(queries={n})…")
        try:
            rows.append(eval_app(app, n, build_missing, do_build, model_override))
        except Exception as exc:  # 單一 AP 失敗不擋全艦隊
            print(f"[{app.name}] 量測失敗:{exc}")

    if not rows:
        print("沒有可量測的 AP。")
        return 1
    out = EVAL_DIR / "FLEET-REPORT.md"
    write_report(rows, out)
    print(f"\n→ {out}")
    for r in rows:
        print(f"  {r['name']:14} grep p95={r['grep']['p95']:.0f}ms  "
              f"jaccard={r['jaccard'] if r['jaccard'] is None else round(r['jaccard'],2)}  "
              f"→ {r['tentative']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
