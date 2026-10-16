"""A markdown subset renderer, sized to what this hub actually contains.

Not CommonMark. It handles ATX headings, paragraphs, bold/em/strike, inline and
fenced code, nested lists, blockquotes (the exporter's comment dialect), GFM
tables, horizontal rules, links and images. Anything more exotic falls through
as text.

The part that matters is `rewrite_href`: cross-links between issues, projects
and documents become in-board navigation instead of dead file paths.
"""

from __future__ import annotations

import html
import posixpath
import re

FENCE_RE = re.compile(r"^(?P<fence>```|~~~)\s*(?P<lang>[\w+-]*)\s*$")
HEADING_RE = re.compile(r"^(?P<hashes>#{1,6})\s+(?P<text>.*?)\s*#*\s*$")
HR_RE = re.compile(r"^\s{0,3}(?:-{3,}|\*{3,}|_{3,})\s*$")
LIST_RE = re.compile(r"^(?P<indent>\s*)(?P<marker>[-*+]|\d+[.)])\s+(?P<text>.*)$")
TABLE_SEP_RE = re.compile(r"^\s*\|?[\s:|-]*-[\s:|-]*\|?\s*$")
ENTITY_RE = re.compile(r"&(?:#\d+|#[xX][0-9a-fA-F]+|[a-zA-Z][a-zA-Z0-9]{1,31});")

ISSUE_ID_RE = re.compile(r"^[A-Z][A-Z0-9]*-(\d+)$")


def rewrite_href(href: str, context: str) -> tuple[str, bool]:
    """Map a hub link to a board route. Returns (href, opens_in_new_tab)."""
    href = href.strip()
    if not href:
        return ("#", False)
    if href.startswith(("http://", "https://", "mailto:")):
        return (href, True)
    if href.startswith("#"):
        return (href, False)

    path, _, fragment = href.partition("#")
    resolved = posixpath.normpath(posixpath.join(context, path)).lstrip("./")
    stem, ext = posixpath.splitext(posixpath.basename(resolved))
    folder = posixpath.dirname(resolved)

    if ext == ".md":
        if folder == "issues" and ISSUE_ID_RE.match(stem):
            return (f"#{stem}", False)
        if folder == "projects":
            return (f"#project/{stem}", False)
        if folder == "documents":
            return (f"#doc/{stem}", False)
        if resolved == "README.md":
            return ("#board", False)
    if ext == ".html" and folder == "projects":
        return (f"/projects/{stem}.html", True)

    return (f"/raw/{resolved}" + (f"#{fragment}" if fragment else ""), True)


def _escape(text: str) -> str:
    """Escape for HTML, but leave existing entities (`&middot;`) intact."""
    out: list[str] = []
    pos = 0
    for match in ENTITY_RE.finditer(text):
        out.append(html.escape(text[pos : match.start()], quote=False))
        out.append(match.group(0))
        pos = match.end()
    out.append(html.escape(text[pos:], quote=False))
    return "".join(out)


def _inline(text: str, context: str) -> str:
    codes: list[str] = []

    def stash_code(match: re.Match[str]) -> str:
        codes.append(match.group(2).strip())
        return f"\x00{len(codes) - 1}\x00"

    text = re.sub(r"(`+)(.+?)\1", stash_code, text, flags=re.S)
    text = _escape(text)

    def link(match: re.Match[str], image: bool) -> str:
        label, href = match.group(1), match.group(2)
        target, external = rewrite_href(html.unescape(href), context)
        safe = html.escape(target, quote=True)
        if image:
            return f'<img src="{safe}" alt="{html.escape(label, quote=True)}">'
        rel = ' target="_blank" rel="noreferrer"' if external else ""
        return f'<a href="{safe}"{rel}>{label}</a>'

    text = re.sub(r"!\[([^\]]*)\]\(([^)\s]+)[^)]*\)", lambda m: link(m, True), text)
    text = re.sub(r"\[([^\]]*)\]\(([^)\s]+)[^)]*\)", lambda m: link(m, False), text)

    text = re.sub(r"\*\*(?=\S)(.+?)(?<=\S)\*\*", r"<strong>\1</strong>", text, flags=re.S)
    text = re.sub(r"__(?=\S)(.+?)(?<=\S)__", r"<strong>\1</strong>", text, flags=re.S)
    text = re.sub(r"~~(?=\S)(.+?)(?<=\S)~~", r"<del>\1</del>", text, flags=re.S)
    text = re.sub(r"(?<![\w*])\*(?=\S)([^*]+?)(?<=\S)\*(?![\w*])", r"<em>\1</em>", text)
    text = re.sub(r"(?<![\w_])_(?=\S)([^_]+?)(?<=\S)_(?![\w_])", r"<em>\1</em>", text)

    for i, code in enumerate(codes):
        text = text.replace(f"\x00{i}\x00", f"<code>{_escape(code)}</code>")
    return text


