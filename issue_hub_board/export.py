"""Export hubs as a static, read-only site for the viewer.

    out/index.html                          hub picker; opens the last hub used
    out/hubs.json                           every hub: slug, name, prefix, counts
    out/<hub>/index.html, viewer.js, ...    the viewer, copied from ../viewer
    out/<hub>/data/index.json               every card, project and document
    out/<hub>/data/issues/<ID>.json         one issue's page, links and relations
    out/<hub>/data/projects/<slug>.json     one project's page
    out/<hub>/data/docs/<slug>.json         one document's page

The markdown stays the source; this is a cache to rebuild after every pull.
Files whose content is unchanged are not rewritten, so a static server's
Last-Modified stays put and browsers revalidate for free. Raw hub files
(illustrated plans, images, documents) are linked as `hub/<path>`; whatever
serves the export serves each hub's checkout at `<hub>/hub/`.
"""

from __future__ import annotations

import hashlib
import json
import posixpath
import shutil
import re
import subprocess
import time
from pathlib import Path

from . import parse as hubparse
from . import render as hubrender

VIEWER = Path(__file__).resolve().parent / "viewer"
VIEWER_FILES = ("index.html", "viewer.js", "viewer.css")
PICKER = "hubs.html"

ID_RE = re.compile(r"\b[A-Z][A-Z0-9]*-\d+\b")
SECTION_RE = re.compile(r"^#{2,3}\s+(?P<name>.+?)\s*$")
VIEWABLE = {".html", ".htm", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".pdf", ".mp4", ".mov", ".webm"}
INVERSE = {"Blocks": "Blocked by", "Blocked by": "Blocks", "Follows": "Followed by",
           "Followed by": "Follows", "Related": "Related", "Duplicate of": "Duplicated by"}


def _write(path: Path, text: str) -> bool:
    """Write only when the content changed; atomic, so a reader never sees half a file."""
    data = text.encode("utf-8")
    if path.exists() and path.read_bytes() == data:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.tmp")
    temp.write_bytes(data)
    temp.replace(path)
    return True


def _hub_links(html: str) -> str:
    """The renderer links raw files at /raw/ and plans at /projects/; the export serves both under hub/."""
    html = re.sub(r'(href|src)="/raw/', r'\1="hub/', html)
    return re.sub(r'href="/projects/([^"/]+\.html)"', r'href="hub/projects/\1"', html)


def _section(body: str, name: str) -> list[str]:
    lines, inside = [], False
    for line in body.splitlines():
        heading = SECTION_RE.match(line)
        if heading:
            if inside:
                break
            inside = heading.group("name").strip().lower() == name.lower()
            continue
        if inside:
            lines.append(line)
    return lines


def _name(text: str, path: str) -> str:
    """Link text, unless it is just the path spelled out."""
    return posixpath.basename(path) if not text or "/" in text or text.endswith(posixpath.basename(path)) else text


def page_key(path: str) -> str:
    return path.replace("/", "~")


def _links(markdown: str, context: str) -> list[dict]:
    """Every file, page and artifact the markdown links to, in order, once each."""
    seen: set[str] = set()
    out: list[dict] = []
    for match in hubparse.LINK_RE.finditer(markdown):
        text, href = match.group("text").strip(" `"), match.group("href").strip()
        if not href or href.startswith(("#", "mailto:")):
            continue
        if href.startswith(("http://", "https://")):
            if "claude.ai/" in href and href not in seen:
                seen.add(href)
                dead = markdown[match.end():match.end() + 16].lstrip().startswith("(dead link")
                out.append({"type": "artifact", "name": text or "Artifact", "href": href, **({"dead": True} if dead else {})})
            continue
        path = posixpath.normpath(posixpath.join(context, href.split("#")[0])).lstrip("./")
        if path in seen:
            continue
        seen.add(path)
        folder, stem, ext = posixpath.dirname(path), posixpath.splitext(posixpath.basename(path))[0], posixpath.splitext(path)[1].lower()
        if ext == ".md" and folder == "issues":
            continue  # relations cover issue links
        if ext == ".md" and folder == "projects":
            out.append({"type": "project", "name": text, "slug": stem})
        elif ext == ".md" and folder == "documents":
            out.append({"type": "doc", "name": text, "slug": stem})
        elif ext == ".md":
            out.append({"type": "page", "name": _name(text, path), "key": path})
        elif ext in VIEWABLE:
            out.append({"type": "file", "name": _name(text, path), "path": path, "ext": ext[1:]})
        elif ext:
            out.append({"type": "file", "name": _name(text, path), "path": path, "ext": ext[1:], "download": True})
    return out


