import os              # 读环境变量
import requests         # 调 doubao 云端 embedding 的 HTTP 请求
from common.config import settings  # 读 embedding 配置
# 说明：OllamaEmbeddings 改为惰性导入（见 get_embedder），部署环境未装 langchain-ollama 时也能启动

class DoubaoEmbeddings:
    # 火山方舟 doubao 多模态 embedding 的 LangChain 兼容封装（这里只用纯文本模式）
    def __init__(self, model, base_url, api_key, dimensions=1024):
        self.model = model
        self.base_url = base_url.rstrip("/")   # 去掉结尾斜杠，避免拼 URL 出错
        self.api_key = api_key
        self.dimensions = dimensions            # 显式 1024，和本地 Ollama 对齐

    def _embed_one(self, text):
        # 调 /embeddings/multimodal 端点，纯文本时 input 用 type=text
        resp = requests.post(
            f"{self.base_url}/embeddings/multimodal",
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            json={"model": self.model,
                  "input": [{"type": "text", "text": text}],
                  "dimensions": self.dimensions,
                  "encoding_format": "float"},
            timeout=30,
        )
        resp.raise_for_status()                 # 非 200 直接抛错
        return resp.json()["data"][0]["embedding"]  # 取回向量（列表）

    def embed_documents(self, texts):
        return [self._embed_one(t) for t in texts]   # 批量向量化（入库用）

    def embed_query(self, text):
        return self._embed_one(text)                # 单条向量化（查询用）

def get_embedder():
    # 根据配置选择 embedding 后端；返回对象都提供 embed_documents / embed_query 两个方法
    e = settings["embedding"]
    if e.get("provider") == "doubao":       # 部署到云端走 doubao
        d = e["doubao"]
        return DoubaoEmbeddings(
            model=d["model"],
            base_url=d["base_url"],
            api_key=os.environ[d["api_key_env"]],   # 密钥从环境变量读
            dimensions=d["dimensions"],
        )
    # 默认（本地开发）走 Ollama；惰性导入避免部署环境未装 langchain-ollama 时崩溃
    from langchain_ollama import OllamaEmbeddings
    return OllamaEmbeddings(model=e["model"], base_url=e["base_url"])
