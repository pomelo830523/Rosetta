"""語意檢索:ANN top-k + glossary/精確 identifier boost(混合排序)。

查詢期只做:query 向量化 + 內積 + 少量字面 boost —— 不掃 repo。
向量庫為 numpy 單檔暴力內積:BestHouse(約 1k symbols)< 1ms;
一隊一台、百萬行以內(~10 萬 symbols)仍 < 0.1s,現行夠用。
超出定位(千萬行/高並發)才換 hnswlib/Qdrant,本模組介面不變(SPEC §4.5)。
"""

import json
from dataclasses import dataclass

import numpy as np

from kb_config import AppContext
from semantic_common import embed_texts, index_paths

# 混合排序權重:精確 identifier 命中必須贏過純語意近似(SPEC §4.2)。
# boost 按「命中詞數」累計:calculatePricePerPingWithoutParking 命中 5 個展開詞
# 要贏過只沾到 price 一個詞的 totalPrice(eval 發現的系統性誤排)。
_TYPED_WORD_BOOST = 0.08    # 使用者親打的詞,每命中一詞(上限 0.24)
_GLOSSARY_WORD_BOOST = 0.04 # glossary 展開詞,每命中一詞(上限 0.20)
_MIN_SCORE = 0.15           # 低於此分數視為雜訊不回傳


@dataclass(frozen=True)
class SemanticHit:
    score: float
    kind: str
    name: str
    qualified_name: str
    file_path: str
    start_line: int
    end_line: int


_caches: dict[str, dict] = {}  # app.name → {stamp, meta, vectors, state}


def available(app: AppContext) -> bool:
    return index_paths(app).all_exist()


def index_info(app: AppContext) -> str:
    state = _load(app)["state"]
    return f"model={state.get('model')}, built_at={state.get('built_at')}"


def index_model(app: AppContext) -> str:
    """該 app 索引所用的 embedding model(all 模式跨 AP 重用 query 向量的分組鍵)。"""
    return _load(app)["state"].get("model") or ""


def _load(app: AppContext) -> dict:
    """載入該 app 的索引,以 state.json 的 mtime 做快取失效(index 重建後免重啟 server)。"""
    paths = index_paths(app)
    cache = _caches.setdefault(app.name, {"stamp": None})
    stamp = paths.state.stat().st_mtime_ns
    if cache["stamp"] != stamp:
        meta = [
            json.loads(l) for l in paths.meta.read_text(encoding="utf-8").splitlines() if l
        ]
        vectors = np.load(paths.vectors)
        if len(meta) != len(vectors):
            raise ValueError(
                f"app「{app.name}」語意索引不一致(meta {len(meta)} 筆 / "
                f"vectors {len(vectors)} 筆),可能正在重建;請稍後重試,"
                "持續發生則重跑 semantic_index --rebuild。")
        cache["meta"] = meta
        cache["vectors"] = vectors
        cache["state"] = json.loads(paths.state.read_text(encoding="utf-8"))
        cache["stamp"] = stamp
        import kb_log
        kb_log.setup().info(
            "語意索引載入 app=%s symbols=%d model=%s built_at=%s",
            app.name, len(cache["meta"]),
            cache["state"].get("model"), cache["state"].get("built_at"))
    return cache


def query_words(query: str) -> set[str]:
    """使用者親打的英數詞(≥3 字元),用於精確命中 boost。"""
    word = ""
    words = set()
    for ch in query.lower():
        if ch.isalnum():
            word += ch
        else:
            if len(word) >= 3:
                words.add(word)
            word = ""
    if len(word) >= 3:
        words.add(word)
    return words


def literal_boost(name_lower: str, typed_words: set[str], extra_terms: set[str]) -> float:
    """字面 boost:親打詞與 glossary 展開詞按命中詞數累計(各自封頂)。"""
    typed_hits = sum(1 for w in typed_words if w in name_lower)
    gloss_hits = sum(1 for t in extra_terms if t in name_lower)
    return min(_TYPED_WORD_BOOST * typed_hits, 0.24) + min(_GLOSSARY_WORD_BOOST * gloss_hits, 0.20)


def hybrid_rank(scores: np.ndarray, name_of, top_k: int,
                typed_words: set[str], extra_terms: set[str]) -> list[tuple[float, int]]:
    """混合排序(語意分數 + 字面 boost):回傳 [(final_score, index)] 前 top_k。

    只對語意分數前段的候選做字面 boost(避免全表字面比對);name_of(i) 回傳
    第 i 筆的 symbol 名。production 檢索與 eval_retrieval 共用本函式,
    評測排序不會與線上漂移。
    """
    candidate_idx = np.argsort(scores)[::-1][: max(top_k * 10, 50)]
    rescored = [
        (float(scores[i]) + literal_boost(name_of(int(i)).lower(), typed_words, extra_terms),
         int(i))
        for i in candidate_idx
    ]
    rescored.sort(key=lambda x: x[0], reverse=True)
    return rescored[:top_k]


def search(query: str, top_k: int, extra_terms: set[str], app: AppContext,
           query_vec: np.ndarray | None = None) -> list[SemanticHit]:
    """query_vec 可由呼叫端預先算好傳入(app="all" 跨 AP 查詢時,
    同 model 的 AP 共用一次嵌入);None 則以該 app 索引的 model 現算。"""
    data = _load(app)
    meta, vectors, state = data["meta"], data["vectors"], data["state"]
    if not meta:
        return []

    if query_vec is None:
        query_vec = embed_texts([query], kind="query", model_name=state.get("model"))[0]
    scores = vectors @ query_vec  # 向量已 L2 正規化,內積即 cosine

    typed_words = query_words(query)
    hits: list[SemanticHit] = []
    ranked = hybrid_rank(scores, lambda i: meta[i]["name"], top_k, typed_words, extra_terms)
    for score, i in ranked:
        if score < _MIN_SCORE:
            continue
        m = meta[i]
        hits.append(SemanticHit(
            score=round(score, 4), kind=m["kind"], name=m["name"],
            qualified_name=m["qualified_name"], file_path=m["file_path"],
            start_line=m["start_line"], end_line=m["end_line"],
        ))
    return hits
