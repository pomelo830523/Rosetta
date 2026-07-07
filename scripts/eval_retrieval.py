"""模型評測:多語檢索命中率對比(SPEC §8 待定案 → 以此定案)。

3 個 fastembed 多語模型 × 4 語言 × 5 題,in-memory 計算,不動 .semantic/。
評分含 production 同款字面 boost(semantic_search 的混合排序邏輯)。
輸出 markdown 對比表 → eval/RESULT.md。

用法:.venv\\Scripts\\python.exe -X utf8 scripts\\eval_retrieval.py
注意:bge-m3 不在本版 fastembed 支援清單(SPEC 原候選),已記入結果檔限制說明。
"""

from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "rosetta"))

import numpy as np
import yaml

import glossary
import graph_db
import kb_config
import script_args
import semantic_index
from semantic_common import embed_texts
from semantic_search import hybrid_rank, query_words

MODELS = (
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
    "sentence-transformers/paraphrase-multilingual-mpnet-base-v2",
    "intfloat/multilingual-e5-large",
)
LANGS = ("zh", "en", "de", "ja")
TOP_K = 3
EVAL_DIR = kb_config.ROOT_DIR / "eval"


def load_questions() -> list[dict]:
    # 單一題庫檔:zh/en/de/ja 皆內嵌於 questions.yaml。
    return yaml.safe_load((EVAL_DIR / "questions.yaml").read_text(encoding="utf-8"))


def build_corpus(app: kb_config.AppContext) -> tuple[list[dict], list[str]]:
    """跟 semantic_index 相同的 NL 訊號組裝(單一事實來源:直接呼叫其函式)。

    收錄範圍也與 production 一致:只收 search_dirs 內的 symbol。
    """
    injection = semantic_index.glossary_injection(app)
    prefixes = semantic_index.search_prefixes(app)
    file_cache: dict[str, list[str]] = {}
    meta, texts = [], []
    for sym in graph_db.iter_symbols(app):
        if not sym.file_path.startswith(prefixes):
            continue
        if sym.file_path not in file_cache:
            try:
                file_cache[sym.file_path] = (app.repo_root / sym.file_path).read_text(
                    encoding="utf-8", errors="replace").splitlines()
            except OSError:
                file_cache[sym.file_path] = []
        meta.append({"name": sym.name, "qualified_name": sym.qualified_name})
        texts.append(semantic_index.build_nl_text(sym, file_cache[sym.file_path], injection))
    return meta, texts


def rank(query: str, meta: list[dict], vectors: np.ndarray, model: str,
         app: kb_config.AppContext) -> list[str]:
    """production 混合排序(直接呼叫 semantic_search.hybrid_rank,不另維護一份)。"""
    qv = embed_texts([query], kind="query", model_name=model)[0]
    scores = vectors @ qv
    extra_terms, _ = glossary.expand_query(query, app.glossary_path)
    ranked = hybrid_rank(scores, lambda i: meta[i]["name"],
                         TOP_K, query_words(query), extra_terms)
    return [meta[i]["qualified_name"].lower() for _, i in ranked]


def main() -> None:
    app, error = kb_config.resolve_app(script_args.flag_value("--app"))
    if app is None:
        raise SystemExit(error)
    questions = load_questions()
    meta, texts = build_corpus(app)
    print(f"corpus:{len(texts)} symbols;題庫:{len(questions)} 題 × {len(LANGS)} 語言")

    lines = [
        "# 檢索模型評測結果(Phase 3 定案依據)", "",
        f"- corpus:{len(texts)} symbols(NL 訊號,與 production 索引相同組裝)",
        f"- 指標:top-{TOP_K} 命中(production 同款混合排序,含 glossary/identifier boost)",
        "- 限制:SPEC 原候選 bge-m3 不在本版 fastembed 支援清單,未納入;"
        "企業選型時應以 onnx 自行掛載補測。", "",
        "| model | 嵌入耗時 | " + " | ".join(LANGS) + " | 總計 |",
        "|---|---|" + "---|" * (len(LANGS) + 1),
    ]
    for model in MODELS:
        started = time.time()
        vectors = embed_texts(texts, kind="passage", model_name=model)
        embed_secs = time.time() - started
        per_lang, detail = {}, []
        for lang in LANGS:
            hit = 0
            for q in questions:
                if not q.get(lang):
                    continue
                top = rank(q[lang], meta, vectors, model, app)
                ok = any(e in t for e in q["expected"] for t in top)
                hit += ok
                if not ok:
                    detail.append(f"  - {model.split('/')[-1]} [{lang}] {q['id']} miss:top1={top[0] if top else '-'}")
            per_lang[lang] = hit
        total = sum(per_lang.values())
        n = len(questions)
        row = (f"| {model.split('/')[-1]} | {embed_secs:.0f}s | "
               + " | ".join(f"{per_lang[l]}/{n}" for l in LANGS)
               + f" | {total}/{n * len(LANGS)} |")
        lines.append(row)
        print(row)
        if detail:
            lines += ["", "<details><summary>miss 明細(" + model.split("/")[-1] + ")</summary>", ""]
            lines += detail
            lines += ["", "</details>"]

    (EVAL_DIR / "RESULT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("→ eval/RESULT.md")


if __name__ == "__main__":
    main()
