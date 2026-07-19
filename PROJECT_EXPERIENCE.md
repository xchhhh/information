# 项目经历

> 说明：下方「质量数据」中的「优化后」数值为占位，运行 `python -m evaluation.benchmark`
> 拿到真实分数后，将 `{{OPT_FAITHFULNESS}}` 与 `{{IMPROVE_PCT}}` 替换为实测值即可。
> 基线 0.4333 为 2026-07-19 实测（top_k=4 + 原 Prompt + temperature=0.3）。

## 基于 FastAPI + Milvus-Lite 的个人 RAG 知识库问答系统

**角色**：全栈开发工程师（独立开发）
**时间**：2026.06 - 至今

### 项目简介

针对个人作品集 / 简历展示中"信息检索不直观、问答交互体验差"的痛点，独立设计并实现基于 RAG（检索增强生成）的个人知识库问答系统。构建"用户提问 → 查询改写 → 混合检索（向量 + BM25）→ 重排序 → 上下文增强 → LLM 生成"的完整链路，实现对项目经历、技术栈、专业技能等资料的语义检索与智能问答。配套 Web 聊天页与后台管理页，部署于腾讯云服务器供考官直接访问。

### 技术栈

Python、FastAPI、Uvicorn、Milvus-Lite、火山方舟 Doubao Embedding、DeepSeek、RAG、Hybrid Retrieval、Rerank、Semantic Cache、systemd、原生 HTML/CSS/JS

### 职责与产出

- 独立完成后端架构：基于 FastAPI 实现 `/chat` 问答、`/health` 健康检查、后台 `/admin/status`、`/admin/upload`、`/admin/ingest` 共 **6 个 REST 接口**，统一 `X-API-Key` 鉴权与 IP 限流。
- 构建混合检索链路：Milvus-Lite 向量检索 + BM25 关键词检索，经 Rerank 重排序后取 Top-K 拼接上下文，召回更准。
- 实现语义缓存（Semantic Cache），对相似问题复用历史答案，降低重复 Embedding 与 LLM 调用成本。
- 对接火山方舟 Doubao Embedding 与 DeepSeek LLM 完成向量化与答案生成；修复 Doubao 多模态 Embedding 返回结构差异导致的 KeyError。
- 开发后台管理页：系统状态检测、多文件上传（PDF/TXT/Markdown 白名单 + 路径穿越防护）、清空重建 / 追加入库。
- 前端实现 **2 个完整页面**（聊天页 + 后台页），支持浅色 / 深色 / 跟随系统三态主题、玻璃拟态、卡片式对话、磁吸按钮、拖拽上传。
- 完成腾讯云部署与 systemd 常驻服务，通过 Gitee 镜像解决国内服务器 GitHub 直连超时问题，实现稳定更新。
- 搭建 RAGAS 自动评估流水线，对 10 条真实问答对量化答案质量，并以数据驱动检索与生成链路迭代优化。

### 质量数据（RAGAS 实测）

| 指标 | 优化前 | 优化后 | 提升 |
|------|--------|--------|------|
| 答案忠实度 faithfulness | 0.4333 | {{OPT_FAITHFULNESS}} | {{IMPROVE_PCT}} |

> 优化手段：强化"严格仅依据检索资料"的生成约束（temperature 0）、扩大上下文窗口（top-k 4 → 8）。
> 详细说明与可复现命令见 `evaluation_report.md`（运行 `python -m evaluation.benchmark` 自动生成）。
