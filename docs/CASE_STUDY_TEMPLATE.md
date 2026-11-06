# Case study: KnowledgeOS AI

> Template. Replace every _italic prompt_ with your own words and **your own measured numbers**.
> Do not report results you did not measure.

## 1. Problem
_Who needs this and why? (e.g. students revising from many PDFs; analysts checking claims against sources.)
What goes wrong with a plain chatbot? (unsupported answers, no way to check sources.)_

## 2. Goals and constraints
- Answers must cite the exact passage they rely on, and say so when evidence is missing.
- Must run on free Google Colab, with no API key required to start.
- _Add your own goals (latency target, document types, …)._

## 3. Design decisions
| Decision | Alternatives considered | Why |
|---|---|---|
| Hybrid retrieval with Reciprocal Rank Fusion | dense only; weighted score mixing | _your reasoning_ |
| NumPy exact vector search | FAISS, Chroma | _your reasoning_ |
| Citation verification against retrieved chunk IDs | trusting model output | _your reasoning_ |
| _…_ | | |

## 4. Architecture
_Paste the Mermaid diagram from the README and explain the document and question lifecycles in a few sentences._

## 5. Implementation highlights
- _What was hardest? (e.g. keeping chunk IDs stable, honest fallbacks, streaming with citations.)_
- _One code excerpt you are proud of, with a sentence on why._

## 6. Evaluation
- Dataset: _N documents, M questions, how labels were made._
- Retrieval results (from Evaluation Lab exports):

| Strategy | Precision@k | Recall@k | MRR | Mean latency |
|---|---|---|---|---|
| _fill in_ | | | | |

- Answer results: _citation validity, evidence coverage, F1; note whether an LLM-judge was used._
- _What surprised you? Which questions failed, and why?_

## 7. Limitations
_Be specific: language coverage, PDF layouts, scale, no authentication, judge bias, small eval set._

## 8. Future improvements
_e.g. approximate-nearest-neighbour index, multilingual embeddings, user accounts, PDF page previews._

## 9. What I learned
_Two or three honest sentences._