def _issue_folder(root: Path, issue_id: str) -> list[dict]:
    """Files kept for one issue: documents/<id>/ and documents/<id>-*.*"""
    key = issue_id.lower()
    documents = root / "documents"
    found: list[Path] = []
    folder = documents / key
    if folder.is_dir():
        found += sorted(p for p in folder.iterdir() if p.is_file() and not p.name.startswith("."))
    found += sorted(p for p in documents.glob(f"{key}-*") if p.is_file())
    out = []
    for path in found[:60]:
        ext = path.suffix.lower()
        rel = path.relative_to(root).as_posix()
        if ext == ".md" and path.parent == documents:
            out.append({"type": "doc", "name": path.name, "slug": path.stem})
        else:
            out.append({"type": "file", "name": path.name, "path": rel, "ext": ext[1:],
                        "download": ext not in VIEWABLE, "size": path.stat().st_size})
    return out


def _relations(body: str) -> list[dict]:
    out = []
    for line in _section(body, "Relationships"):
        line = line.strip().lstrip("-* ").strip()
        kind, sep, rest = line.partition(":")
        if not sep or kind.strip().lower() == "project":
            continue
        for issue_id in ID_RE.findall(rest):
            out.append({"rel": kind.strip(), "id": issue_id})
    return out


def _git_dates(root: Path) -> dict[str, tuple[int, int]]:
    """Path -> (first commit, last commit) as unix times, from one pass over history."""
    try:
        log = subprocess.run(["git", "-C", str(root), "log", "--relative", "--format=@%ct", "--name-only", "--", "issues", "projects"],
                             capture_output=True, text=True, check=True, timeout=60).stdout
    except (OSError, subprocess.SubprocessError):
        return {}
    dates: dict[str, tuple[int, int]] = {}
    stamp = 0
    for line in log.splitlines():
        if line.startswith("@"):
            stamp = int(line[1:])
        elif line:
            last = dates.get(line, (stamp, stamp))[1]
            dates[line] = (stamp, last)  # log runs newest first, so the last one seen is the first commit
    return dates


def _stamp(text: str) -> int:
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return int(time.mktime(time.strptime(text.strip()[:19], fmt)))
        except ValueError:
            continue
    return 0


def _hub_config(root: Path) -> dict:
    try:
        return json.loads((root / "hub.json").read_text())
    except (OSError, ValueError):
        return {}


