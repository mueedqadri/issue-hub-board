"""issue-hub-board: browse markdown issue hubs in a fast, Linear-style viewer.

    issue-hub-board view [HUB ...]          serve the read-only viewer, live
    issue-hub-board export OUT [HUB ...]    write a static site for any web server
    issue-hub-board edit [HUB]              the local board: drag to change status

A hub is a folder with an `issues/` folder of markdown files (see
docs/format.md). Without HUB, the hub is $ISSUE_HUB or the nearest parent
folder with a hub.json, else the current folder.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from . import __version__


def default_hub() -> Path:
    if os.environ.get("ISSUE_HUB"):
        return Path(os.environ["ISSUE_HUB"]).expanduser()
    here = Path.cwd().resolve()
    for folder in (here, *here.parents):
        if (folder / "hub.json").exists():
            return folder
    return here


def check_hub(path: Path) -> Path:
    path = path.expanduser().resolve()
    if not (path / "issues").is_dir():
        sys.exit(f"issue-hub-board: {path} has no issues/ folder, so it is not a hub (see docs/format.md)")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="issue-hub-board", description=__doc__.splitlines()[0])
    parser.add_argument("--version", action="version", version=f"issue-hub-board {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)

    view = commands.add_parser("view", help="serve the read-only viewer; re-exports when a hub changes")
    view.add_argument("hubs", type=Path, nargs="*", metavar="HUB", help="one or more hubs to switch between")
    view.add_argument("--host", default="127.0.0.1", help="address to listen on (default 127.0.0.1)")
    view.add_argument("--port", type=int, default=8788)
    view.add_argument("--out", type=Path, help="export folder (default ~/.cache/issue-hub-board)")
    view.add_argument("--no-open", action="store_true", help="don't open a browser")

    export = commands.add_parser("export", help="write the viewer and hubs as a static site")
    export.add_argument("out", type=Path, help="output folder")
    export.add_argument("hubs", type=Path, nargs="*", metavar="HUB")
    export.add_argument("--with-files", action="store_true",
                        help="also copy each hub's files to <hub>/hub/, for static hosts such as GitHub Pages")

    edit = commands.add_parser("edit", help="the local board: drag cards to change status, add comments")
    edit.add_argument("hub", type=Path, nargs="?", metavar="HUB")
    edit.add_argument("--port", type=int, default=8787)
    edit.add_argument("--no-open", action="store_true", help="don't open a browser")

    args = parser.parse_args(argv)

    if args.command == "view":
        from . import view as viewer
        roots = [check_hub(path) for path in (args.hubs or [default_hub()])]
        return viewer.run(roots, args.out, args.host, args.port, not args.no_open)
    if args.command == "export":
        from . import export as exporter
        roots = [check_hub(path) for path in (args.hubs or [default_hub()])]
        counts = exporter.export_all(roots, args.out, with_files=args.with_files)
        print(f"{counts['hubs']} hub(s), {counts['issues']} issues, {counts['projects']} projects; "
              f"{counts['changed']} files written, {counts['removed']} removed")
        return 0
    from . import edit as editor
    return editor.run(check_hub(args.hub or default_hub()), args.port, not args.no_open)
