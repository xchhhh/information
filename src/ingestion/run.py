import os            # 路径处理
import sys           # 修改模块搜索路径
import pickle        # 把 BM25 语料存成文件
# 把 src 加入模块搜索路径，这样无论从哪运行都能 import common / ingestion
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from common.config import BASE_DIR, settings      # 项目根、全局配置
from ingestion.milvus_client import get_client, ensure_collection, insert_chunks  # Milvus 连接/建表/写入
from ingestion.loaders import load_documents       # 加载原始资料
from ingestion.chunking import chunk_documents     # 切分
from ingestion.embed import get_embedder           # 向量化（Ollama / doubao）

def main():
    client = get_client()              # 第1步：连 Milvus
    ensure_collection(client)          # 第2步：确保集合已建
    chunks = chunk_documents(load_documents())   # 第3步：加载并切分资料
    emb = get_embedder()               # 第4步：取 embedding 后端
    texts = [c.page_content for c in chunks]      # 第5步：抽出每段原文
    vectors = emb.embed_documents(texts)          # 第6步：文本 -> 1024 维向量
    n = insert_chunks(client, chunks, vectors)    # 第7步：写入 Milvus
    # 第8步：把“原文 + 来源 + chunk_id”存成 BM25 语料，供检索阶段的稀疏检索用
    corpus = [{"chunk_id": c.metadata.get("chunk_id", ""),
               "text": c.page_content,
               "source": c.metadata.get("source", "")} for c in chunks]
    out = os.path.join(BASE_DIR, "data", "processed", "bm25_corpus.pkl")
    os.makedirs(os.path.dirname(out), exist_ok=True)   # 确保 processed 目录存在
    with open(out, "wb") as f:
        pickle.dump(corpus, f)
    print(f"inserted {n} chunks; BM25 corpus saved to {out}")  # 成功提示

if __name__ == "__main__":
    main()   # 直接运行本文件时执行入库
