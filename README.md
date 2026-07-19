# 个人 RAG 知识库（企业级）

把个人资料做成可对话的检索增强生成（RAG）网站。本地开发用 Ollama 向量化 + Milvus + DeepSeek 生成；部署走 GitHub Pages 前端 + 后端 PaaS（milvus-lite + doubao embedding）。
访问地址：http://114.132.53.126:8000/

## 目录结构
```
config/settings.yaml           # 所有参数集中配置（改这里不用改代码）
data/raw/                      # 你的原始资料（md/txt/pdf），先脱敏
data/processed/bm25_corpus.pkl # 入库时自动生成，供稀疏检索用
src/common/config.py           # 读配置 + .env
src/ingestion/                 # 加载/切分/向量化/写 Milvus（入口 run.py）
src/retrieval/                 # 查询改写 + 混合检索(RRF) + 重排
src/llm/client.py              # DeepSeek 生成
src/api/                       # FastAPI 服务（鉴权 + 限流）
src/cache/ src/observability/ src/evaluation/  # 缓存/追踪/评估（默认关闭）
app.py                         # 启动 API 的便捷入口
```

## 前置条件
1. Python 3.10/3.11，已建虚拟环境 `.venv` 并 `pip install -r requirements.txt`。
2. `.env` 里有 `LLM_API_KEY=sk-...`（DeepSeek key）。
3. Docker 已启动，`docker compose up -d` 起了 Milvus（etcd/minio/milvus）。
4. Ollama 已启动且拉好 `mxbai-embed-large`：`ollama pull mxbai-embed-large`。

## 运行步骤
### 1) 入库（把资料写进 Milvus）
```
python src/ingestion/run.py
```
成功会打印 `inserted N chunks`。这会生成 `data/processed/bm25_corpus.pkl`。

### 2) 启动问答 API
```
python app.py
```
打开 http://localhost:8000/docs 可直接试 `/chat`（需要带 `X-API-Key` 头，值见 settings.yaml 的 auth.api_keys）。
或用 curl：
```
curl -X POST http://localhost:8000/chat -H "X-API-Key: change_me" -H "Content-Type: application/json" -d "{\"query\":\"你的姓名是什么？\"}"
```

## 部署提示（乙路线：免费 PaaS）
- `config/settings.yaml` 里 `embedding.provider` 改 `doubao`，`milvus.mode` 改 `lite`，并在 `.env` 配 `ARK_API_KEY`。
- 前端（薄静态页）放 GitHub Pages，后端（FastAPI）部署到 Railway/Render，前端用 HTTPS + API Key 跨域调后端。
- 注意：embedding 入库时原始资料会发往火山引擎，请确保已脱敏。

## 可观测 / 缓存 / 评估（默认关闭）
在 settings.yaml 把 `langfuse.enabled` / `cache.enabled` 打开，并配好对应 key 即可；评估用 `python src/evaluation/ragas_eval.py`（需先解决 ragas 与 langchain 版本兼容）。
