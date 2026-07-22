import os                          # 读环境变量
from langchain_openai import ChatOpenAI  # 用 OpenAI 兼容接口接 DeepSeek
from common.config import settings  # 读 llm 配置

def get_llm(temperature=None, max_tokens=None):
    # 构造 DeepSeek 聊天模型；temperature / max_tokens 可覆盖配置
    # 不显式设 max_tokens 会吃到模型默认上限，长答案会被从中间截断 -> 前端“回答不完整”
    l = settings["llm"]
    return ChatOpenAI(
        base_url=l["base_url"],
        api_key=os.environ["LLM_API_KEY"],   # 从 .env 读 key（绝不硬编码）
        model=l["model"],
        temperature=temperature if temperature is not None else l["temperature"],
        max_tokens=max_tokens if max_tokens is not None else l.get("max_tokens", 2048),
    )

def build_answer_prompt(query, contexts, strict=True):
    # 根据检索到的资料段，构造送给 LLM 的提示词；strict 控制约束强度
    # strict=True：强化约束（生产版），严格只依据资料、禁止外部知识补充
    # strict=False：宽松版（基线），资料不足时允许适度结合自身知识补充
    ctx_block = "\n\n".join(
        f"[资料{i+1}]（来源：{c.get('source', '')}）\n{c['text']}" for i, c in enumerate(contexts)
    )
    if strict:
        # 强化约束：严格只依据资料，禁止用外部知识补充，资料缺失就明说没有
        # 引用要求：必须写出具体的文件名（资料括号内的“来源：xxx”），而不是[资料1]这种编号
        return (
            "你是基于个人资料的智能助手，必须严格只依据下面【资料】作答，"
            "绝对禁止使用任何【资料】之外的知识或自身记忆进行补充。\n"
            "规则：\n"
            "1. 若【资料】中能找到答案，基于资料回答并标注引用来源的具体文件名；"
            "引用格式必须是 `[来源：<文件名>]`（例如 `[来源：architecture.md]`），"
            "不要写成 `[资料1]` 这种编号。\n"
            "2. 若【资料】中没有相关信息，必须明确回答“资料中没有相关信息”，不得猜测；\n"
            "3. 不得生成资料未提及的项目、数据或结论。\n\n"
            f"【资料】\n{ctx_block}\n\n用户问题：{query}"
        )
    # 宽松版（基线）：允许资料不足时适度结合自身知识补充，同样要求文件名引用
    return (
        "你是基于个人资料的智能助手，请参考下面【资料】回答用户问题，"
        "资料不足时可结合自身知识适当补充。"
        "引用来源时必须标注具体文件名，格式如 `[来源：<文件名>]`。\n\n"
        f"【资料】\n{ctx_block}\n\n用户问题：{query}"
    )


def generate_answer(query, contexts, temperature=0, strict=True):
    # 根据检索到的资料段生成答案；temperature 默认 0 让回答更稳定、减少编造
    # strict=True：强化约束（生产/优化后版本），严格只依据资料、禁止外部知识补充
    # strict=False：宽松版（基线/优化前版本），资料不足时允许适度结合自身知识补充
    prompt = build_answer_prompt(query, contexts, strict=strict)
    out = get_llm(temperature=temperature).invoke(prompt)
    answer = out.content.strip() if hasattr(out, "content") else str(out)
    sources = [c.get("source", "") for c in contexts]   # 收集来源，返回给前端
    return answer, sources


async def stream_generate_answer(query, contexts, temperature=0, strict=True):
    # 流式版生成：用 ChatOpenAI.astream 逐 token 产出（供 SSE 流式接口调用）
    # 产出的是 token 片段字符串（str），由上层累积成完整答案
    prompt = build_answer_prompt(query, contexts, strict=strict)
    llm = get_llm(temperature=temperature)
    async for chunk in llm.astream(prompt):
        tok = chunk.content if hasattr(chunk, "content") else str(chunk)
        if tok:
            yield tok
