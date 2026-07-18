import numpy as np                 # 向量运算
from common.config import settings  # 读 cache 配置
from ingestion.embed import get_embedder  # 用同一套 embedding 算查询向量

_enabled = None   # 缓存是否启用（懒读配置）
_store = []       # 内存缓存：[(查询向量, 答案), ...]
_embedder = None  # embedding 后端（懒加载）

def _is_enabled():
    global _enabled
    if _enabled is None:
        _enabled = settings.get("cache", {}).get("enabled", False)
    return _enabled

def _get_embedder():
    global _embedder
    if _embedder is None:
        _embedder = get_embedder()
    return _embedder

def get(query):
    # 查缓存：相似度超过阈值就直接返回历史答案（连同当时的来源）
    if not _is_enabled():
        return None
    qv = np.array(_get_embedder().embed_query(query))
    thr = settings["cache"]["similarity"]
    for vec, item in _store:
        # 余弦相似度 = 两向量点积 / 各自模长（加 1e-9 防除零）
        sim = np.dot(qv, vec) / (np.linalg.norm(qv) * np.linalg.norm(vec) + 1e-9)
        if sim >= thr:
            return item          # item 结构：{"answer": ..., "sources": [...]}
    return None

def put(query, answer, sources=None):
    # 写缓存：连同来源一起存，下次命中时前端也能展示引用
    if not _is_enabled():
        return
    qv = np.array(_get_embedder().embed_query(query))
    _store.append((qv, {"answer": answer, "sources": sources or []}))
