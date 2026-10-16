"""Read the local issue hub, and write single fields back to it.

The hub is hand-maintained markdown in two dialects (exporter-generated and
hand-written). This module parses only the `## Metadata` bullet list of each
file; everything below it is handed to the renderer verbatim. That keeps the
parser immune to the ~95 distinct `##` headings that appear *inside* issue
descriptions.
"""

from __future__ import annotations

import os
import re
import tempfile
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

# Board columns, in display order. Every status in the corpus normalizes to one.
STATUSES = ["Backlog", "Todo", "In Progress", "In Review", "Done", "Canceled"]
OPEN_STATUSES = ["Backlog", "Todo", "In Progress", "In Review"]

# Linear state types, kept only so a file written in the exporter dialect
# (`Done (completed)`) stays in that dialect after an edit.
STATE_TYPE = {
    "Backlog": "backlog",
    "Todo": "unstarted",
    "In Progress": "started",
    "In Review": "started",
    "Done": "completed",
    "Canceled": "canceled",
}

PRIORITIES = ["No priority", "Urgent", "High", "Medium", "Low"]  # index == Linear number

# An issue file is `<PREFIX>-<number>.md`, e.g. `ABC-12.md`.
ISSUE_ID_RE = re.compile(r"^[A-Z][A-Z0-9]*-(\d+)$")

META_RE = re.compile(r"^- \*\*(?P<key>[^*]+):\*\*\s*(?P<value>.*)$")
LINK_RE = re.compile(r"\[(?P<text>[^\]]*)\]\((?P<href>[^)]*)\)")
STATE_SUFFIX_RE = re.compile(r"\s*\((backlog|unstarted|started|completed|canceled)\)\s*$")
PRIORITY_RE = re.compile(r"^(?P<name>.*?)\s*\((?P<num>\d)\)\s*$")

# Both comment dialects: `> **Name** (2026-06-22 20:57:15):` and `**2026-08-10** — …`
COMMENT_MARK_RE = re.compile(
    r"^(?:>\s*\*\*[^*]+\*\*\s*\(\d{4}-\d{2}-\d{2}|\*\*\d{4}-\d{2}-\d{2}\*\*)"
)
COMMENTS_HEADING_RE = re.compile(r"^#{2,3}\s+Comments\s*$")


def slugify(name: str) -> str:
    s = name.lower()
    s = re.sub(r"[^a-z0-9\s-]", "", s)
    s = re.sub(r"\s+", "-", s.strip())
    return re.sub(r"-{2,}", "-", s)


@dataclass
class Issue:
    id: str
    num: int
    title: str
    status: str
    kind: str
    priority: str
    priority_num: int
    labels: list[str]
    project_slug: str | None
    project_name: str | None
    created: str
    updated: str
    comment_count: int
    body: str  # everything after the `# ABC-n: title` line
    path: Path
    mtime: float

    def card(self) -> dict:
        return {
            "id": self.id,
            "num": self.num,
            "title": self.title,
            "status": self.status,
            "kind": self.kind,
            "priority": self.priority,
            "priorityNum": self.priority_num,
            "labels": self.labels,
            "projectSlug": self.project_slug,
            "projectName": self.project_name,
            "commentCount": self.comment_count,
            "created": self.created,
            "updated": self.updated,
            "mtime": self.mtime,
        }


@dataclass
class Project:
    slug: str
    name: str
    status: str
    body: str
    path: Path
    has_plan: bool  # a sibling projects/<slug>.html exists
    mtime: float


@dataclass
class Doc:
    slug: str
    name: str
    body: str
    path: Path


@dataclass
class Hub:
    root: Path
    issues: dict[str, Issue] = field(default_factory=dict)
    projects: dict[str, Project] = field(default_factory=dict)
    docs: dict[str, Doc] = field(default_factory=dict)

    def labels(self) -> list[str]:
        seen: set[str] = set()
        for issue in self.issues.values():
            seen.update(issue.labels)
        return sorted(seen)


def _split_metadata(text: str) -> tuple[str, dict[str, str]]:
    """Return (title, metadata). Metadata is the bullet list under `## Metadata`."""
    lines = text.splitlines()
    title = ""
    for line in lines:
        if line.startswith("# "):
            title = line[2:].strip()
            break

    meta: dict[str, str] = {}
    inside = False
    for line in lines:
        if line.strip().startswith("## Metadata"):
            inside = True
            continue
        if inside:
            if line.startswith("## "):
                break
            m = META_RE.match(line)
            if m:
                meta[m.group("key").strip()] = m.group("value").strip()
    return title, meta