def _table(rows: list[str], context: str) -> str:
    def cells(line: str) -> list[str]:
        line = line.strip()
        if line.startswith("|"):
            line = line[1:]
        if line.endswith("|"):
            line = line[:-1]
        return [c.strip() for c in line.split("|")]

    head = cells(rows[0])
    out = ["<table><thead><tr>"]
    out += [f"<th>{_inline(c, context)}</th>" for c in head]
    out.append("</tr></thead><tbody>")
    for row in rows[2:]:
        out.append("<tr>")
        values = cells(row)
        values += [""] * (len(head) - len(values))
        out += [f"<td>{_inline(c, context)}</td>" for c in values[: len(head)]]
        out.append("</tr>")
    out.append("</tbody></table>")
    return "".join(out)


def _list(lines: list[str], start: int, context: str) -> tuple[str, int]:
    first = LIST_RE.match(lines[start])
    assert first is not None
    base = len(first.group("indent"))
    ordered = not first.group("marker")[0] in "-*+"

    items: list[list[str]] = []
    i = start
    while i < len(lines):
        line = lines[i]
        match = LIST_RE.match(line)
        if match and len(match.group("indent")) <= base:
            if len(match.group("indent")) < base:
                break
            if (not match.group("marker")[0] in "-*+") != ordered:
                break
            items.append([match.group("text")])
            i += 1
            continue
        if not line.strip():
            # A blank line ends the list unless the next line continues it.
            nxt = i + 1
            if nxt < len(lines):
                cont = LIST_RE.match(lines[nxt])
                indented = lines[nxt].startswith(" " * (base + 1)) and lines[nxt].strip()
                if (cont and len(cont.group("indent")) >= base) or indented:
                    if items:
                        items[-1].append("")
                    i += 1
                    continue
            break
        if items and (line.startswith(" " * (base + 1)) or not LIST_RE.match(line)):
            items[-1].append(line[base + 2 :] if line.startswith(" " * (base + 2)) else line.strip())
            i += 1
            continue
        break

    tag = "ol" if ordered else "ul"
    body = "".join(f"<li>{_blocks(item, context, tight=True)}</li>" for item in items)
    return (f"<{tag}>{body}</{tag}>", i)


def _blocks(lines: list[str], context: str, tight: bool = False) -> str:
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]

        if not line.strip():
            i += 1
            continue

        fence = FENCE_RE.match(line)
        if fence:
            marker = fence.group("fence")
            body: list[str] = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith(marker):
                body.append(lines[i])
                i += 1
            i += 1
            lang = fence.group("lang")
            attr = f' class="language-{lang}"' if lang else ""
            out.append(f"<pre><code{attr}>{_escape(chr(10).join(body))}</code></pre>")
            continue

        heading = HEADING_RE.match(line)
        if heading:
            level = len(heading.group("hashes"))
            text = _inline(heading.group("text"), context)
            slug = re.sub(r"[^a-z0-9]+", "-", heading.group("text").lower()).strip("-")
            out.append(f'<h{level} id="s-{slug}">{text}</h{level}>')
            i += 1
            continue

        if HR_RE.match(line):
            out.append("<hr>")
            i += 1
            continue

        if line.lstrip().startswith(">"):
            quote: list[str] = []
            while i < len(lines) and (lines[i].lstrip().startswith(">") or (quote and lines[i].strip())):
                stripped = lines[i].lstrip()
                quote.append(stripped[1:].removeprefix(" ") if stripped.startswith(">") else stripped)
                i += 1
            out.append(f"<blockquote>{_blocks(quote, context)}</blockquote>")
            continue

        if "|" in line and i + 1 < len(lines) and TABLE_SEP_RE.match(lines[i + 1]):
            rows = [line, lines[i + 1]]
            i += 2
            while i < len(lines) and "|" in lines[i] and lines[i].strip():
                rows.append(lines[i])
                i += 1
            out.append(_table(rows, context))
            continue

        if LIST_RE.match(line):
            chunk, i = _list(lines, i, context)
            out.append(chunk)
            continue

        # A paragraph. This corpus hard-wraps prose at ~78 columns, so a single
        # newline is a soft break (a space); only a two-space or backslash
        # suffix forces a <br>.
        para = ""
        prev_hard = False
        while i < len(lines) and lines[i].strip():
            nxt = lines[i]
            if (
                HEADING_RE.match(nxt)
                or FENCE_RE.match(nxt)
                or HR_RE.match(nxt)
                or nxt.lstrip().startswith(">")
                or LIST_RE.match(nxt)
            ) and para:
                break
            if para:
                para += "\x01" if prev_hard else " "
            para += nxt.strip().rstrip("\\")
            prev_hard = nxt.endswith("  ") or nxt.rstrip().endswith("\\")
            i += 1
        if para:
            text = _inline(para, context).replace("\x01", "<br>\n")
            out.append(text if tight and not out and i >= len(lines) else f"<p>{text}</p>")

    return "".join(out)


def render(markdown: str, context: str = "issues") -> str:
    """Render hub markdown. `context` is the folder the file lives in, so
    relative links resolve the way they do on disk."""
    return _blocks(markdown.replace("\r\n", "\n").replace("\t", "    ").split("\n"), context)
