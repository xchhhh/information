# src/orchestrator.py
# 多智能体编排：Orchestrator 总控模式
# 复杂问题 -> Planner 拆解子问题 -> 多个子 Agent 并行检索+生成 -> Synthesizer 汇总
# 设计原则：子 Agent 直接复用现有单链路 answer()，零重复代码；失败优雅降级。
import asyncio
import json
import re
from llm.client import get_llm             # 构造 DeepSeek 客户端
from rag import answer as single_answer, stream_answer as stream_single_answer  # 复用现有单链路（含流式版）
from common.config import settings         # 读 orchestrator 配置


def _planner_prompt(query, max_n):
    # Planner（主 Agent）的职责：把复杂问题拆成可独立检索回答的子问题
    return (
        "你是一个任务拆解器。请把用户的问题拆解成若干个可以独立检索资料来回答的子问题，"
        "这些子问题合起来要完整覆盖原问题的不同侧面，避免重复。\n"
        f"最多拆成 {max_n} 个子问题。\n"
        "只输出一个 JSON 数组，例如：[\"子问题1\", \"子问题2\"]，不要输出任何额外说明文字。\n\n"
        f"用户原问题：{query}"
    )


def _synthesize_prompt(query, sub_qa):
    # Synthesizer（汇总 Agent）的职责：把子答案综合成针对原问题的完整答案
    parts = [f"【子问题{i}】{q}\n回答：{a}" for i, (q, a) in enumerate(sub_qa, 1)]
    block = "\n\n".join(parts)
    return (
        "你是答案汇总器。下面是针对一个复杂问题拆解出的若干子问题及其回答，"
        "请你综合这些回答，给出针对【原始问题】的完整、连贯的最终答案。\n"
        "要求：\n"
        "1. 必须基于子回答中的事实，不要引入子回答之外的猜测；\n"
        "2. 引用资料时必须标注具体文件名，格式为 `[来源：<文件名>]`；\n"
        "3. 去除重复内容，组织成结构清晰的段落；\n"
        "4. 若子回答之间存在冲突，请指出并说明。\n\n"
        f"【原始问题】{query}\n\n"
        f"【子问题及回答】\n{block}\n\n"
        "请给出最终答案："
    )


def _parse_subqueries(raw, max_n):
    # 从 LLM 输出里尽量解析出 JSON 数组，做清洗与上限截断（容错）
    try:
        s = raw.strip()
        if s.startswith("```"):                 # 剥掉 ```json ... ``` 围栏
            s = re.sub(r"^```[a-zA-Z]*\n?", "", s)
            s = re.sub(r"\n?```$", "", s)
        arr = json.loads(s)
        if isinstance(arr, list):
            items = [str(x).strip() for x in arr if str(x).strip()]
            return items[:max_n]
    except Exception:
        pass
    return []


def planner_decompose(query, max_n):
    # 调 LLM 把问题拆成子问题列表；任何失败都返回空列表（上层退回单链路，保证可用）
    try:
        llm = get_llm(temperature=0)
        raw = llm.invoke(_planner_prompt(query, max_n)).content
        return _parse_subqueries(raw, max_n)
    except Exception:
        return []


def synthesize(query, sub_qa):
    # 汇总子答案；LLM 调用失败则用规则拼接兜底（不依赖外部，保证一定有答案）
    try:
        llm = get_llm(temperature=0)
        return llm.invoke(_synthesize_prompt(query, sub_qa)).content.strip()
    except Exception:
        return "\n\n".join(f"· {q}\n{a}" for q, a in sub_qa)


async def orchestrate(query):
    # 主编排入口：拆解 -> 并行子 Agent -> 汇总 -> 降级
    cfg = settings.get("orchestrator", {})
    max_n = cfg.get("max_sub_queries", 3)
    timeout = cfg.get("timeout", 30)

    subs = planner_decompose(query, max_n)
    if not subs:
        # 拆解失败或 LLM 认为无需拆解 -> 退回单链路
        return single_answer(query)

    # 并行跑每个子问题：每个子 Agent 复用 answer()（含改写+混合检索+重排+生成）
    # answer 是同步函数（内部 milvus 同步调用），用 to_thread 丢进线程池并发，避免阻塞事件循环
    async def run_one(sub):
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(single_answer, sub),
                timeout=timeout,
            )
        except Exception:
            return None   # 单个子问题失败不影响其他子问题

    results = await asyncio.gather(*[run_one(s) for s in subs])
    valid = [(s, r) for s, r in zip(subs, results) if r is not None]

    if not valid:
        # 所有子问题都失败 -> 退回单链路
        return single_answer(query)

    # 汇总阶段
    sub_qa = [(s, r["answer"]) for s, r in valid]
    final_text = synthesize(query, sub_qa)

    # 去重来源（多个子问题可能命中同一文件）
    sources = []
    for _, r in valid:
        for src in r.get("sources", []):
            if src and src not in sources:
                sources.append(src)

    return {
        "answer": final_text,
        "sources": sources,
        "sub_queries": subs,      # 透传给前端，可展示“已拆为 N 个子问题”的思维链
    }


async def stream_orchestrate(query):
    # 流式版编排：供 /chat 的 SSE 接口调用。
    # 流程：Planner 拆解（整段）-> 先发 sub_queries 思维链 -> 并行子 Agent（整段）-> Synthesizer 流式汇总。
    cfg = settings.get("orchestrator", {})
    max_n = cfg.get("max_sub_queries", 3)
    timeout = cfg.get("timeout", 30)

    subs = await asyncio.to_thread(planner_decompose, query, max_n)
    if not subs:
        # 拆解失败或 LLM 认为无需拆解 -> 退回单链路流式
        async for c in stream_single_answer(query):
            yield c
        return

    # 先把拆解出的子问题发给前端（思维链可视化，用户能看到“正在分而治之”）
    yield {"type": "sub_queries", "data": subs}

    # 并行跑每个子问题：复用单链路 answer()（含改写+混合检索+重排+生成），整段返回供汇总
    async def run_one(sub):
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(single_answer, sub),
                timeout=timeout,
            )
        except Exception:
            return None   # 单个子问题失败不影响其他子问题

    results = await asyncio.gather(*[run_one(s) for s in subs])
    valid = [(s, r) for s, r in zip(subs, results) if r is not None]

    if not valid:
        # 所有子问题都失败 -> 退回单链路流式
        async for c in stream_single_answer(query):
            yield c
        return

    # 汇总阶段：子答案先收集，Synthesizer 用流式输出最终答案（用户能看到逐字汇总）
    sub_qa = [(s, r["answer"]) for s, r in valid]
    sources = []
    for _, r in valid:
        for src in r.get("sources", []):
            if src and src not in sources:
                sources.append(src)

    llm = get_llm(temperature=0)
    full = []
    async for chunk in llm.astream(_synthesize_prompt(query, sub_qa)):
        tok = chunk.content if hasattr(chunk, "content") else str(chunk)
        if tok:
            full.append(tok)
            yield {"type": "delta", "data": tok}
    yield {"type": "sources", "data": sources}