def export(root: Path, out: Path) -> dict:
    """Write the export and return counts of what changed."""
    root, out = Path(root).resolve(), Path(out).resolve()
    hub = hubparse.load_hub(root)
    config = _hub_config(root)
    # "dates": "metadata" trusts Created At / Updated At over git history (imported or generated hubs).
    dates = {} if config.get("dates") == "metadata" else _git_dates(root)
    changed = 0

    for name in VIEWER_FILES:
        changed += _write(out / name, (VIEWER / name).read_text(encoding="utf-8"))

    relations: dict[str, list[dict]] = {}
    for issue in hub.issues.values():
        for rel in _relations(issue.body):
            relations.setdefault(issue.id, []).append(rel)
    for issue_id, rels in list(relations.items()):
        for rel in rels:
            inverse = INVERSE.get(rel["rel"])
            target = relations.setdefault(rel["id"], [])
            if inverse and rel["id"] in hub.issues and not any(r["id"] == issue_id for r in target):
                target.append({"rel": inverse, "id": issue_id})

    cards = []
    live: set[str] = set()
    for issue in sorted(hub.issues.values(), key=lambda i: -i.num):
        rel = issue.path.relative_to(root).as_posix()
        first, last = dates.get(rel, (0, 0))
        created = _stamp(issue.created) or first or int(issue.mtime)
        updated = max(_stamp(issue.updated), last) or int(issue.mtime)
        card = issue.card()
        for key in ("mtime", "created", "updated", "priority"):
            card.pop(key)
        card.update({"created": created, "updated": updated})
        cards.append(card)
        attachments = _links(issue.body, "issues")
        for extra in _issue_folder(root, issue.id):
            if not any(a.get("path") == extra.get("path") and a.get("slug") == extra.get("slug") for a in attachments):
                attachments.append(extra)
        page = {"id": issue.id, "file": rel, "html": _hub_links(hubrender.render(issue.body, "issues")),
                "attachments": attachments, "relations": relations.get(issue.id, [])}
        live.add(f"{issue.id}.json")
        changed += _write(out / "data" / "issues" / f"{issue.id}.json", json.dumps(page, separators=(",", ":")))

    counts: dict[str, dict[str, int]] = {}
    latest: dict[str, int] = {}
    for card in cards:
        if card["projectSlug"]:
            bucket = counts.setdefault(card["projectSlug"], {})
            bucket[card["status"]] = bucket.get(card["status"], 0) + 1
            latest[card["projectSlug"]] = max(latest.get(card["projectSlug"], 0), card["updated"])

    projects = []
    live_projects: set[str] = set()
    for project in hub.projects.values():
        _, meta = hubparse._split_metadata(project.path.read_text(encoding="utf-8"))
        release = hubparse.LINK_RE.search(meta.get("Release", ""))
        documents = _links("\n".join(_section(project.body, "Documents")), "projects")
        for d in documents:
            if d["type"] == "page" and (root / d["key"]).is_file():
                d["name"] = hubparse._split_metadata((root / d["key"]).read_text(encoding="utf-8"))[0] or d["name"]
        plan = f"projects/{project.slug}.html" if project.has_plan else None
        if plan and not any(d.get("path") == plan for d in documents):
            documents.insert(0, {"type": "file", "name": f"{project.slug}.html", "path": plan, "ext": "html"})
        status_lines = [line for line in _section(project.body, "Status") if line.strip()]
        projects.append({
            "slug": project.slug, "name": project.name, "status": project.status,
            "lead": meta.get("Lead", ""), "start": meta.get("Start Date", ""), "target": meta.get("Target Date", ""),
            "release": release.group("text") if release else meta.get("Release", "").strip() or None,
            "plan": plan, "documents": documents,
            "summary": status_lines[-1].strip() if status_lines else "",
            "counts": counts.get(project.slug, {}), "total": sum(counts.get(project.slug, {}).values()),
            "updated": latest.get(project.slug) or int(project.mtime),
        })
        page = {"slug": project.slug, "file": project.path.relative_to(root).as_posix(),
                "html": _hub_links(hubrender.render(project.body, "projects"))}
        live_projects.add(f"{project.slug}.json")
        changed += _write(out / "data" / "projects" / f"{project.slug}.json", json.dumps(page, separators=(",", ":")))
    for slug in {c["projectSlug"] for c in cards if c["projectSlug"] and c["projectSlug"] not in hub.projects}:
        name = next(c["projectName"] for c in cards if c["projectSlug"] == slug)
        projects.append({"slug": slug, "name": name or slug, "status": "", "orphan": True, "documents": [],
                         "counts": counts.get(slug, {}), "total": sum(counts.get(slug, {}).values()),
                         "updated": latest.get(slug, 0)})

    live_docs: set[str] = set()
    for doc in hub.docs.values():
        page = {"slug": doc.slug, "name": doc.name, "file": doc.path.relative_to(root).as_posix(),
                "html": _hub_links(hubrender.render(doc.body, "documents"))}
        live_docs.add(f"{doc.slug}.json")
        changed += _write(out / "data" / "docs" / f"{doc.slug}.json", json.dumps(page, separators=(",", ":")))

    # Other markdown the issues and projects link to, such as release notes.
    live_pages: set[str] = set()
    linked = [a for card in cards for a in json.loads((out / "data" / "issues" / f"{card['id']}.json").read_text())["attachments"]]
    linked += [d for project in projects for d in project["documents"]]
    always = [name for name in ("ROADMAP.md", "HUB.md") if (root / name).is_file()]
    for key in sorted({a["key"] for a in linked if a["type"] == "page"} | set(always)):
        source = root / key
        if not source.is_file() or source.resolve().parent == (root / "issues").resolve():
            continue
        title, _ = hubparse._split_metadata(source.read_text(encoding="utf-8"))
        page = {"key": key, "name": title or source.stem, "file": key,
                "html": _hub_links(hubrender.render(hubparse._body_after_title(source.read_text(encoding="utf-8")),
                                                     posixpath.dirname(key)))}
        live_pages.add(f"{page_key(key)}.json")
        changed += _write(out / "data" / "pages" / f"{page_key(key)}.json", json.dumps(page, separators=(",", ":")))

    removed = 0
    for folder, keep in (("issues", live), ("projects", live_projects), ("docs", live_docs), ("pages", live_pages)):
        for stale in (out / "data" / folder).glob("*.json"):
            if stale.name not in keep:
                stale.unlink()
                removed += 1

    index = {
        "name": config.get("name") or root.name, "prefix": config.get("prefix", ""),
        "kinds": config.get("kinds") or ["Bug", "Feature", "Improvement", "Task"],
        "labelGroups": config.get("labels") or {},
        "statuses": hubparse.STATUSES, "openStatuses": hubparse.OPEN_STATUSES, "priorities": hubparse.PRIORITIES,
        "issues": cards,
        "projects": sorted(projects, key=lambda p: (-p["updated"], p["name"].lower())),
        "pages": always,
        "docs": sorted(({"slug": d.slug, "name": d.name} for d in hub.docs.values()), key=lambda d: d["name"].lower()),
    }
    index["version"] = hashlib.sha1(json.dumps(index, sort_keys=True).encode()).hexdigest()[:12]
    changed += _write(out / "data" / "index.json", json.dumps(index, separators=(",", ":")))
    return {"issues": len(cards), "projects": len(projects), "docs": len(hub.docs), "changed": changed, "removed": removed}



