import os                          # 读环境变量
from langchain_openai import ChatOpenAI  # 用 OpenAI 兼容接口接 DeepSeek
from common.config import settings  # 读 llm 配置

def _get_llm():
    # 构造 DeepSeek 的聊天模型（通过 OpenAI 兼容接口）
    l = settings["llm"]
    return ChatOpenAI(
        base_url=l["base_url"],          # https://api.deepseek.com
        api_key=os.environ["LLM_API_KEY"],  # 从环境变量读 key
        model=l["model"],                # deepseek-chat
        temperature=l["temperature"],
    )

def rewrite_query(query):
    # 查询改写：把口语化问题改写成更适合向量检索的查询语句（企业级检索提质的一步）
    prompt = (
        "你是一个检索助手。把用户的问题改写成一段适合向量数据库检索的查询语句，"
        "保留关键信息、去掉寒暄。只输出改写后的查询，不要任何解释。\n"
        f"原问题：{query}"
    )
    out = _get_llm().invoke(prompt)            # 调 DeepSeek 改写
    return out.content.strip() if hasattr(out, "content") else str(out)
