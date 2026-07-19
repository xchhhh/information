import os                          # 读环境变量
from langchain_openai import ChatOpenAI  # 用 OpenAI 兼容接口接 DeepSeek
from common.config import settings  # 读 llm 配置

def get_llm(temperature=None):
    # 构造 DeepSeek 聊天模型；temperature 可覆盖配置（严谨/评估场景传 0 更稳）
    l = settings["llm"]
    return ChatOpenAI(
        base_url=l["base_url"],
        api_key=os.environ["LLM_API_KEY"],   # 从 .env 读 key（绝不硬编码）
        model=l["model"],
        temperature=temperature if temperature is not None else l["temperature"],
    )

def generate_answer(query, contexts, temperature=0):
    # 根据检索到的资料段生成答案；temperature 默认 0 让回答更稳定、减少编造
    ctx_block = "\n\n".join(
        f"[资料{i+1}]（来源：{c.get('source', '')}）\n{c['text']}" for i, c in enumerate(contexts)
    )
    # 强化约束：严格只依据资料，禁止用外部知识补充，资料缺失就明说没有
    prompt = (
        "你是基于个人资料的智能助手，必须严格只依据下面【资料】作答，"
        "绝对禁止使用任何【资料】之外的知识或自身记忆进行补充。\n"
        "规则：\n"
        "1. 若【资料】中能找到答案，基于资料回答并标注引用来源（资料编号）；\n"
        "2. 若【资料】中没有相关信息，必须明确回答“资料中没有相关信息”，不得猜测；\n"
        "3. 不得生成资料未提及的项目、数据或结论。\n\n"
        f"【资料】\n{ctx_block}\n\n用户问题：{query}"
    )
    out = get_llm(temperature=temperature).invoke(prompt)
    answer = out.content.strip() if hasattr(out, "content") else str(out)
    sources = [c.get("source", "") for c in contexts]   # 收集来源，返回给前端
    return answer, sources
