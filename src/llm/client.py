import os                          # 读环境变量
from langchain_openai import ChatOpenAI  # 用 OpenAI 兼容接口接 DeepSeek
from common.config import settings  # 读 llm 配置

def get_llm():
    # 构造 DeepSeek 聊天模型
    l = settings["llm"]
    return ChatOpenAI(
        base_url=l["base_url"],
        api_key=os.environ["LLM_API_KEY"],   # 从 .env 读 key（绝不硬编码）
        model=l["model"],
        temperature=l["temperature"],
    )

def generate_answer(query, contexts):
    # 根据检索到的资料段，让 LLM 生成答案，并强制标注来源、限制只依据资料
    ctx_block = "\n\n".join(
        f"[资料{i+1}]（来源：{c.get('source', '')}）\n{c['text']}" for i, c in enumerate(contexts)
    )
    prompt = (
        "你是基于个人资料的智能助手。只根据下面提供的【资料】回答问题，"
        "如果资料里没有答案，就如实说“资料中没有相关信息”。\n"
        "回答时尽量标注引用来源（资料编号）。\n\n"
        f"{ctx_block}\n\n用户问题：{query}"
    )
    out = get_llm().invoke(prompt)
    answer = out.content.strip() if hasattr(out, "content") else str(out)
    sources = [c.get("source", "") for c in contexts]   # 收集来源，返回给前端
    return answer, sources
