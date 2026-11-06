"""Light, modern look for the app: Gradio theme + custom CSS + light-mode switch."""
from __future__ import annotations

import gradio as gr

FORCE_LIGHT_JS = """
() => {
  const u = new URL(window.location.href);
  if (u.searchParams.get('__theme') !== 'light') {
    u.searchParams.set('__theme', 'light');
    window.location.replace(u.href);
  }
}
"""


def make_theme():
    try:
        font = [gr.themes.GoogleFont("Inter"), "ui-sans-serif", "system-ui", "sans-serif"]
        base = gr.themes.Soft(primary_hue="indigo", secondary_hue="violet", neutral_hue="slate", font=font)
    except Exception:
        base = gr.themes.Soft()
    try:
        return base.set(
            body_background_fill="linear-gradient(180deg, #f5f7ff 0%, #fbfcff 40%, #ffffff 100%)",
            block_background_fill="#ffffff",
            block_border_color="#e7eaf6",
            block_shadow="0 1px 2px rgba(16,24,64,.04), 0 6px 20px rgba(79,70,229,.06)",
            block_radius="16px",
            button_primary_background_fill="linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%)",
            button_primary_background_fill_hover="linear-gradient(135deg, #4f46e5 0%, #7c3aed 100%)",
            button_primary_text_color="#ffffff",
            button_secondary_background_fill="#ffffff",
            button_secondary_background_fill_hover="#f1f2ff",
            input_background_fill="#fbfcff",
            input_border_color="#dfe3f3",
        )
    except TypeError:  # older/newer Gradio without some variables: keep the base theme
        return base


