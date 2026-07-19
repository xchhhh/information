r"""
RAG 质量基准测试：对比「优化前」与「优化后」的多维答案质量（RAGAS 三指标）。

一次运行同时测量两个配置、三个指标，输出完整「优化前 vs 优化后」对比表：
  - faithfulness    答案忠实度：生成内容是否忠于检索到的资料（0~1，越高越好）
  - context_recall  检索召回率：参考答案所需资料是否被检索召回（0~1，越高越好）
  - context_precision 检索精准度：召回的资料是否真相关、是否排在前面（0~1，越高越好）

配置差异（即本次“优化”所做的工作）：
  - 优化前（基线）：top_k=4 + 宽松 Prompt（允许补充外部知识） + temperature=0.3
  - 优化后        ：top_k=8 + 严格 Prompt（仅依据资料）       + temperature=0

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
from ragas.metrics import faithfulness, context_precision, context_recall
from datasets import Dataset
from langchain_openai import ChatOpenAI

# 三个要测的指标，key 与 RAGAS 返回结果里的字段名一致
METRICS = {
    "faithfulness": faithfulness,
    "context_recall": context_recall,
    "context_precision": context_precision,
}


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


def build_rows(top_k, strict, temperature):
    """复用项目检索 / 生成链路，收集 RAGAS 需要的样本。

    top_k      : 送进 LLM 的段落数（4=基线，8=优化后）
    strict     : True=严格仅依据资料（优化后），False=宽松允许补充（基线）
    temperature: 生成温度（基线 0.3，优化后 0）
    """
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
        # 2) 混合检索，取指定 top_k 段
        top = retriever.retrieve(q)[:top_k]
        contexts = [c["text"] for c in top]
        # 3) 按指定 Prompt 策略 + 温度生成答案
        text, _ = generate_answer(item["question"], top, temperature=temperature, strict=strict)
        rows.append({
            "question": item["question"],
            "answer": text,
            "contexts": contexts,
            "reference": item.get("reference", ""),
        })
    return rows


def eval_metrics(rows):
    """给 RAGAS 的三个裁判指标挂上 DeepSeek（替代默认 gpt-4o-mini），返回各指标均值。"""
    judge = ChatOpenAI(
        base_url=settings["llm"]["base_url"],   # https://api.deepseek.com
        api_key=os.environ["OPENAI_API_KEY"],
        model="deepseek-v4-flash",
        temperature=0,
    )
    for m in METRICS.values():
        try:
            m.llm = judge
        except Exception:
            pass  # 个别版本接口不同，跳过即可

    dataset = Dataset.from_list(rows)
    result = evaluate(dataset, metrics=list(METRICS.values()))
    return {name: _mean_metric(result, name) for name in METRICS}


def main():
    top_k_opt = settings["retrieval"]["top_k_final"]   # 优化后的上下文窗口大小（8）

    # —— 优化前（基线）：top_k=4 + 宽松 Prompt + temperature=0.3 ——
    print(">>> 评估优化前（基线）：top_k=4, 宽松Prompt, temperature=0.3")
    base_rows = build_rows(top_k=4, strict=False, temperature=0.3)
    base = eval_metrics(base_rows)

    # —— 优化后：top_k=8 + 严格 Prompt + temperature=0 ——
    print(f">>> 评估优化后：top_k={top_k_opt}, 严格Prompt, temperature=0")
    opt_rows = build_rows(top_k=top_k_opt, strict=True, temperature=0)
    opt = eval_metrics(opt_rows)

    # 打印对比表
    print("\n===== RAG 质量对比（RAGAS 三指标）=====")
    print(f"{'指标':<18}{'优化前':>10}{'优化后':>10}{'提升':>12}")
    for name in METRICS:
        b, o = base[name], opt[name]
        improve = (o - b) / b * 100 if b else 0.0
        print(f"{name:<18}{b:>10.4f}{o:>10.4f}{improve:>+11.1f}%")
    print("=======================================\n")

    # 生成可读报告
    lines = [
        "# RAG 质量基准报告\n\n",
        f"- 评估集: tests/eval_set.json（{len(opt_rows)} 条真实问答对）\n",
        "- 指标: RAGAS faithfulness / context_recall / context_precision（均 0~1，越高越好）\n",
        "- 裁判模型: DeepSeek (deepseek-v4-flash)\n\n",
        "| 指标 | 优化前 | 优化后 | 提升 |\n",
        "|------|--------|--------|------|\n",
    ]
    for name in METRICS:
        b, o = base[name], opt[name]
        improve = (o - b) / b * 100 if b else 0.0
        lines.append(f"| {name} | {b:.4f} | {o:.4f} | {improve:+.1f}% |\n")
    lines.append(
        "\n## 配置差异（即本次优化手段）\n\n"
        "| 维度 | 优化前（基线） | 优化后 |\n"
        "|------|----------------|--------|\n"
        "| 上下文窗口 top_k | 4 | 8 |\n"
        "| 生成 Prompt | 宽松（允许补充外部知识） | 严格（仅依据资料） |\n"
        "| 生成温度 temperature | 0.3 | 0 |\n"
    )
    report = "".join(lines)
    out_path = os.path.join(BASE_DIR, "evaluation_report.md")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(report)
    print("报告已写入", out_path)


if __name__ == "__main__":
    main()
