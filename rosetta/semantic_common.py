"""語意索引的共用設定:模型載入、embedding 呼叫、索引檔路徑(per-app)。

索引目錄:.semantic/<app>/(kb_config.AppContext.index_dir)。
模型優先序:環境變數 KB_EMBED_MODEL > app.embed_model(kb.config.yaml)> DEFAULT_MODEL。
e5 系列模型需要 query:/passage: 前綴(官方要求),在這裡統一處理。
"""

from dataclasses import dataclass
import os
from pathlib import Path

import numpy as np

from kb_config import AppContext

# 評測(eval/RESULT.md,2026-07-04)定案:e5-large 17/20 最佳(zh 5/5、ja 5/5)。
# 輕量替代:paraphrase-multilingual-MiniLM-L12-v2(16/20,嵌入快 15 倍)。
DEFAULT_MODEL = "intfloat/multilingual-e5-large"

_model_cache: dict[str, object] = {}


@dataclass(frozen=True)
class IndexPaths:
    meta: Path
    vectors: Path
    state: Path

    def all_exist(self) -> bool:
        return self.meta.is_file() and self.vectors.is_file() and self.state.is_file()


def index_paths(app: AppContext) -> IndexPaths:
    return IndexPaths(
        meta=app.index_dir / "meta.jsonl",
        vectors=app.index_dir / "vectors.npy",
        state=app.index_dir / "state.json",
    )


def get_model_name(app: AppContext) -> str:
    return os.environ.get("KB_EMBED_MODEL") or app.embed_model or DEFAULT_MODEL


def _get_model(model_name: str):
    if model_name not in _model_cache:
        from fastembed import TextEmbedding  # import 放函式內:沒裝也不擋非語意功能
        _model_cache[model_name] = TextEmbedding(model_name)
    return _model_cache[model_name]


def _apply_prefix(texts: list[str], kind: str, model_name: str) -> list[str]:
    """e5 系列需要 'query: ' / 'passage: ' 前綴,其他模型不需要。"""
    if "e5" in model_name.lower():
        prefix = "query: " if kind == "query" else "passage: "
        return [prefix + t for t in texts]
    return texts


def embed_texts(texts: list[str], kind: str, model_name: str) -> np.ndarray:
    """回傳 L2 正規化後的向量(cosine 相似度 = 內積)。kind: 'query' | 'passage'。"""
    name = model_name or DEFAULT_MODEL
    model = _get_model(name)
    vectors = np.array(list(model.embed(_apply_prefix(texts, kind, name))), dtype=np.float32)
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return vectors / norms