def hub_slug(root: Path) -> str:
    config = _hub_config(Path(root))
    return hubparse.slugify(config.get("name") or "") or hubparse.slugify(Path(root).resolve().name) or "hub"


def slugs(roots: list[Path]) -> dict[str, Path]:
    """One URL-safe name per hub, from its hub.json name; duplicates get a number."""
    out: dict[str, Path] = {}
    for root in roots:
        base = hub_slug(root)
        slug, n = base, 2
        while slug in out:
            slug, n = f"{base}-{n}", n + 1
        out[slug] = Path(root).resolve()
    return out


def _copy_files(root: Path, dest: Path) -> int:
    """Mirror a hub's own files (never dotfiles or .git) for a fully static site."""
    copied = 0
    for path in root.rglob("*"):
        rel = path.relative_to(root)
        if any(part.startswith(".") for part in rel.parts) or not path.is_file():
            continue
        target = dest / rel
        if target.exists() and target.stat().st_size == path.stat().st_size and target.stat().st_mtime >= path.stat().st_mtime:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        copied += 1
    return copied


def export_all(roots: list[Path], out: Path, with_files: bool = False) -> dict:
    """Export every hub into out/<slug>/, plus the picker and hubs.json.

    with_files also copies each hub's own files to out/<slug>/hub/, for static
    hosts (such as GitHub Pages) that cannot serve the hub checkout."""
    out = Path(out).resolve()
    hubs = slugs(roots)
    totals = {"hubs": len(hubs), "issues": 0, "projects": 0, "changed": 0, "removed": 0}
    listing = []
    for slug, root in hubs.items():
        counts = export(root, out / slug)
        if with_files:
            totals["changed"] += _copy_files(root, out / slug / "hub")
        for key in ("issues", "projects", "changed", "removed"):
            totals[key] += counts[key]
        index = json.loads((out / slug / "data" / "index.json").read_text())
        open_statuses = set(index["openStatuses"])
        listing.append({
            "slug": slug, "name": index["name"], "prefix": index["prefix"],
            "open": sum(1 for i in index["issues"] if i["status"] in open_statuses),
            "total": len(index["issues"]),
            "updated": max((i["updated"] for i in index["issues"]), default=0),
        })
    for stale in out.iterdir() if out.exists() else ():
        if stale.is_dir() and stale.name not in hubs and (stale / "data" / "index.json").exists():
            shutil.rmtree(stale)
            totals["removed"] += 1
    totals["changed"] += _write(out / "hubs.json", json.dumps(listing, separators=(",", ":")))
    totals["changed"] += _write(out / "index.html", (VIEWER / PICKER).read_text(encoding="utf-8"))
    return totals