def _body_after_title(text: str, drop_metadata: bool = False) -> str:
    """Everything below the `# Title` line. The `## Metadata` block is dropped
    when the caller renders those fields as controls instead."""
    lines = text.splitlines()
    start = next((i for i, line in enumerate(lines) if line.startswith("# ")), -1)
    body = lines[start + 1 :]

    if drop_metadata:
        head = next((i for i, line in enumerate(body) if line.strip().startswith("## Metadata")), None)
        if head is not None:
            tail = next(
                (j for j in range(head + 1, len(body)) if body[j].startswith("## ")), len(body)
            )
            body = body[:head] + body[tail:]

    return "\n".join(body).strip("\n")


def _count_comments(text: str) -> int:
    lines = text.splitlines()
    start = next(
        (i for i, line in enumerate(lines) if COMMENTS_HEADING_RE.match(line)), None
    )
    if start is None:
        return 0
    return sum(1 for line in lines[start + 1 :] if COMMENT_MARK_RE.match(line))


def normalize_status(raw: str) -> str:
    value = STATE_SUFFIX_RE.sub("", raw).strip()
    return value if value in STATUSES else "Backlog"


def parse_priority(raw: str) -> tuple[str, int]:
    m = PRIORITY_RE.match(raw.strip())
    if m:
        num = int(m.group("num"))
        return (PRIORITIES[num] if num < len(PRIORITIES) else m.group("name"), num)
    return ("No priority", 0)


def _resolve_project(raw: str, name_index: dict[str, str]) -> tuple[str | None, str | None]:
    """The Project field is a markdown link, a bare name, or `None`."""
    raw = raw.strip()
    if not raw or raw == "None":
        return (None, None)
    m = LINK_RE.search(raw)
    if m:
        slug = Path(m.group("href")).stem
        return (slug, m.group("text").strip())
    key = raw.lower().strip()
    slug = name_index.get(key) or slugify(raw)
    return (slug, raw)


def load_hub(root: Path) -> Hub:
    root = Path(root)
    hub = Hub(root=root)

    # Projects first — their titles are the index bare project names resolve against.
    name_index: dict[str, str] = {}
    for path in sorted((root / "projects").glob("*.md")):
        if path.name.startswith("."):
            continue
        text = path.read_text(encoding="utf-8")
        title, meta = _split_metadata(text)
        name = re.sub(r"^Project:\s*", "", title).strip()
        slug = path.stem
        name_index[name.lower()] = slug
        hub.projects[slug] = Project(
            slug=slug,
            name=name or slug,
            status=meta.get("Status", "Backlog").strip() or "Backlog",
            body=_body_after_title(text, drop_metadata=True),
            path=path,
            has_plan=(root / "projects" / f"{slug}.html").exists(),
            mtime=path.stat().st_mtime,
        )

    for path in sorted((root / "documents").glob("*.md")):
        if path.name.startswith("."):
            continue
        text = path.read_text(encoding="utf-8")
        title, _ = _split_metadata(text)
        hub.docs[path.stem] = Doc(
            slug=path.stem,
            name=title or path.stem,
            body=_body_after_title(text),
            path=path,
        )

    for path in (root / "issues").glob("*-*.md"):
        if not ISSUE_ID_RE.match(path.stem):
            continue
        text = path.read_text(encoding="utf-8")
        title, meta = _split_metadata(text)
        issue_id = path.stem
        display = re.sub(rf"^{re.escape(issue_id)}:\s*", "", title).strip()
        priority, priority_num = parse_priority(meta.get("Priority", ""))
        labels_raw = meta.get("Labels", "None").strip()
        labels = (
            []
            if labels_raw in ("", "None")
            else [s.strip() for s in labels_raw.split(",") if s.strip()]
        )
        project_slug, project_name = _resolve_project(meta.get("Project", "None"), name_index)
        if project_slug in hub.projects:
            project_name = hub.projects[project_slug].name

        hub.issues[issue_id] = Issue(
            id=issue_id,
            num=int(issue_id.rsplit("-", 1)[1]),
            title=display or issue_id,
            status=normalize_status(meta.get("Status", "Backlog")),
            kind="" if meta.get("Kind", "").strip() in ("", "None") else meta.get("Kind", "").strip(),
            priority=priority,
            priority_num=priority_num,
            labels=labels,
            project_slug=project_slug,
            project_name=project_name,
            created=meta.get("Created At", ""),
            updated=meta.get("Updated At", ""),
            comment_count=_count_comments(text),
            body=_body_after_title(text, drop_metadata=True),
            path=path,
            mtime=path.stat().st_mtime,
        )

    return hub


