"""Evaluation Lab page: define questions, compare retrieval strategies, evaluate answers."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

import gradio as gr

from ..config import RETRIEVAL_STRATEGIES
from . import controllers as C
from . import workspace_controllers as W

if TYPE_CHECKING:
    from ..services import KnowledgeService


def build(svc: "KnowledgeService") -> dict[str, Any]:
    cases = gr.State([])
    runs = gr.State([])
    last_ret = gr.State(None)
    last_ans = gr.State(None)
    gr.Markdown("### Evaluation lab")
    with gr.Accordion("How to read these numbers", open=False):
        gr.Markdown(W.EVAL_LIMITATIONS)

    # ---------- 1. questions ----------
    with gr.Accordion("1 · Evaluation questions", open=True):
        with gr.Row():
            with gr.Column(scale=2):
                q = gr.Textbox(label="Question", max_lines=2)
                exp = gr.Textbox(label="Reference answer (optional, for answer metrics)", max_lines=3)
                kw = gr.Textbox(label="Relevant keywords (separate with ;) — a passage is relevant if it contains one",
                                max_lines=1)
                rel_docs = gr.Dropdown(label="…or relevant documents (overrides keywords)", multiselect=True,
                                       choices=C.doc_filter_choices(svc), value=[])
                add = gr.Button("Add question", variant="primary")
            with gr.Column(scale=1):
                up = gr.File(label="Load questions (.csv or .json)", file_types=[".csv", ".json"], type="filepath")
                load = gr.Button("Load file", size="sm")
                samples = gr.Button("Add sample questions", size="sm")
                export_q = gr.Button("Export questions", size="sm")
                clear = gr.Button("Clear all questions", size="sm", variant="stop")
                q_file = gr.File(label="Download", interactive=False)
                gr.Markdown("CSV columns: `question, expected_answer, relevant_keywords, relevant_doc_ids, "
                            "relevant_chunk_ids` (lists separated by `;`).")
        q_msg = gr.HTML()
        table = gr.Dataframe(interactive=False, wrap=True, label="Questions")

    # ---------- 2. retrieval experiment ----------
    with gr.Accordion("2 · Retrieval experiment (deterministic metrics)", open=True):
        with gr.Row():
            strategies = gr.CheckboxGroup([(v, v) for v in RETRIEVAL_STRATEGIES], value=list(RETRIEVAL_STRATEGIES),
                                          label="Strategies to compare")
            k = gr.Slider(1, 20, value=5, step=1, label="k (results per question)")
        run_ret = gr.Button("Run retrieval experiment", variant="primary")
        ret_msg = gr.HTML()
        ret_summary = gr.Dataframe(interactive=False, label="This run: per-strategy summary")
        with gr.Accordion("Per-question results", open=False):
            ret_rows = gr.Dataframe(interactive=False, wrap=True)
        comparison = gr.Dataframe(interactive=False, label="Experiment comparison (all runs this session)")
        with gr.Row():
            ret_csv = gr.Button("Export run .csv", size="sm")
            ret_json = gr.Button("Export run .json", size="sm")
        ret_file = gr.File(label="Download", interactive=False)

    # ---------- 3. answer evaluation ----------
    with gr.Accordion("3 · Answer evaluation (end to end)", open=False):
        with gr.Row():
            a_strat = gr.Dropdown(C.STRATEGY_CHOICES, value=svc.settings.retrieval_strategy, label="Strategy")
            judge = gr.Checkbox(label="Also run LLM-as-judge (model-based, uses extra tokens)", value=False)
        with gr.Row():
            p_in = gr.Number(label="Price USD per 1M input tokens (optional)", value=0)
            p_out = gr.Number(label="Price USD per 1M output tokens (optional)", value=0)
        run_ans = gr.Button("Run answer evaluation", variant="primary")
        ans_msg = gr.HTML()
        ans_summary = gr.Dataframe(interactive=False, label="Summary")
        ans_rows = gr.Dataframe(interactive=False, wrap=True, label="Per-question answers")
        with gr.Row():
            ans_csv = gr.Button("Export .csv", size="sm")
            ans_json = gr.Button("Export .json", size="sm")
        ans_file = gr.File(label="Download", interactive=False)

    # ---------------- handlers ----------------
    def _after(state, msg):
        return state, W.cases_table(state), msg

    add.click(lambda s, a, b, c, d: _after(*W.add_case(s, a, b, c, d)), [cases, q, exp, kw, rel_docs],
              [cases, table, q_msg]).then(lambda: ("", "", ""), None, [q, exp, kw])
    load.click(lambda s, p: _after(*W.load_cases_file(s, p)), [cases, up], [cases, table, q_msg])
    samples.click(lambda s: _after(*W.load_samples(s)), cases, [cases, table, q_msg])
    clear.click(lambda: _after([], ""), None, [cases, table, q_msg])
    export_q.click(lambda s: W.export_cases(svc, s), cases, [q_file, q_msg])

    def _run_ret(state, strats, kk, rs, progress=gr.Progress()):
        return W.run_retrieval(svc, state, strats, kk, rs, lambda f, m: progress(f, desc=m))

    run_ret.click(_run_ret, [cases, strategies, k, runs],
                  [ret_summary, ret_rows, comparison, runs, last_ret, ret_msg])
    ret_csv.click(lambda r: W.export_eval(svc, r, "retrieval_eval", "csv"), last_ret, [ret_file, ret_msg])
    ret_json.click(lambda r: W.export_eval(svc, r, "retrieval_eval", "json"), last_ret, [ret_file, ret_msg])

    def _run_ans(state, s, j, pi, po, progress=gr.Progress()):
        return W.run_answers(svc, state, s, j, pi, po, lambda f, m: progress(f, desc=m))

    run_ans.click(_run_ans, [cases, a_strat, judge, p_in, p_out], [ans_summary, ans_rows, last_ans, ans_msg])
    ans_csv.click(lambda r: W.export_eval(svc, r, "answer_eval", "csv"), last_ans, [ans_file, ans_msg])
    ans_json.click(lambda r: W.export_eval(svc, r, "answer_eval", "json"), last_ans, [ans_file, ans_msg])

    return {"refresh_docs_fn": lambda: gr.update(choices=C.doc_filter_choices(svc)),
            "refresh_docs_outputs": [rel_docs]}

