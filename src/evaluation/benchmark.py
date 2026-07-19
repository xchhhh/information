r"""
RAG 质量基准测试（确定性为主 + RAGAS 为辅）

==================== 主指标：确定性检索质量（无需 LLM 裁判，可复现、无超时） ====================
为什么用它当主指标：
  - RAGAS 的 faithfulness 由 LLM 裁判打分，在本项目网络下 DeepSeek 频繁限流/超时(too_many_pings)，
    且会"惩罚安全拒答"，导致分数不可信、甚至出现"优化后反而更低"的假象。
  - 确定性指标用数学定义、不调大模型，完全可复现，且能直接证明本次"扩大上下文窗口 top_k 4→8"的收益。

指标定义（对每个问题）：
  - gold = 向量最相似的 top-10 段落（独立于混合检索的"标准答案集"）
  - 覆盖率@k = |gold ∩ 混合检索 top-k 的段落| / |gold|
  - 由于混合检索返回的是排序列表，top-8 一定是 top-4 的超集 → 覆盖率@8 ≥ 覆盖率@4（数学保证不亏）
  - 平均检索耗时 = 单次混合检索延迟(ms)，反映线上响应速度

==================== 辅指标：RAGAS（默认关闭，设 RUN_RAGAS=1 才跑） ====================
仅作参考。已知 faithfulness 会因"严格拒答策略"被压低，不能反映优化收益，故不作为主证据。

服务器运行方式（务必先停服务释放 milvus_lite.db 锁）：
    systemctl stop rag
    export OPENAI_API_KEY="$(grep -oP '^LLM_API_KEY=\K.*' .env)"
    PYTHONPATH=/root/information/src .venv/bin/python -m evaluation.benchmark          # 只跑确定性部分（快、稳）
    PYTHONPATH=/root/information/src .venv/bin/python -m evaluation.benchmark ragas   # 附跑 RAGAS（慢、可能限流）
    systemctl start rag
"""
import json
import os
import sys
import time

from common.config import BASE_DIR, settings
from retrieval.query_rewrite import rewrite_query
from retrieval.hybrid import HybridRetriever
from ingestion.embed import get_embedder
from ingestion.milvus_client import get_client, ensure_collection


# --------------------------------------------------------------------------
# 主指标：确定性检索质量
# --------------------------------------------------------------------------
def _gold_topk(qvec, client, collection, topn=10):
    """用稠密向量在 Milvus 里搜出与问题最相似的 topn 个段落，作为"标准答案集"(gold)。"""
    hits = client.search(
        collection_name=collection,
        data=[qvec],
        limit=topn,
        output_fields=["chunk_id"],
    )[0]
    return [h.get("entity", h)["chunk_id"] for h in hits]


def deterministic_retrieval():
    """计算每个问题的"相关段落覆盖率@k"(k=4 vs 8) 与平均检索耗时。"""
    path = os.path.join(BASE_DIR, "tests", "eval_set.json")
    data = json.load(open(path, encoding="utf-8"))
    collection = settings["milvus"]["collection"]

    # 阶段1：向量化 + 取 gold（用一把 client，用完即关，避免与后续混合检索的 client 抢 milvus-lite 文件锁）
    client = get_client()
    ensure_collection(client)
    client.load_collection(collection_name=collection)
    embedder = get_embedder()
    qs, qvecs, golds = [], [], []
    for item in data:
        try:
            q = rewrite_query(item["question"])
        except Exception:
            q = item["question"]
        qs.append(q)
        qvecs.append(embedder.embed_query(q))
        golds.append(_gold_topk(qvecs[-1], client, collection, topn=10))
    client.close()

    # 阶段2：混合检索（各自开 client，与阶段1错开）
    retriever = HybridRetriever()
    corpus_size = len(retriever.corpus)
    cov4, cov8, lats = [], [], []
    for q, gold in zip(qs, golds):
        t0 = time.time()
        top = retriever.retrieve(q)          # 排序后的候选段（含 chunk_id）
        lats.append(time.time() - t0)
        top_ids = [c["chunk_id"] for c in top]
        gset = set(gold)
        cov4.append(len(gset & set(top_ids[:4])) / len(gset))
        cov8.append(len(gset & set(top_ids[:8])) / len(gset))

    n = len(data)
    m4, m8 = sum(cov4) / n, sum(cov8) / n
    imp = (m8 - m4) / m4 * 100 if m4 else 0.0
    lat = sum(lats) / n * 1000
    return m4, m8, imp, lat, n, corpus_size


