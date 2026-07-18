import os            # 路径
import json          # 读评估集
from common.config import BASE_DIR, settings  # 项目根、全局配置

def load_eval_set():
    # 读取评估问答对（tests/eval_set.json）
    path = os.path.join(BASE_DIR, "tests", "eval_set.json")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def run():
    # 离线评估：对评估集逐条走“真实检索 + 生成”，把真实上下文喂给 RAGAS 算指标
    # ragas 与部分 langchain 版本存在兼容问题，这里懒加载，失败给提示不崩溃
    try:
        from ragas import evaluate                  # RAGAS 主评估函数
        from ragas.metrics import faithfulness, answer_relevancy  # 两个核心指标
        from datasets import Dataset                # RAGAS 需要的样本容器
    except Exception as e:
        print("ragas 导入失败（与 langchain 版本不兼容）：", e)
        print("可单独执行：pip install \"langchain-community==0.2.13\" \"datasets\" 后再跑本脚本。")
        return

    # 直接复用检索与生成链路，拿到“真实检索上下文”，这是 RAGAS 算分的前提
    from retrieval.query_rewrite import rewrite_query
    from retrieval.hybrid import HybridRetriever
    from llm.client import generate_answer

    retriever = HybridRetriever()                    # 复用已建好的混合检索器
    top_k = settings["retrieval"]["top_k_final"]     # 与线上一致：取重排后的前 N 段
    data = load_eval_set()
    rows = []                                        # 收集成 RAGAS 需要的行
    for item in data:
        q = item["question"]
        try:
            rewritten = rewrite_query(q)             # 1) 查询改写（失败退回原问题）
        except Exception:
            rewritten = q
        candidates = retriever.retrieve(rewritten)   # 2) 混合检索
        top = candidates[:top_k]                     # 3) 取线上实际送进 LLM 的那几段
        contexts = [c["text"] for c in top]          # 真实上下文（关键！之前是占位串）
        text, _ = generate_answer(q, top)            # 4) 生成答案
        rows.append({
            "question": q,
            "answer": text,
            "contexts": contexts,                    # 真实上下文列表，供 faithfulness 校验
            "reference": item.get("reference", ""),  # 参考答案，供后续人工/指标比对
        })

    # 组织成 RAGAS 的 Dataset 并真正计算指标
    dataset = Dataset.from_list(rows)
    result = evaluate(dataset, metrics=[faithfulness, answer_relevancy])
    print("评估结果：")
    print(result)                                    # 输出 faithfulness / answer_relevancy 分数

if __name__ == "__main__":
    run()