# ---------------------------------------------------------------- writes


def _atomic_write(path: Path, text: str) -> float:
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".board-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return path.stat().st_mtime


class ConflictError(Exception):
    """The file changed on disk since the board loaded it."""


def _check_mtime(path: Path, expected: float | None) -> None:
    if expected is None:
        return
    if abs(path.stat().st_mtime - float(expected)) > 0.001:
        raise ConflictError(
            f"{path.name} changed on disk since the board loaded it — reload before editing."
        )


def set_metadata_field(path: Path, key: str, value: str, expected_mtime: float | None = None) -> float:
    """Rewrite exactly one `- **Key:** …` line inside the `## Metadata` block."""
    _check_mtime(path, expected_mtime)
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)

    inside = False
    for i, line in enumerate(lines):
        stripped = line.rstrip("\n")
        if stripped.startswith("## Metadata"):
            inside = True
            continue
        if inside:
            if stripped.startswith("## "):
                break
            m = META_RE.match(stripped)
            if m and m.group("key").strip() == key:
                ending = "\n" if line.endswith("\n") else ""
                lines[i] = f"- **{key}:** {value}{ending}"
                return _atomic_write(path, "".join(lines))

    raise KeyError(f"no `{key}` line in the Metadata block of {path.name}")


def set_status(path: Path, status: str, expected_mtime: float | None = None) -> float:
    """Write a status, preserving the file's dialect (`Done` vs `Done (completed)`)."""
    _, meta = _split_metadata(path.read_text(encoding="utf-8"))
    value = status
    if STATE_SUFFIX_RE.search(meta.get("Status", "")):
        value = f"{status} ({STATE_TYPE[status]})"
    return set_metadata_field(path, "Status", value, expected_mtime)


def set_project(path: Path, slug: str | None, name: str | None, expected_mtime: float | None = None) -> float:
    value = "None" if not slug else f"[{name}](../projects/{slug}.md)"
    return set_metadata_field(path, "Project", value, expected_mtime)


def append_comment(path: Path, text: str, expected_mtime: float | None = None, today: str | None = None) -> float:
    """Append a comment in the hand-written dialect the recent issues use."""
    _check_mtime(path, expected_mtime)
    body = path.read_text(encoding="utf-8").rstrip("\n")
    stamp = today or date.today().isoformat()
    entry = f"**{stamp}** — {text.strip()}"

    lines = body.splitlines()
    if not any(COMMENTS_HEADING_RE.match(line) for line in lines):
        body = f"{body}\n\n## Comments"
    return _atomic_write(path, f"{body}\n\n{entry}\n")


# ---------------------------------------------------------------- README index


def render_issues_overview(hub: Hub) -> str:
    """Rebuild README's `## Issues Overview` block from the issue files."""
    order = ["Todo", "In Progress", "In Review", "Backlog", "Done", "Canceled"]
    by_status: dict[str, list[Issue]] = {status: [] for status in order}
    for issue in hub.issues.values():
        by_status.setdefault(issue.status, []).append(issue)

    out = ["## Issues Overview", ""]
    for status in order:
        items = sorted(by_status.get(status, []), key=lambda i: i.num, reverse=True)
        out.append(f"### {status} ({len(items)})")
        for issue in items:
            suffix = f" ({issue.project_name})" if issue.project_name else ""
            out.append(f"- [{issue.id}](./issues/{issue.id}.md) - {issue.title}{suffix}")
        out.append("")
    return "\n".join(out)


def sync_readme(root: Path) -> bool:
    """Replace only the Issues Overview block; leave the header, project table
    and the `*Generated on:*` footer untouched."""
    readme = Path(root) / "README.md"
    if not readme.exists():
        return False

    lines = readme.read_text(encoding="utf-8").splitlines()
    try:
        start = next(i for i, line in enumerate(lines) if line.strip() == "## Issues Overview")
    except StopIteration:
        return False

    # The footer is the last standalone `---` rule after the overview.
    footer = next(
        (i for i in range(len(lines) - 1, start, -1) if lines[i].strip() == "---"), len(lines)
    )

    block = render_issues_overview(load_hub(root)).splitlines() + [""]
    updated = lines[:start] + block + lines[footer:]
    text = "\n".join(updated).rstrip("\n") + "\n"
    if text == readme.read_text(encoding="utf-8"):
        return False
    _atomic_write(readme, text)
    return True
