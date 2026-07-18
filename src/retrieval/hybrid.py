import os            # 路径处理
import re            # 正则，做中文分词
import pickle        # 读取 BM25 语料
from rank_bm25 import BM25Okapi   # 稀疏检索（关键词匹配）
from common.config import BASE_DIR, settings  # 项目根、配置
from ingestion.embed import get_embedder     # 同一套 embedding（查询要用和入库一致的模型）

def _tokenize(text):
    # 中文按“字”、英文/数字按“词”切，简单但对中文 BM25 够用（无需额外装分词库）
    return re.findall(r"[a-zA-Z0-9]+|[\u4e00-\u9fff]", text)

def _entity(item):
    # pymilvus 不同版本把字段放在 item["entity"] 或平铺，这里统一取出
    return item.get("entity", item)

class HybridRetriever:
    # 混合检索：稠密向量（Milvus）+ 稀疏 BM25 -> RRF 倒数排名融合
    def __init__(self):
        self.embedder = get_embedder()    # 查询用的 embedder（必须和入库一致）
        # 加载入库时生成的 BM25 语料
        path = os.path.join(BASE_DIR, "data", "processed", "bm25_corpus.pkl")
        if not os.path.exists(path):
            raise FileNotFoundError("未找到 BM25 语料，请先运行 python src/ingestion/run.py 完成入库")
        with open(path, "rb") as f:
            self.corpus = pickle.load(f)          # list of {chunk_id, text, source}
        self.texts = [c["text"] for c in self.corpus]
        self.bm25 = BM25Okapi([_tokenize(t) for t in self.texts])  # 建 BM25 索引

    def retrieve(self, query):
        r = settings["retrieval"]
        k = r["top_k_retrieve"]                    # 每路先召回前 20
        # 1) 稠密检索：query 向量化后去 Milvus 搜
        qvec = self.embedder.embed_query(query)
        from ingestion.milvus_client import get_client, ensure_collection
        client = get_client(); ensure_collection(client)
        dense_hits = client.search(
            collection_name=settings["milvus"]["collection"],
            data=[qvec], limit=k,
            output_fields=["text", "source", "chunk_id"],
        )[0]                                       # search 返回 [[hit,...]]，取第一组
        # 记录每个 chunk 的稠密排名
        dense_rank = {}
        for i, hit in enumerate(dense_hits):
            ent = _entity(hit)
            dense_rank[ent["chunk_id"]] = i + 1
        # 2) 稀疏检索：BM25 打分，取前 k
        bm25_scores = self.bm25.get_scores(_tokenize(query))
        bm25_order = sorted(range(len(self.texts)), key=lambda i: bm25_scores[i], reverse=True)[:k]
        bm25_rank = {self.corpus[i]["chunk_id"]: rank + 1 for rank, i in enumerate(bm25_order)}
        # 3) RRF 融合：score = Σ 1/(k + rank)
        fused = {}
        for cid in set(dense_rank) | set(bm25_rank):
            s = 0.0
            if cid in dense_rank: s += 1.0 / (r["rrf_k"] + dense_rank[cid])
            if cid in bm25_rank: s += 1.0 / (r["rrf_k"] + bm25_rank[cid])
            fused[cid] = s
        # 按融合分排序，取前 k 个候选
        ranked = sorted(fused, key=lambda c: fused[c], reverse=True)
        cid2meta = {c["chunk_id"]: c for c in self.corpus}
        return [cid2meta[c] for c in ranked[:k]]   # 返回融合后的候选段（含 text/source/chunk_id）
