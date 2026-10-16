#!/usr/bin/env python3
"""Checks for the board's parser, renderer and writers.

    python3 tests/test_board.py

Reads the fixture hub (never writes to it) and exercises the writers against
throwaway copies in a temp directory.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from issue_hub_board import parse as hubparse  # noqa: E402
from issue_hub_board import render as hubrender  # noqa: E402

HUB = ROOT / "tests" / "fixtures" / "hub"
FAILURES: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  ok   {label}")
    else:
        FAILURES.append(f"{label}{' — ' + detail if detail else ''}")
        print(f"  FAIL {label}{' — ' + detail if detail else ''}")


def main() -> int:
    print("parsing the hub")
    hub = hubparse.load_hub(HUB)
    check("issues parsed", len(hub.issues) == 5, f"{len(hub.issues)}")
    check("projects parsed", len(hub.projects) == 1, f"{len(hub.projects)}")
    check("documents parsed", len(hub.docs) == 1, f"{len(hub.docs)}")
    check("project plan found", hub.projects["offline-forecasts"].has_plan)
    check("kinds parsed", {i.id: i.kind for i in hub.issues.values()} ==
          {"PW-1": "Feature", "PW-2": "Feature", "PW-3": "Improvement", "PW-4": "Bug", "PW-5": "Feature"},
          str({i.id: i.kind for i in hub.issues.values()}))
    check("card carries kind", hub.issues["PW-4"].card()["kind"] == "Bug")

    counts = {status: 0 for status in hubparse.STATUSES}
    for issue in hub.issues.values():
        counts[issue.status] += 1
    print(f"       {counts}")
    check("every status normalizes to a column", sum(counts.values()) == len(hub.issues))
    check("titles have no id prefix", all(not i.title.startswith(i.id) for i in hub.issues.values()))
    check("every issue has a title", all(i.title for i in hub.issues.values()))

    offline = {i.project_slug for i in hub.issues.values() if i.project_name == "Offline Forecasts"}
    check("project resolves to one slug", offline == {"offline-forecasts"}, str(offline))
    check("no unknown project slugs leak", all(
        i.project_slug in hub.projects or i.project_slug is None for i in hub.issues.values()
    ), str({i.project_slug for i in hub.issues.values()} - set(hub.projects) - {None}))

    print("rendering every file")
    rendered = 0
    for issue in hub.issues.values():
        try:
            html = hubrender.render(issue.body, "issues")
        except Exception as exc:  # noqa: BLE001
            check(f"render {issue.id}", False, f"{type(exc).__name__}: {exc}")
            continue
        rendered += 1
        if "](./PW-" in html or "](../projects/" in html:
            check(f"{issue.id} links rewritten", False, "raw markdown link survived")
    for project in hub.projects.values():
        try:
            hubrender.render(project.body, "projects")
        except Exception as exc:  # noqa: BLE001
            check(f"render project {project.slug}", False, f"{type(exc).__name__}: {exc}")
    for doc in hub.docs.values():
        try:
            hubrender.render(doc.body, "documents")
        except Exception as exc:  # noqa: BLE001
            check(f"render doc {doc.slug}", False, f"{type(exc).__name__}: {exc}")
    check("all issue bodies rendered", rendered == len(hub.issues), f"{rendered}/{len(hub.issues)}")

    print("link rewriting")
    cases = [
        (("./XYZ-441.md", "issues"), ("#XYZ-441", False)),
        (("../issues/PW-2.md", "projects"), ("#PW-2", False)),
        (("./ABC2-7.md", "issues"), ("#ABC2-7", False)),
        (("../projects/offline-forecasts.md", "issues"), ("#project/offline-forecasts", False)),
        (("../documents/field-notes.md", "issues"), ("#doc/field-notes", False)),
        (("./offline-forecasts.html", "projects"), ("/projects/offline-forecasts.html", True)),
        (("https://example.com/x", "issues"), ("https://example.com/x", True)),
        (("#s-goal", "issues"), ("#s-goal", False)),
    ]
    for (href, context), expected in cases:
        got = hubrender.rewrite_href(href, context)
        check(f"{href} @{context}", got == expected, f"got {got}, want {expected}")

    print("renderer output")
    md = "## Head\n\n| a | b |\n| --- | --- |\n| 1 | `x` |\n\n- one\n  - nested\n- two\n\n> **Name** (2026-01-01):\n>\n> quoted\n\n```sh\necho hi\n```\n"
    html = hubrender.render(md, "issues")
    for fragment in ("<h2", "<table>", "<th>a</th>", "<code>x</code>", "<ul>", "nested", "<blockquote>", "<pre><code"):
        check(f"renders {fragment}", fragment in html)
    # The corpus hard-wraps prose, so a soft newline must join with a space.
    wrapped = hubrender.render("The app has **twelve producers\nfor any of it.** Only one.", "issues")
    check("soft wrap joins with a space", "<br>" not in wrapped and "producers for any" in wrapped, wrapped)
    check("bold spans a wrapped line", "<strong>twelve producers for any of it.</strong>" in wrapped, wrapped)
    check("two trailing spaces force a break", "<br>" in hubrender.render("one  \ntwo", "issues"))
    check("entities survive", "&middot;" in hubrender.render("a &middot; b", "issues"))
    check("html is escaped", "&lt;script&gt;" in hubrender.render("<script>alert(1)</script>", "issues"))

    print("README index")
    overview = hubparse.render_issues_overview(hub)
    listed = overview.count("](./issues/PW-")
    check("index covers every issue", listed == len(hub.issues), f"{listed}/{len(hub.issues)}")
    check("index has all six sections", all(f"### {s} (" in overview for s in hubparse.STATUSES))

    print("writes (temp copies, the fixture hub is untouched)")
    with tempfile.TemporaryDirectory() as tmp:
        sandbox = Path(tmp)
        (sandbox / "issues").mkdir()

        # Exporter dialect: the parenthetical must survive a status change.
        exporter = sandbox / "issues" / "XYZ-900.md"
        exporter.write_text(
            "# XYZ-900: Exporter dialect\n\n## Metadata\n- **Status:** Done (completed)\n"
            "- **Priority:** High (2)\n- **Project:** None\n- **Labels:** None\n\n"
            "## Description\nBody.\n\n## Relationships\n- **Parent:** None\n",
            encoding="utf-8",
        )
        hubparse.set_status(exporter, "In Review")
        text = exporter.read_text(encoding="utf-8")
        check("exporter dialect preserved", "- **Status:** In Review (started)" in text, text.splitlines()[3])
        check("only the status line changed", "- **Priority:** High (2)" in text and "## Relationships" in text)

        # Hand dialect: a bare status stays bare.
        hand = sandbox / "issues" / "XYZ-901.md"
        hand.write_text(
            "# XYZ-901: Hand dialect\n\n## Metadata\n- **Status:** Todo\n- **Priority:** Low (4)\n"
            "- **Project:** None\n- **Labels:** PDF, OCR\n\n## Description\nBody.\n",
            encoding="utf-8",
        )
        hubparse.set_status(hand, "In Progress")
        check("bare dialect preserved", "- **Status:** In Progress\n" in hand.read_text(encoding="utf-8"))

        hubparse.set_metadata_field(hand, "Priority", "Urgent (1)")
        hubparse.set_project(hand, "offline-forecasts", "Offline Forecasts")
        text = hand.read_text(encoding="utf-8")
        check("priority written", "- **Priority:** Urgent (1)" in text)
        check("project written as a link", "- **Project:** [Offline Forecasts](../projects/offline-forecasts.md)" in text)

        # Comments: heading created when absent, reused when present.
        hubparse.append_comment(hand, "First note.", today="2026-08-12")
        text = hand.read_text(encoding="utf-8")
        check("comments heading created", text.count("## Comments") == 1)
        check("comment appended", "**2026-08-12** — First note." in text)
        hubparse.append_comment(hand, "Second note.", today="2026-08-12")
        text = hand.read_text(encoding="utf-8")
        check("heading not duplicated", text.count("## Comments") == 1)
        check("second comment appended", "**2026-08-12** — Second note." in text)

        parsed = hubparse.load_hub(sandbox) if (sandbox / "projects").exists() else None
        if parsed is None:
            (sandbox / "projects").mkdir()
            (sandbox / "documents").mkdir()
            parsed = hubparse.load_hub(sandbox)
        check("re-parsed comment count", parsed.issues["XYZ-901"].comment_count == 2,
              str(parsed.issues["XYZ-901"].comment_count))
        check("re-parsed status", parsed.issues["XYZ-901"].status == "In Progress")

        # Conflict detection.
        stale = hand.stat().st_mtime - 5
        try:
            hubparse.set_status(hand, "Done", stale)
            check("stale mtime is refused", False, "the write went through")
        except hubparse.ConflictError:
            check("stale mtime is refused", True)

        # A file with no Metadata block fails loudly rather than silently.
        broken = sandbox / "issues" / "XYZ-902.md"
        broken.write_text("# XYZ-902: No metadata\n\nJust prose.\n", encoding="utf-8")
        try:
            hubparse.set_status(broken, "Done")
            check("missing metadata raises", False, "no error")
        except KeyError:
            check("missing metadata raises", True)

        # No temp files left behind.
        leftovers = list((sandbox / "issues").glob(".board-*"))
        check("no temp files leaked", not leftovers, str(leftovers))

    print("fixture hub untouched")
    import subprocess

    dirty = subprocess.run(
        ["git", "-C", str(ROOT), "status", "--porcelain", "tests/fixtures/hub"],
        capture_output=True, text=True,
    ).stdout.strip()
    check("git tree clean for hub content", dirty == "", dirty[:200])

    print()
    if FAILURES:
        print(f"{len(FAILURES)} failure(s):")
        for failure in FAILURES:
            print(f"  - {failure}")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
