# 技术栈与依赖详解

本项目以"轻量、可单机部署、易维护"为选型原则，技术栈如下。

## 一、后端与 Web 框架

- Python：项目主语言，利用成熟的数据/AI 生态。
- FastAPI：异步 Web 框架，用类型注解定义请求/响应模型，自动生成 OpenAPI 文档；本项目所有接口（/chat、/health、/admin/*）都挂在它上面。
- Uvicorn：ASGI 服务器，负责真正把 FastAPI 应用跑起来、监听端口（生产为 8000）。

## 二、向量与检索相关

- Milvus-Lite：嵌入式向量数据库（详见 vector_db.md）。
- 火山方舟 Doubao Embedding：部署侧使用的 Embedding 模型（doubao-embedding-vision-250615），把文本编码为 1024 维向量；本地开发可用 Ollama 的 mxbai-embed-large 替代，维度一致（1024），Milvus schema 通用。
- BM25：稀疏关键词检索，入库时生成倒排语料。
- BAAI/bge-reranker-v2-m3：跨编码器重排模型，本地加载，对融合候选做精排。

## 三、大模型（LLM）

- DeepSeek（deepseek-chat）：负责最终答案生成，通过 OpenAI 兼容接口（base_url=https://api.deepseek.com）调用。
- 生成约束：temperature 默认 0（生产聊天更稳、减少编造），并强制"严格仅依据检索资料、资料缺失就明说没有"。

## 四、RAG 核心能力

- 混合检索（Hybrid Retrieval）：稠密向量 + BM25 双路。
- Rerank：重排序精排。
- 语义缓存（Semantic Cache）：相似问题复用历史答案，降低重复 Embedding 与 LLM 调用。

## 五、前端

- 原生 HTML / CSS / JavaScript，不依赖任何前端框架，零构建步骤，直接由 FastAPI 同源托管。包含聊天页与后台管理页两个页面。

## 六、部署与运维

- systemd：把服务注册为常驻系统服务（rag.service），开机自启、崩溃重启。
- 腾讯云服务器：生产运行环境，公网 IP + 端口 8000。
- Gitee 镜像：国内服务器直连 GitHub 常超时，改用 Gitee 镜像拉取代码更新。

## 七、配置集中管理

所有"旋钮"（chunk 大小、top_k、融合常数、模型名、密钥环境变量名）集中在 config/settings.yaml，密钥统一从 .env 经 python-dotenv 读取，不写进配置文件，避免泄露。改超参不必动代码。

## 八、依赖隔离

项目使用独立 Python 虚拟环境（.venv），依赖清单 requirements.txt / requirements-deploy.txt 明确列出（含 python-multipart，供 FastAPI 的 UploadFile 使用），保证服务器与本地环境一致。
