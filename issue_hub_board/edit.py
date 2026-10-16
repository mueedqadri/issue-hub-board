#!/usr/bin/env python3
"""A local board for the issue hub.

    python3 board/serve.py [--port 8787] [--no-open]

Reads `issues/`, `projects/` and `documents/` on every request, so the board is
never stale. Writes are narrow: one metadata line, or one appended comment.
Binds 127.0.0.1 only.
"""

from __future__ import annotations

import json
import mimetypes
import os
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from . import parse as hubparse
from . import render as hubrender

HUB = Path(os.environ.get("ISSUE_HUB", ".")).expanduser().resolve()
UI = Path(__file__).resolve().parent / "ui.html"

_cache: dict[str, object] = {"signature": None, "hub": None}
_lock = threading.Lock()


def _signature() -> tuple:
    parts = []
    for folder in ("issues", "projects", "documents"):
        directory = HUB / folder
        if not directory.is_dir():
            continue
        for entry in os.scandir(directory):
            if entry.name.endswith((".md", ".html")):
                parts.append((entry.name, entry.stat().st_mtime))
    return tuple(sorted(parts))


def hub() -> hubparse.Hub:
    with _lock:
        signature = _signature()
        if signature != _cache["signature"]:
            _cache["hub"] = hubparse.load_hub(HUB)
            _cache["signature"] = signature
        return _cache["hub"]  # type: ignore[return-value]


def invalidate() -> None:
    with _lock:
        _cache["signature"] = None


def hub_kinds() -> list[str]:
    try:
        kinds = json.loads((HUB / "hub.json").read_text()).get("kinds")
    except (OSError, ValueError):
        kinds = None
    return kinds or ["Bug", "Feature", "Improvement", "Task"]


