# Evaluation

## Retrieval metrics (deterministic)

For each question and strategy, the top-k results are compared with the question's relevance labels:

| Label type (precedence) | A result is relevant if… | Recall is… |
|---|---|---|
| chunk IDs | its chunk ID is listed | listed chunks found / listed chunks |
| document IDs | it comes from a listed document | listed documents found / listed documents |
| keywords | it contains any listed keyword (case-insensitive) | keywords found in top-k / keywords |

- **Precision@K** = relevant results in top k / k
- **MRR** = 1 / rank of the first relevant result (0 if none)
- **Hit@K** = 1 if any relevant result is in the top k
- **Latency** = wall-clock retrieval time per question (mean and p95)

Questions without labels are excluded from these metrics.

## Answer metrics

| Metric | Kind | Meaning |
|---|---|---|
| Token-F1 | deterministic | Word overlap with your reference answer; rewards wording, not correctness |
| Citation validity | deterministic | Share of citations that point to passages actually retrieved |
| Evidence coverage | deterministic | Share of substantive sentences carrying a verified citation |
| LLM-judge (1–5) | **model-based** | An LLM's opinion of agreement with the reference; biased and non-deterministic |
| Estimated cost | arithmetic | ≈4 characters per token × prices you enter; not a bill |

## How to run a fair comparison

1. Write 30+ questions that reflect real use, with labels you trust.
2. Compare strategies on the same question set and the same index (the comparison table records model and
   chunk size per run).
3. Treat small differences as noise; inspect per-question results before drawing conclusions.
4. Re-run after changing chunking or the embedding model (re-index first).

No benchmark numbers are claimed for this project: results depend entirely on your documents and labels.
