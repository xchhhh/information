from common.config import settings  # 读 reranker 模型名

_model = None        # 模型对象（加载成功后）
_model_failed = False  # 模型是否加载失败（失败则跳过重排，保证链路可用）

def _get_model():
    # 懒加载重排模型；若加载失败（未装 sentence-transformers / 模型未下载 / 无网络），标记失败并返回 None
    global _model, _model_failed
    if _model is not None or _model_failed:
        return _model
    try:
        # 惰性导入：部署环境不装 sentence-transformers 时也能正常启动（仅跳过重排）
        from sentence_transformers import CrossEncoder
        _model = CrossEncoder(settings["reranker"]["model"])  # BAAI/bge-reranker-v2-m3
    except Exception as e:
        _model_failed = True
        print(f"[警告] 重排模型加载失败，已跳过重排（检索结果按融合排序返回）：{e}")
    return _model

def rerank(query, candidates, top_k=None):
    # 对检索召回的候选段用重排模型重新打分，取最相关的 top_k
    top_k = top_k or settings["retrieval"]["top_k_final"]   # 默认取前 4
    model = _get_model()
    if model is None:
        # 模型不可用：直接返回融合排序后的前 top_k（由混合检索的 RRF 分决定顺序）
        return candidates[:top_k]
    if not candidates:
        return []
    pairs = [(query, c["text"]) for c in candidates]        # 构造 (问题, 段落) 对
    scores = model.predict(pairs)                           # 模型给出相关性分数
    for c, s in zip(candidates, scores):
        c["rerank_score"] = float(s)                       # 把分数挂回候选
    ranked = sorted(candidates, key=lambda c: c["rerank_score"], reverse=True)
    return ranked[:top_k]                                  # 返回重排后的前 top_k 段
