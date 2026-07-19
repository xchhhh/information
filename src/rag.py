from retrieval.query_rewrite import rewrite_query  # 查询改写
from retrieval.hybrid import HybridRetriever        # 混合检索
from retrieval.rerank import rerank                  # 重排
from llm.client import generate_answer               # 调用 LLM 生成答案
from cache.semantic_cache import get as cache_get, put as cache_put  # 语义缓存（接入主流程）
from observability.tracing import trace_step         # 可观测追踪装饰器（接入主流程）

_retriever = None   # 检索器只创建一次（含 BM25 索引加载）

def _get_retriever():
    global _retriever
    if _retriever is None:
        _retriever = HybridRetriever()
    return _retriever

def reset_retriever():
    # 入库（/admin/ingest）成功后调用：清空检索单例，
    # 下次 /chat 会用最新 bm25_corpus.pkl 自动重建，避免内存索引与 Milvus 不一致导致 500
    global _retriever
    _retriever = None

@trace_step("answer")   # 给整段问答打追踪点：settings 里 langfuse.enabled=true 时，可在 Langfuse 看到这次调用
def answer(query):
    # 企业级问答主线：缓存 -> 改写 -> 混合检索 -> 重排 -> 生成

    # 0) 先查语义缓存：相似问题直接命中就返回，省去后面整条检索+生成链路（cache.enabled=true 才生效）
    cached = cache_get(query)
    if cached is not None:
        return {"answer": cached["answer"], "sources": cached["sources"], "cached": True}

    try:
        rewritten = rewrite_query(query)   # 1) 改写（失败就退回原问题，保证可用）
    except Exception:
        rewritten = query
    candidates = _get_retriever().retrieve(rewritten)   # 2) 混合检索召回候选
    top = rerank(query, candidates)                     # 3) 重排取最相关 top_k
    text, sources = generate_answer(query, top)         # 4) 拼上下文让 LLM 回答
    cache_put(query, text, sources)                     # 5) 回写缓存，供后续相似问题命中
    return {"answer": text, "sources": sources}         # 返回答案 + 引用来源
