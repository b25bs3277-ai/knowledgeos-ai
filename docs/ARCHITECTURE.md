# Architecture

## Layers

| Layer | Modules | Responsibility |
|---|---|---|
| Configuration & cross-cutting | `config`, `exceptions`, `schemas`, `logging_config`, `security` | Settings, typed errors with user-safe messages, data classes, JSON logs, validation |
| Ingestion | `document_loader`, `text_processing`, `chunking` | Per-format extraction → normalised units with location metadata → chunks |
| Storage & indexes | `storage` (SQLite), `vector_store` (NumPy), `keyword_search` (BM25) | Documents and chunks, vectors, inverted index |
| Retrieval | `embeddings`, `hybrid_retrieval`, `reranking` | Dense, keyword, RRF fusion, optional cross-encoder |
| Generation | `query_understanding`, `llm_providers`, `answer_generation`, `citations` | Classify/rewrite, call the provider, verify citations |
| Application | `services`, `conversations`, `research_tools`, `evaluation`, `diagnostics` | Orchestration, sessions, research outputs, metrics, health |
| Interface | `ui/controllers*`, `ui/*` pages, `app` | Gradio-free page logic; thin Gradio wiring |

The UI calls only `KnowledgeService`; the service owns every store and serialises index mutations with a lock.

## Document lifecycle

1. **Validate** extension, size, magic bytes; sanitise the filename; hash content (SHA-256). Same hash →
   reported as a duplicate, not re-indexed.
2. **Register** a `DocumentRecord` (status `uploaded`) and store the file under `uploads/<doc_id>/`.
3. **Extract** (`extracting`): PDF pages, DOCX headings and tables, Markdown heading paths, CSV/XLSX rows as
   `column: value` records. Optional OCR for empty PDF pages. Errors and empty pages become warnings or a
   `failed` status with the reason — never silent.
4. **Chunk**: paragraph → sentence → word windows, packed to `chunk_size_tokens` with an overlap tail.
   Chunk ID = `doc_id:ordinal:content-hash`, so identical input yields identical IDs.
5. **Index** (`indexing`): embed only chunks whose vectors are not already present; write chunks to SQLite,
   vectors to `vectors.npy` (atomic replace), rebuild BM25. Status `ready`.
6. If the runtime dies mid-way, the next start marks the document `failed` ("interrupted"), never `ready`.

## Question lifecycle

1. **Classify**: greeting / meta / ambiguous → fixed reply, no retrieval; general (no documents or explicit
   "in general") → general answer only if a provider exists; otherwise document question.
2. **Rewrite** follow-ups into a standalone query (LLM when available; otherwise append terms from the
   previous user turns only). Optional multi-query expansion.
3. **Retrieve** candidates per component with relevance floors, fuse by rank (RRF), optionally rerank,
   remove duplicate passages, keep top-k.
4. **Generate** with evidence wrapped in `<evidence id=n>` blocks inside a character budget and a system
   prompt that requires `[n]` citations and treats evidence as untrusted.
5. **Verify** every `[n]` against the passages actually sent. Metadata comes from SQLite; unknown markers are
   shown as `[n?]` and listed as unverified.
6. **Fallbacks**: no evidence → "not enough evidence"; no provider or provider error → evidence-only answer.

## Design decisions

- **NumPy exact search instead of FAISS/Chroma** — no version-compatibility risk on Colab, trivially
  recoverable from SQLite, fast enough at this scale.
- **BM25 implemented directly** — only chunks containing a query term get scores, which keeps
  "no keyword match" detectable for honest insufficient-evidence handling.
- **Rank fusion, not score mixing** — cosine and BM25 scores are on different scales.
- **Gradio-free controllers** — page logic is unit-tested without a browser.
- **Conversations in a separate database** — chat history never mixes with document data.
