"""HTTP layer for the KnowledgeOS web app (Starlette, which Gradio already installs).

launch_web() starts the server in a background thread so the notebook stays usable.
"""
from __future__ import annotations

import socket
import threading
import time
from pathlib import Path
from typing import Any, Optional

from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from ..logging_config import get_logger, log_event
from .api import WebAPI

log = get_logger("web")
STATIC = Path(__file__).parent / "static"
MAX_AUDIO = 15 * 1024 * 1024


def _json(data: dict[str, Any]) -> JSONResponse:
    return JSONResponse(data, status_code=400 if "error" in data else 200,
                        headers={"Cache-Control": "no-store"})


async def _form(request: Request, **limits: Any) -> Any:
    """request.form() with size limits where this Starlette version supports them."""
    try:
        return await request.form(**limits)
    except TypeError:
        return await request.form()


async def _body(request: Request) -> dict[str, Any]:
    try:
        data = await request.json()
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def build_app(api: WebAPI) -> Starlette:
    async def index(request: Request) -> Response:
        return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-store"})

    async def state(request: Request) -> Response:
        return _json(await run_in_threadpool(api.state))

    async def ask(request: Request) -> Response:
        b = await _body(request)
        q = str(b.get("question", ""))[:4000]
        docs = [str(d) for d in b.get("doc_ids") or []][:50]
        return _json(await run_in_threadpool(api.ask, str(b.get("owner", ""))[:80], b.get("conv_id"), q, docs))

    async def source(request: Request) -> Response:
        p = request.query_params
        try:
            i = int(p.get("i", "0"))
            page = int(p["page"]) if p.get("page") else None
        except ValueError:
            return _json({"error": "Bad page request."})
        return _json(await run_in_threadpool(api.source, p.get("aid", ""), i, page))

    async def image(request: Request) -> Response:
        data = api.image(request.path_params["key"])
        if data is None:
            return Response(status_code=404)
        return Response(data, media_type="image/png", headers={"Cache-Control": "private, max-age=600"})

    async def study(request: Request) -> Response:
        b = await _body(request)
        return _json(await run_in_threadpool(api.study, str(b.get("action", "")), str(b.get("doc_id", "")),
                                             int(b.get("count", 8) or 8)))

    async def settings(request: Request) -> Response:
        if request.method == "GET":
            return _json(await run_in_threadpool(api.settings))
        b = await _body(request)
        return _json(await run_in_threadpool(api.save_settings, str(b.get("provider", "none")),
                                             str(b.get("model", "")), str(b.get("key", "")),
                                             str(b.get("base_url", ""))))

    async def test_provider(request: Request) -> Response:
        return JSONResponse(await run_in_threadpool(api.test_provider))

    async def upload(request: Request) -> Response:
        form = await _form(request, max_files=100)
        files = []
        for item in form.getlist("files"):
            if hasattr(item, "read"):
                files.append((item.filename or "upload", await item.read()))
        return _json(api.start_upload(files))

    async def job(request: Request) -> Response:
        return _json(api.job(request.path_params["jid"]))

    async def delete_doc(request: Request) -> Response:
        b = await _body(request)
        return _json(await run_in_threadpool(api.delete_doc, str(b.get("doc_id", ""))))

    async def transcribe(request: Request) -> Response:
        form = await _form(request, max_files=2)
        audio = form.get("audio")
        if audio is None or not hasattr(audio, "read"):
            return _json({"error": "No audio received."})
        data = await audio.read()
        if len(data) > MAX_AUDIO:
            return _json({"error": "Recording too long; keep questions under about a minute."})
        suffix = Path(audio.filename or "a.webm").suffix.lower()
        return _json(await run_in_threadpool(api.transcribe, data, suffix, str(form.get("mode", "transcribe"))))

    routes = [
        Route("/", index),
        Route("/api/state", state),
        Route("/api/ask", ask, methods=["POST"]),
        Route("/api/source", source),
        Route("/api/img/{key}", image),
        Route("/api/study", study, methods=["POST"]),
        Route("/api/settings", settings, methods=["GET", "POST"]),
        Route("/api/settings/test", test_provider, methods=["POST"]),
        Route("/api/upload", upload, methods=["POST"]),
        Route("/api/job/{jid}", job),
        Route("/api/docs/delete", delete_doc, methods=["POST"]),
        Route("/api/transcribe", transcribe, methods=["POST"]),
        Mount("/static", StaticFiles(directory=str(STATIC)), name="static"),
    ]
    return Starlette(routes=routes)


class WebServer:
    def __init__(self, server: Any, thread: threading.Thread, port: int) -> None:
        self.server, self.thread, self.port = server, thread, port

    def stop(self) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=10)


def _port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


def launch_web(svc: Optional[Any] = None, port: int = 8000, host: str = "127.0.0.1") -> tuple[WebServer, Any]:
    """Start the web app in a background thread. Returns (server, service); call server.stop() to stop."""
    import uvicorn

    from ..config import SecretStore, Settings
    from ..services import KnowledgeService

    svc = svc or KnowledgeService(Settings.load(), SecretStore())
    if not _port_free(port):
        raise RuntimeError(f"Port {port} is already in use. Stop the previous web app first.")
    app = build_app(WebAPI(svc))
    server = uvicorn.Server(uvicorn.Config(app, host=host, port=port, log_level="warning", access_log=False))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.1)
    if not server.started:
        raise RuntimeError("The web server did not start; see the logs above.")
    log_event(log, "web app started", port=port)
    return WebServer(server, thread, port), svc
