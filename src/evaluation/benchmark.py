r"""
RAG 质量基准测试：对比「优化前」与「优化后」的答案忠实度（RAGAS faithfulness）。

- 基线 0.4333 为 2026-07-19 在 top_k=4 + 原 Prompt(temperature=0.3) 下的实测值。
- 本脚本测量「优化后」配置（settings.retrieval.top_k_final + 强化 Prompt + temperature=0），
  输出提升幅度，并生成 evaluation_report.md。

服务器运行方式（务必先停服务释放 milvus_lite.db 锁）：
    systemctl stop rag
    export OPENAI_API_KEY="$(grep -oP '^LLM_API_KEY=\K.*' .env)"
    PYTHONPATH=/root/information/src .venv/bin/python -m evaluation.benchmark
    systemctl start rag
"""
import json
import os

from common.config import BASE_DIR, settings
from retrieval.query_rewrite import rewrite_query
from retrieval.hybrid import HybridRetriever
from llm.client import generate_answer
from ragas import evaluate
from ragas.metrics import faithfulness
from datasets import Dataset
from langchain_openai import ChatOpenAI

# 优化前实测基线（2026-07-19，top_k=4 + 原 Prompt + temperature=0.3）
BASELINE_FAITHFULNESS = 0.4333


def _mean_metric(result, name):
    """从 ragas 评估结果里提取某指标的均值，兼容多种返回结构。

    ragas 不同版本返回形式不一：
      - 新版：result.scores 是「每条样本一个 dict」的列表 -> [{name: x}, ...]
      - 旧版：result 本身像 dict -> {name: x} 或 {name: [x, ...]}
      - 也可通过 result[name] 直接取列（返回序列）
    """
    scores = getattr(result, "scores", None)
    if scores is None:
        scores = result  # 旧版：result 本身就是 dict 形态

    if isinstance(scores, list):
        vals = [s[name] for s in scores if isinstance(s, dict) and name in s]
    elif isinstance(scores, dict):
        v = scores.get(name)
        vals = v if isinstance(v, (list, tuple)) else [v]
    else:
        vals = None

    # 兜底：用 result[name] 直接取列
    if not vals:
        try:
            col = result[name]
            vals = col if isinstance(col, (list, tuple)) else [col]
        except Exception:
            vals = None

    if not vals:
        raise ValueError(f"无法从评估结果中提取指标 {name}")

    # 过滤 nan（LLM 裁判偶发失败的样本，nan != nan 恒为 False）
    clean = [v for v in vals if v == v]
    if not clean:
        raise ValueError(f"指标 {name} 全部为 nan，请检查 LLM 裁判调用是否正常")
    return sum(clean) / len(clean)


def build_rows(top_k):
    """复用项目检索 / 生成链路，收集 RAGAS 需要的样本。"""
    path = os.path.join(BASE_DIR, "tests", "eval_set.json")
    data = json.load(open(path, encoding="utf-8"))
    retriever = HybridRetriever()
    rows = []
    for item in data:
        # 1) 查询改写（失败退回原问题）
        try:
            q = rewrite_query(item["question"])
        except Exception:
            q = item["question"]
        # 2) 混合检索，取优化后的 top_k 段
        top = retriever.retrieve(q)[:top_k]
        contexts = [c["text"] for c in top]
        # 3) 用强化 Prompt + temperature=0 生成答案
        text, _ = generate_answer(item["question"], top)
        rows.append({
            "question": item["question"],
            "answer": text,
            "contexts": contexts,
            "reference": item.get("reference", ""),
        })
    return rows


def main():
    # 给 RAGAS 的裁判模型挂上 DeepSeek（端点明确支持的模型名，替代默认 gpt-4o-mini）
    judge = ChatOpenAI(
        base_url=settings["llm"]["base_url"],   # https://api.deepseek.com
        api_key=os.environ["OPENAI_API_KEY"],
        model="deepseek-v4-flash",
        temperature=0,
    )
    faithfulness.llm = judge

    top_k = settings["retrieval"]["top_k_final"]   # 优化后的上下文窗口大小
    rows = build_rows(top_k)
    print(f"评估样本数: {len(rows)}（来自 tests/eval_set.json）")
    result = evaluate(Dataset.from_list(rows), metrics=[faithfulness])

    # 兼容 ragas 不同版本的结果结构：提取 faithfulness 的均值
    optimized = _mean_metric(result, "faithfulness")

    improve = (optimized - BASELINE_FAITHFULNESS) / BASELINE_FAITHFULNESS * 100

    print(f"基线 faithfulness  : {BASELINE_FAITHFULNESS:.4f}")
    print(f"优化后 faithfulness: {optimized:.4f}")
    print(f"提升: {improve:+.1f}%")

    # 生成可读报告
    report = (
        "# RAG 质量基准报告\n\n"
        f"- 评估集: tests/eval_set.json（{len(rows)} 条问答对）\n"
        "- 指标: RAGAS faithfulness（答案忠实度，0~1 越高越好）\n"
        "- 裁判模型: DeepSeek (deepseek-v4-flash)\n\n"
        "| 配置 | top_k | Prompt | temperature | faithfulness |\n"
        "|------|-------|--------|-------------|--------------|\n"
        f"| 优化前（基线） | 4 | 原版（允许补充） | 0.3 | {BASELINE_FAITHFULNESS:.4f} |\n"
        f"| 优化后 | {top_k} | 强化（严格仅依据资料） | 0 | {optimized:.4f} |\n\n"
        f"**提升: {improve:+.1f}%**\n"
    )
    out_path = os.path.join(BASE_DIR, "evaluation_report.md")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(report)
    print("报告已写入", out_path)


if __name__ == "__main__":
    main()