CSS = """
.gradio-container { max-width: 1320px !important; margin: 0 auto !important; }
footer { display: none !important; }

/* ---------- top bar ---------- */
.kos-topbar { display:flex; align-items:center; justify-content:space-between; gap:16px; flex-wrap:wrap;
  padding: 14px 18px; border-radius: 20px; margin-bottom: 6px;
  background: linear-gradient(120deg, #eef2ff 0%, #f5f3ff 50%, #ecfeff 100%); border: 1px solid #e4e7fb; }
.kos-brand { display:flex; align-items:center; gap:12px; }
.kos-mark { width:44px; height:44px; border-radius:14px; display:grid; place-items:center; font-size:22px;
  background: linear-gradient(135deg,#6366f1,#8b5cf6); color:#fff; box-shadow: 0 8px 20px rgba(99,102,241,.35); }
.kos-name { font-size:21px; font-weight:800; color:#1e1b4b; letter-spacing:-.02em; }
.kos-sub { font-size:13px; color:#64748b; }
.kos-pills { display:flex; gap:8px; flex-wrap:wrap; }
.kos-pill { font-size:12px; font-weight:600; padding:5px 11px; border-radius:999px; background:#fff;
  border:1px solid #e4e7fb; color:#334155; }
.kos-pill.ok { color:#15803d; border-color:#bbf7d0; background:#f0fdf4; }
.kos-pill.warn { color:#b45309; border-color:#fde68a; background:#fffbeb; }

/* ---------- tabs ---------- */
button[role="tab"] { font-weight:600 !important; border-radius: 12px 12px 0 0 !important; transition: all .15s ease; }
button[role="tab"]:hover { color:#4f46e5 !important; background:#f5f3ff !important; }
button[role="tab"][aria-selected="true"] { color:#4f46e5 !important; }

/* ---------- buttons ---------- */
button { transition: transform .12s ease, box-shadow .12s ease, background .15s ease !important; }
button.primary:hover, button.lg.primary:hover { transform: translateY(-1px); box-shadow: 0 8px 18px rgba(99,102,241,.30) !important; }

/* ---------- home ---------- */
.kos-hero { padding: 28px 28px 22px; border-radius: 22px; color:#1e1b4b;
  background: radial-gradient(1200px 300px at 0% 0%, #e0e7ff 0%, transparent 60%),
              radial-gradient(800px 260px at 100% 0%, #f3e8ff 0%, transparent 60%), #ffffff;
  border:1px solid #e4e7fb; }
.kos-hero h1 { font-size: 30px; line-height:1.15; margin:0 0 6px; font-weight:800; letter-spacing:-.03em; }
.kos-hero p { margin:0; color:#475569; font-size:15px; }
.kos-stats { display:grid; grid-template-columns: repeat(auto-fit, minmax(140px,1fr)); gap:12px; margin-top:18px; }
.kos-stat { background:#fff; border:1px solid #eef0fb; border-radius:16px; padding:14px 16px;
  box-shadow: 0 1px 2px rgba(16,24,64,.04); transition: transform .15s ease, box-shadow .15s ease; }
.kos-stat:hover { transform: translateY(-2px); box-shadow: 0 10px 24px rgba(79,70,229,.10); }
.kos-stat .v { font-size: 26px; font-weight: 800; color:#312e81; }
.kos-stat .l { font-size: 12px; color:#64748b; font-weight:600; text-transform: uppercase; letter-spacing:.05em; }
.kos-steps2 { display:flex; gap:8px; flex-wrap:wrap; margin-top:14px; }
.kos-steps2 span { font-size:12px; padding:5px 11px; border-radius:999px; background:#eef2ff; color:#4338ca; font-weight:600; }

.kos-action button, button.kos-action { min-height: 92px !important; border-radius: 18px !important; font-size: 15px !important;
  font-weight: 700 !important; background:#ffffff !important; border:1px solid #e4e7fb !important; color:#1e1b4b !important;
  box-shadow: 0 1px 2px rgba(16,24,64,.04) !important; white-space: pre-line !important; }
.kos-action button:hover, button.kos-action:hover { transform: translateY(-3px); border-color:#c7d2fe !important;
  box-shadow: 0 12px 26px rgba(99,102,241,.16) !important; background: linear-gradient(180deg,#ffffff,#f7f7ff) !important; }

/* ---------- notices ---------- */
.kos-note { border-radius:12px; padding:10px 14px; margin:6px 0; border:1px solid #e7eaf6; background:#fff; font-size:14px; }
.kos-note.ok { border-left:4px solid #16a34a; } .kos-note.warn { border-left:4px solid #f59e0b; }
.kos-note.err { border-left:4px solid #dc2626; } .kos-note.info { border-left:4px solid #6366f1; }
.kos-empty { text-align:center; padding:30px 14px; color:#64748b; border:1.5px dashed #dfe3f3; border-radius:16px; background:#fbfcff; }
.kos-empty b { display:block; font-size:16px; color:#334155; margin-bottom:4px; }

/* ---------- flashcards ---------- */
.kos-grid { display:grid; grid-template-columns: repeat(auto-fill, minmax(240px,1fr)); gap:16px; }
.kos-flip { perspective: 1000px; cursor:pointer; display:block; }
.kos-flip input { display:none; }
.kos-flip-inner { position:relative; min-height:180px; transition: transform .55s cubic-bezier(.2,.8,.2,1); transform-style: preserve-3d; }
.kos-flip input:checked + .kos-flip-inner { transform: rotateY(180deg); }
.kos-face { position:absolute; inset:0; backface-visibility:hidden; -webkit-backface-visibility:hidden; border-radius:18px;
  padding:18px; display:flex; flex-direction:column; justify-content:center; gap:8px; border:1px solid #e4e7fb;
  box-shadow: 0 6px 18px rgba(79,70,229,.08); }
.kos-front { background: linear-gradient(135deg,#ffffff,#f5f3ff); }
.kos-back { background: linear-gradient(135deg,#eef2ff,#ecfeff); transform: rotateY(180deg); }
.kos-face .t { font-weight:700; color:#1e1b4b; font-size:15px; }
.kos-face .h { font-size:11px; color:#6366f1; font-weight:700; text-transform:uppercase; letter-spacing:.08em; }
.kos-face .s { font-size:11px; color:#64748b; margin-top:auto; }
.kos-flip:hover .kos-front { border-color:#c7d2fe; }

/* ---------- quiz ---------- */
.kos-q { background:#fff; border:1px solid #e7eaf6; border-radius:18px; padding:16px 18px; margin-bottom:14px;
  box-shadow: 0 1px 2px rgba(16,24,64,.04); }
.kos-q .qt { font-weight:700; color:#1e1b4b; margin-bottom:10px; }
.kos-opt { display:block; margin:6px 0; cursor:pointer; }
.kos-opt input { display:none; }
.kos-opt span { display:block; padding:10px 14px; border-radius:12px; border:1.5px solid #e4e7fb; background:#fbfcff;
  transition: all .15s ease; }
.kos-opt:hover span { border-color:#a5b4fc; background:#f5f3ff; }
.kos-opt.correct input:checked + span { background:#dcfce7; border-color:#16a34a; color:#14532d; }
.kos-opt.wrong input:checked + span { background:#fee2e2; border-color:#dc2626; color:#7f1d1d; }
.kos-q:has(input:checked) .kos-opt.correct span { border-color:#16a34a; }
.kos-q details { margin-top:8px; color:#475569; font-size:14px; }
.kos-q .src { font-size:12px; color:#64748b; margin-top:6px; }

/* ---------- source viewer ---------- */
.kos-viewer-head { font-weight:700; color:#1e1b4b; }
.kos-chips label { border-radius:999px !important; }
.kos-textdoc { background:#fff; border:1px solid #e7eaf6; border-radius:14px; padding:14px 16px; max-height:520px; overflow:auto;
  font-size:14px; line-height:1.6; white-space:pre-wrap; }
.kos-doc-title { font-weight:700; margin-bottom:6px; color:#312e81; }
mark.kos-focus { background:#ffe58a; padding:1px 2px; border-radius:4px; }
.kos-passage { border:1px solid #e7eaf6; border-radius:12px; padding:10px 12px; margin:8px 0; background:#fff; }
.kos-passage .meta { font-size:12px; color:#64748b; margin-bottom:4px; }
.kos-badge { display:inline-block; padding:1px 8px; border-radius:999px; font-size:12px; font-weight:600; border:1px solid #e4e7fb; }
.kos-cards { display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:10px; margin:6px 0 12px; }
.kos-card { border:1px solid #e7eaf6; background:#fff; border-radius:14px; padding:12px 14px; }
.kos-card .v { font-size:22px; font-weight:800; color:#312e81; } .kos-card .l { color:#64748b; font-size:12px; text-transform:uppercase; }
.kos-steps { display:flex; flex-wrap:wrap; gap:6px; font-size:13px; }
.kos-steps span { border-radius:999px; padding:3px 10px; background:#eef2ff; color:#4338ca; font-weight:600; }
@media (max-width: 720px) { .kos-hero h1 { font-size: 23px; } .kos-name { font-size:18px; } }
"""
