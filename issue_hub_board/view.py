#!/usr/bin/env python3
"""Serve the read-only viewer for one or more hubs.

    issue-hub-board view [HUB ...] [--out DIR] [--host 127.0.0.1] [--port 8788]

Exports every hub to DIR/<hub> (default DIR ~/.cache/issue-hub/viewer),
serves them, and re-exports when a hub file changes. `/` opens the hub used
last, and the viewer switches between hubs. Each hub's raw files are served
under /<hub>/hub/, never dotfiles or .git. Nothing here writes to a hub.
"""

from __future__ import annotations

import os
import threading
import time
import webbrowser
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from . import export as hubexport

_state = {"signature": None, "checked": 0.0}
_lock = threading.Lock()


def signature(roots: list[Path]) -> tuple:
    parts: list = [(hubexport.VIEWER / name).stat().st_mtime_ns for name in (*hubexport.VIEWER_FILES, hubexport.PICKER)]
    for root in roots:
        parts.append((root / "hub.json").stat().st_mtime_ns if (root / "hub.json").exists() else 0)
        for folder in ("issues", "projects", "documents"):
            for entry in os.scandir(root / folder) if (root / folder).is_dir() else ():
                if entry.is_file() and entry.name.endswith(".md"):
                    stat = entry.stat()
                    parts.append((folder, entry.name, stat.st_mtime_ns, stat.st_size))
    return tuple(parts)


def refresh(roots: list[Path], out: Path) -> None:
    """Re-export at most once a second, and only when a hub file changed."""
    with _lock:
        now = time.monotonic()
        if now - _state["checked"] < 1:
            return
        _state["checked"] = now
        current = signature(roots)
        if current != _state["signature"]:
            hubexport.export_all(roots, out)
            _state["signature"] = current


class Handler(SimpleHTTPRequestHandler):
    hubs: dict[str, Path]
    out: Path

    def log_message(self, fmt: str, *args) -> None:
        pass

    def handle_one_request(self) -> None:
        try:
            super().handle_one_request()
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def translate_path(self, path: str) -> str:
        route = unquote(urlparse(path).path)
        parts = route.lstrip("/").split("/", 2)
        if len(parts) == 3 and parts[1] == "hub" and parts[0] in self.hubs:
            root, relative = self.hubs[parts[0]], parts[2]
            if any(part.startswith(".") for part in relative.split("/")):
                return str(self.out / ".missing")
            target = (root / relative).resolve()
            if root not in target.parents:
                return str(self.out / ".missing")
            return str(target)
        return super().translate_path(path)

    def do_GET(self) -> None:  # noqa: N802
        route = urlparse(self.path).path
        if route in ("/", "/index.html", "/hubs.json") or route.endswith(("/data/index.json", "/index.html")) or route.count("/") == 2 and route.endswith("/"):
            refresh(list(self.hubs.values()), self.out)
        super().do_GET()


def run(roots: list[Path], out: Path | None, host: str, port: int, open_browser: bool) -> int:
    roots = [path.expanduser().resolve() for path in roots]
    out = (out or Path.home() / ".cache" / "issue-hub-board").expanduser().resolve()
    started = time.monotonic()
    counts = hubexport.export_all(roots, out)
    _state["signature"] = signature(roots)
    print(f"exported {counts['hubs']} hub(s), {counts['issues']} issues in {time.monotonic() - started:.1f}s to {out}", flush=True)

    Handler.hubs, Handler.out = hubexport.slugs(roots), out
    server = ThreadingHTTPServer((host, port), partial(Handler, directory=str(out)))
    url = f"http://{host}:{port}/"
    print(f"viewer at {url} ({', '.join(Handler.hubs)})", flush=True)
    if open_browser:
        threading.Timer(0.3, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0