def board_payload() -> dict:
    data = hub()
    counts: dict[str, dict[str, int]] = {}
    latest: dict[str, int] = {}
    for issue in data.issues.values():
        if issue.project_slug:
            bucket = counts.setdefault(issue.project_slug, {})
            bucket[issue.status] = bucket.get(issue.status, 0) + 1
            latest[issue.project_slug] = max(latest.get(issue.project_slug, 0), issue.num)

    projects = [
        {
            "slug": project.slug,
            "name": project.name,
            "status": project.status,
            "hasPlan": project.has_plan,
            "counts": counts.get(project.slug, {}),
            "total": sum(counts.get(project.slug, {}).values()),
            "latest": latest.get(project.slug, 0),
        }
        for project in data.projects.values()
    ]
    # Projects referenced by issues but with no page of their own.
    for issue in data.issues.values():
        if issue.project_slug and issue.project_slug not in data.projects:
            if not any(p["slug"] == issue.project_slug for p in projects):
                projects.append(
                    {
                        "slug": issue.project_slug,
                        "name": issue.project_name or issue.project_slug,
                        "status": "—",
                        "hasPlan": False,
                        "counts": counts.get(issue.project_slug, {}),
                        "total": sum(counts.get(issue.project_slug, {}).values()),
                        "latest": latest.get(issue.project_slug, 0),
                        "orphan": True,
                    }
                )

    return {
        "issues": [issue.card() for issue in sorted(data.issues.values(), key=lambda i: -i.num)],
        # Most recent first: the project holding the newest issue leads. A
        # project with no issues has nothing to date it, so it sorts last.
        "projects": sorted(projects, key=lambda p: (-p["latest"], p["name"].lower())),
        "docs": [{"slug": doc.slug, "name": doc.name} for doc in data.docs.values()],
        "labels": data.labels(),
        "kinds": hub_kinds(),
        "statuses": hubparse.STATUSES,
        "openStatuses": hubparse.OPEN_STATUSES,
        "priorities": hubparse.PRIORITIES,
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "hubboard"

    def log_message(self, fmt: str, *args) -> None:  # quieter console
        if "?" not in str(args[0] if args else ""):
            sys.stderr.write("  %s\n" % (fmt % args))

    # -------------------------------------------------- helpers

    def _send(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, payload: dict, code: int = 200) -> None:
        self._send(code, json.dumps(payload).encode("utf-8"), "application/json; charset=utf-8")

    def _error(self, code: int, message: str) -> None:
        self._json({"error": message}, code)

    def _file(self, path: Path) -> None:
        if not path.is_file():
            self._error(404, f"not found: {path.name}")
            return
        guess = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        if guess.startswith("text/") or guess in ("application/json",):
            guess += "; charset=utf-8"
        self._send(200, path.read_bytes(), guess)

    def _safe(self, relative: str) -> Path | None:
        target = (HUB / relative).resolve()
        return target if str(target).startswith(str(HUB)) else None

    # -------------------------------------------------- GET

    def do_GET(self) -> None:  # noqa: N802
        route = unquote(urlparse(self.path).path)
        try:
            if route in ("/", "/index.html"):
                self._file(UI)
            elif route == "/api/board":
                self._json(board_payload())
            elif route.startswith("/api/issue/"):
                self._issue(route.rsplit("/", 1)[-1])
            elif route.startswith("/api/project/"):
                self._project(route.rsplit("/", 1)[-1])
            elif route.startswith("/api/doc/"):
                self._doc(route.rsplit("/", 1)[-1])
            elif route.startswith("/projects/") and route.endswith(".html"):
                target = self._safe(route.lstrip("/"))
                self._file(target) if target else self._error(403, "outside the hub")
            elif route.startswith("/raw/"):
                target = self._safe(route[len("/raw/") :])
                self._file(target) if target else self._error(403, "outside the hub")
            else:
                self._error(404, f"no route {route}")
        except BrokenPipeError:
            pass
        except Exception as exc:  # surface parse errors in the UI, don't 500 silently
            self._error(500, f"{type(exc).__name__}: {exc}")

    def _issue(self, issue_id: str) -> None:
        issue = hub().issues.get(issue_id)
        if issue is None:
            self._error(404, f"no issue {issue_id}")
            return
        payload = issue.card()
        payload.update(
            {
                "html": hubrender.render(issue.body, "issues"),
                "mtime": issue.path.stat().st_mtime,
                "file": str(issue.path.relative_to(HUB)),
            }
        )
        self._json(payload)

    def _project(self, slug: str) -> None:
        data = hub()
        project = data.projects.get(slug)
        # Newest first — the most recently filed issue is the one you came for.
        issues = sorted(
            (i for i in data.issues.values() if i.project_slug == slug),
            key=lambda i: -i.num,
        )
        if project is None:
            if not issues:
                self._error(404, f"no project {slug}")
                return
            self._json(
                {
                    "slug": slug,
                    "name": issues[0].project_name or slug,
                    "status": "—",
                    "html": "<p><em>No project page in the hub — this group comes from the "
                    "issues that name it.</em></p>",
                    "hasPlan": False,
                    "issues": [i.card() for i in issues],
                }
            )
            return
        self._json(
            {
                "slug": project.slug,
                "name": project.name,
                "status": project.status,
                "html": hubrender.render(project.body, "projects"),
                "hasPlan": project.has_plan,
                "file": str(project.path.relative_to(HUB)),
                "issues": [i.card() for i in issues],
            }
        )

    def _doc(self, slug: str) -> None:
        doc = hub().docs.get(slug)
        if doc is None:
            self._error(404, f"no document {slug}")
            return
        self._json(
            {
                "slug": doc.slug,
                "name": doc.name,
                "html": hubrender.render(doc.body, "documents"),
                "file": str(doc.path.relative_to(HUB)),
            }
        )

    # -------------------------------------------------- POST

    def do_POST(self) -> None:  # noqa: N802
        route = unquote(urlparse(self.path).path)
        if not route.startswith("/api/issue/"):
            self._error(404, f"no route {route}")
            return

        issue_id = route.rsplit("/", 1)[-1]
        issue = hub().issues.get(issue_id)
        if issue is None:
            self._error(404, f"no issue {issue_id}")
            return

        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, json.JSONDecodeError) as exc:
            self._error(400, f"bad request body: {exc}")
            return

        expected = body.get("mtime")
        touched_status = False
        try:
            if "status" in body:
                status = body["status"]
                if status not in hubparse.STATUSES:
                    self._error(400, f"unknown status {status!r}")
                    return
                hubparse.set_status(issue.path, status, expected)
                touched_status = True
                expected = None  # subsequent edits in the same request see our own write
            if "priority" in body:
                name = body["priority"]
                if name not in hubparse.PRIORITIES:
                    self._error(400, f"unknown priority {name!r}")
                    return
                num = hubparse.PRIORITIES.index(name)
                hubparse.set_metadata_field(issue.path, "Priority", f"{name} ({num})", expected)
                expected = None
            if "projectSlug" in body:
                slug = body["projectSlug"] or None
                project = hub().projects.get(slug) if slug else None
                if slug and project is None:
                    self._error(400, f"unknown project {slug!r}")
                    return
                hubparse.set_project(issue.path, slug, project.name if project else None, expected)
                touched_status = True  # README carries the project name per row
                expected = None
            if body.get("comment", "").strip():
                hubparse.append_comment(issue.path, body["comment"], expected)
        except hubparse.ConflictError as exc:
            self._error(409, str(exc))
            return
        except KeyError as exc:
            self._error(422, str(exc))
            return
        except OSError as exc:
            self._error(500, f"write failed: {exc}")
            return

        invalidate()
        readme_synced = False
        if touched_status:
            try:
                readme_synced = hubparse.sync_readme(HUB)
            except OSError as exc:
                sys.stderr.write(f"  README sync failed: {exc}\n")
            invalidate()

        refreshed = hub().issues[issue_id]
        payload = refreshed.card()
        payload.update(
            {
                "html": hubrender.render(refreshed.body, "issues"),
                "mtime": refreshed.path.stat().st_mtime,
                "readmeSynced": readme_synced,
            }
        )
        self._json(payload)


def run(root: Path, port: int, open_browser: bool) -> int:
    global HUB
    HUB = root.expanduser().resolve()

    for folder in ("issues", "projects"):
        if not (HUB / folder).is_dir():
            sys.stderr.write(f"error: {HUB / folder} not found — is this a hub?\n")
            return 1

    data = hub()
    url = f"http://127.0.0.1:{port}"
    print(f"hub    {HUB}")
    print(f"loaded {len(data.issues)} issues, {len(data.projects)} projects, {len(data.docs)} documents")
    print(f"board  {url}   (ctrl-c to stop)")

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    if open_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        server.server_close()
    return 0
