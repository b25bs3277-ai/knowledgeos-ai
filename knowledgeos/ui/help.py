"""Help & getting-started page."""
from __future__ import annotations

from typing import Any

import gradio as gr

from .workspace_controllers import HELP_MD


def build() -> dict[str, Any]:
    gr.Markdown("### Help")
    gr.Markdown(HELP_MD)
    return {}

