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
    _BM25_PATH = os.path.join(BASE_DIR, "data", "processed", "bm25_corpus.pkl")

    def __init__(self):
        self.embedder = get_embedder()    # 查询用的 embedder（必须和入库一致）
        self._mtime = None                # 记录 BM25 语料文件的修改时间，用于检测入库后变更
        self._load_corpus()               # 首次加载语料 + 构建 BM25 索引

    def _load_corpus(self):
        # 从入库生成的 pickle 载入语料，并重建 BM25 索引
        if not os.path.exists(self._BM25_PATH):
            raise FileNotFoundError("未找到 BM25 语料，请先运行 python src/ingestion/run.py 完成入库")
        self._mtime = os.path.getmtime(self._BM25_PATH)   # 记下当前修改时间
        with open(self._BM25_PATH, "rb") as f:
            self.corpus = pickle.load(f)          # list of {chunk_id, text, source}
        self.texts = [c["text"] for c in self.corpus]
        self.bm25 = BM25Okapi([_tokenize(t) for t in self.texts])  # 建 BM25 索引

    def _ensure_fresh(self):
        # 关键修复：入库（/admin/ingest）会更新 bm25_corpus.pkl 并写入新 chunk_id，
        # 若不刷新内存中的索引，会与 Milvus 中新的向量不一致、检索时 KeyError -> 导致 /chat 返回 500。
        # 这里每次检索前比对文件修改时间，若已被入库更新则自动重载，保证内存索引与向量库一致。
        try:
            mtime = os.path.getmtime(self._BM25_PATH)
        except OSError:
            return   # 文件暂不存在（入库进行中）就维持现状，下一请求再试
        if mtime != self._mtime:
            self._load_corpus()

    def retrieve(self, query):
        self._ensure_fresh()              # 检索前确保语料是最新入库的版本
        r = settings["retrieval"]
        k = r["top_k_retrieve"]                    # 每路先召回前 20
        # 1) 稠密检索：query 向量化后去 Milvus 搜
        qvec = self.embedder.embed_query(query)
        from ingestion.milvus_client import get_client, ensure_collection
        client = get_client(); ensure_collection(client)
        client.load_collection(collection_name=settings["milvus"]["collection"])  # milvus-lite 必须先 load 才能 search
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
        # 防御：仅保留内存语料中确实存在、且与 Milvus 命中一致的块，避免极少见的时序错位导致 KeyError
        return [m for m in (cid2meta.get(c) for c in ranked[:k]) if m is not None]