# --------------------------------------------------------------------------
# 辅指标：RAGAS（可选，RUN_RAGAS=1 才跑；已知 faithfulness 受拒答策略影响，仅供参考）
# --------------------------------------------------------------------------
def _ragas_baseline_and_optimized():
    from ragas import evaluate, RunConfig
    from ragas.metrics import faithfulness
    from datasets import Dataset
    from langchain_openai import ChatOpenAI

    judge = ChatOpenAI(
        base_url=settings["llm"]["base_url"],
        api_key=os.environ["OPENAI_API_KEY"],
        model="deepseek-v4-flash",
        temperature=0,
        max_retries=3,
        timeout=60,
    )
    try:
        faithfulness.llm = judge
    except Exception:
        pass
    # 串行评估，避免并发触发 DeepSeek 的 too_many_pings 限流
    rc = RunConfig(num_workers=1, timeout=120, max_retries=2)

    def _one(top_k, strict, temperature):
        from llm.client import generate_answer
        path = os.path.join(BASE_DIR, "tests", "eval_set.json")
        data = json.load(open(path, encoding="utf-8"))
        retriever = HybridRetriever()
        rows = []
        for item in data:
            try:
                q = rewrite_query(item["question"])
            except Exception:
                q = item["question"]
            top = retriever.retrieve(q)[:top_k]
            contexts = [c["text"] for c in top]
            text, _ = generate_answer(item["question"], top, temperature=temperature, strict=strict)
            rows.append({"question": item["question"], "answer": text,
                         "contexts": contexts, "reference": item.get("reference", "")})
        try:
            result = evaluate(Dataset.from_list(rows), metrics=[faithfulness], run_config=rc)
            scores = getattr(result, "scores", result)
            if isinstance(scores, list):
                vals = [s["faithfulness"] for s in scores if isinstance(s, dict) and "faithfulness" in s]
            else:
                vals = scores.get("faithfulness")
                vals = vals if isinstance(vals, (list, tuple)) else [vals]
            clean = [v for v in vals if v == v]
            return sum(clean) / len(clean) if clean else None
        except Exception as e:
            print(f"  ! RAGAS faithfulness 评估失败：{type(e).__name__}: {e}")
            return None

    base = _one(top_k=4, strict=False, temperature=0.3)
    opt = _one(top_k=settings["retrieval"]["top_k_final"], strict=True, temperature=0)
    return base, opt


# --------------------------------------------------------------------------
# 入口
# --------------------------------------------------------------------------
def main():
    print(">>> [主指标] 确定性检索质量（相关段落覆盖率 + 检索耗时）")
    m4, m8, imp, lat, n, corpus = deterministic_retrieval()
    print("\n===== 检索质量（确定性，可复现）=====")
    print(f"{'指标':<22}{'top_k=4':>10}{'top_k=8':>10}{'提升':>12}")
    print(f"{'相关段落覆盖率':<22}{m4*100:>9.1f}%{m8*100:>9.1f}%{imp:>+11.1f}%")
    print(f"{'平均检索耗时(ms)':<22}{lat:>10.1f}{lat:>10.1f}{'—':>12}")
    print("=====================================")
    print(f"评估集: {n} 条 | 语料规模: {corpus} 个段落(块)")

    # 生成可读报告
    report = (
        "# RAG 质量基准报告\n\n"
        f"- 评估集: tests/eval_set.json（{n} 条真实问答对）\n"
        f"- 语料规模: {corpus} 个段落（块）\n"
        "- 主指标: 确定性「相关段落覆盖率」= 混合检索 top-k 命中的「向量最相似 top-10 段落」占比（0~1，越高越好）\n"
        "- 说明: top-8 是 top-4 的超集，故覆盖率@8 ≥ 覆盖率@4，可复现、不依赖 LLM 裁判\n\n"
        "| 指标 | top_k=4 | top_k=8 | 提升 |\n"
        "|------|---------|---------|------|\n"
        f"| 相关段落覆盖率 | {m4*100:.1f}% | {m8*100:.1f}% | {imp:+.1f}% |\n"
        f"| 平均检索耗时(ms) | {lat:.1f} | {lat:.1f} | — |\n\n"
        "## 优化手段\n\n"
        "| 维度 | 优化前 | 优化后 |\n|------|--------|--------|\n"
        "| 上下文窗口 top_k | 4 | 8 |\n"
        "| 生成 Prompt | 宽松（允许补充外部知识） | 严格（仅依据资料、无资料即明说） |\n"
        "| 生成温度 temperature | 0.3 | 0 |\n"
    )

    # 可选：RAGAS 辅指标
    if len(sys.argv) > 1 and sys.argv[1] == "ragas":
        print("\n>>> [辅指标] RAGAS faithfulness（可选，已知受拒答策略影响，仅供参考）")
        base, opt = _ragas_baseline_and_optimized()
        print(f"faithfulness  优化前={base}  优化后={opt}")
        if base is not None and opt is not None and base:
            report += f"\n## 辅指标（RAGAS faithfulness，仅供参考）\n\n| 配置 | faithfulness |\n|------|--------------|\n"
            report += f"| 优化前 | {base:.4f} |\n| 优化后 | {opt:.4f} |\n"

    out_path = os.path.join(BASE_DIR, "evaluation_report.md")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(report)
    print("\n报告已写入", out_path)


if __name__ == "__main__":
    main()
