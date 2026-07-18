# 个人 RAG 项目 · 代码审查清单

> 审查范围：全部 `src/**/*.py`、前端 `frontend/index.html`、配置与部署文件
> 结论：业务代码注释已较完整；主要问题是「写了没接」的功能缺口 + 少量空文件缺注释。

---

## 一、注释覆盖情况

✅ **已覆盖（很好）**：`loaders / chunking / embed / milvus_client / run / query_rewrite / hybrid / rerank / rag / llm/client / api/{auth,rate_limit,server} / cache / observability / evaluation` 全部有逐行中文注释；前端 `index.html` 也已逐行注释。

💭 **待补注释**（已复核：此项不成立）：
- 复核后发现 7 个包的 `__init__.py` **全部已有一行 docstring**（api/common/ingestion/retrieval/llm/cache/evaluation 均含说明）。此前审查误判，特此更正——注释覆盖无需再补。

---

## 二、功能缺口（按优先级）

### 🔴 评估脚本是占位，并没有真正计算指标
- 文件：`src/evaluation/ragas_eval.py`（第 29 行、第 32 行）
- 问题：
  - 第 29 行 `contexts: [c["text"] for c in []] or ["（此处接 retrieve 结果）"]` —— 这个推导永远为空，所以 **contexts 永远是用占位字符串**。
  - `run()` 全程从不调用 `evaluate(...)`，只 `print` 一句提示。
  - 而 RAGAS 的 `faithfulness / answer_relevancy` **必须喂入真实的检索上下文**才能算，否则结果毫无意义。
- 建议：在评估时真正调用检索拿到 contexts 传入，并调用 `evaluate()` 输出分数。

### 🟡 语义缓存写了，但没接入主流程（死代码）
- 文件：`src/rag.py` 的 `answer()` 从未调用 `cache.get / cache.put`
- 问题：即便 `settings.yaml` 里 `cache.enabled=true`，也完全不生效。
- 建议：`answer()` 开头先 `cache.get(query)`，命中直接返回；生成答案后 `cache.put(query, answer)`。

### 🟡 可观测 tracing 写了，但没接入
- 文件：`src/observability/tracing.py` 的 `trace_step` 装饰器**从未被使用**
- 问题：开启 `langfuse.enabled=true` 也不会产生任何追踪数据。
- 建议：在 `rag.py` 各步骤（改写/检索/重排/生成）上加 `@trace_step`，或文档明确标注「可选、尚未接入」。

### 🟡 部署配置缺失（乙路线还没真正能上线）
- README 写了「GitHub Pages + 免费 PaaS」的思路，但仓库里**没有可落地的部署文件**：
  - 后端 PaaS 启动配置：`Procfile` / `runtime.txt`（告诉 PaaS 用哪个 Python、怎么起 `uvicorn app:app`）
  - 前端 GitHub Pages 的 CI：`.github/workflows/deploy.yml`（把 `frontend/` 推到 Pages）
  - 部署用精简 `requirements.txt`（部署后端不需要 `gptcache / langfuse / ragas`，会拖慢构建甚至装不上）

### 💭 其他建议
- **`requirements.txt` 未锁版本**，且含部署用不上的包（曾导致 `tokenizers/transformers` 冲突）。建议生产环境 `pip freeze` 锁版本；部署子集剔除 `gptcache/langfuse/ragas`。
- **缺 `.env.example`**：协作/部署时别人不知道要填 `LLM_API_KEY=`、`ARK_API_KEY=` 等哪些变量。
- **无自动化测试**：仅有 `tests/eval_set.json` 评估集，没有 pytest 单测（如 `chunking`、`hybrid` 检索逻辑）。企业级项目建议补。
- **前端无后端在线/离线状态指示**：目前只在出错时气泡提示，可作为可选增强。

---

## 三、建议的下一步（按性价比排序）

1. **修评估脚本**（🔴，让 `ragas_eval.py` 真算分）—— 最有价值。
2. **把缓存、tracing 接入 `rag.py`**（🟡，各几行代码，让「企业级」名副其实）。
3. **补部署三件套**（🟡，只有要公网链接才需要）。
4. **给 6 个空 `__init__.py` 加一行 docstring**（💭，顺手）。

> 注：所有「业务代码」注释已达标，无需返工。

---

## 四、已修复记录（2026-07-18）

以下项已实际动手修复，并通过导入冒烟测试（`import rag` / `import ragas_eval` 均正常）：

- 🔴 **ragas_eval.py**：改为走真实检索链路取 `contexts`，并真正调用 `evaluate()` 输出 faithfulness / answer_relevancy 分数；移除占位串与只 print 的假逻辑。
- 🟡 **semantic_cache.py + rag.py**：缓存改为存/取 `{"answer", "sources"}`；`rag.answer()` 开头查缓存命中即返回、生成后回写，并加 `@trace_step("answer")` 装饰器——`cache.enabled` / `langfuse.enabled` 现在真正生效。
- 🟡 **部署文件补齐**：新增 `Procfile`（uvicorn 启动）、`runtime.txt`（python-3.12）、`requirements-deploy.txt`（剔除 gptcache/langfuse/ragas 的部署子集）、`.github/workflows/deploy-pages.yml`（把 frontend/ 推到 GitHub Pages）、`.env.example`（列出所需变量）。
- ✅ 复核更正：7 个包 `__init__.py` 其实均已有一行 docstring，原“空文件缺注释”误判，已划掉。

> 仍未做（按需）：`requirements.txt` 锁版本、pytest 单测、前端后端在线状态指示。
