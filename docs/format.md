# The hub format

issue-hub-board reads a **hub**: a folder of plain markdown files, one per
issue and one per project. Nothing else is required, and the files stay
readable and editable by hand, by scripts or by coding agents. The
[`demo/`](../demo) folder is a complete example.

```
my-hub/
  hub.json               optional: name, prefix, kinds, label groups
  issues/ABC-12.md       one file per issue (required)
  projects/<slug>.md     one file per project (optional)
  projects/<slug>.html   a project's illustrated plan (optional)
  documents/<slug>.md    notes and write-ups the issues cite (optional)
  documents/abc-12/      files for one issue: pages, images, data (optional)
  ROADMAP.md, HUB.md     shown under "Hub" in the sidebar when present
```

The [issue-hub](https://github.com/mueedqadri/issue-hub) plugin creates and
maintains hubs in this format for coding agents, but the board does not need
it.

## Issues

A file named `<PREFIX>-<number>.md` in `issues/`, such as `ABC-12.md`. The
prefix is letters and digits, starting with a letter.

```markdown
# ABC-12: Show where rain is heading in the next hour

## Metadata
- **Status:** In Progress
- **Kind:** Feature
- **Priority:** High (2)
- **Project:** [Radar Rewrite](../projects/radar-rewrite.md)
- **Labels:** Radar, Forecast
- **Created At:** 2026-09-28 09:00:00
- **Updated At:** 2026-10-15 17:00:00

## Description

**What the user will notice:** ...

## Relationships

- Blocked by: ABC-10
- Related: ABC-14

## Documents

- Findings: [timing.html](../documents/abc-12/timing.html)

## Comments

**2026-10-15** — A dated note.
```

The board reads only the `## Metadata` list for its fields and renders
everything else as the issue's page.

| Field | Values | Notes |
| --- | --- | --- |
| `Status` | `Backlog`, `Todo`, `In Progress`, `In Review`, `Done`, `Canceled` | Anything else is shown as Backlog. A trailing state in parentheses, such as `Done (completed)`, is accepted. |
| `Kind` | One of `hub.json`'s `kinds` | Shown as a colored badge. Optional. |
| `Priority` | `Urgent (1)`, `High (2)`, `Medium (3)`, `Low (4)`, `No priority (0)` | The number decides the icon and sort order. |
| `Project` | A link to `projects/<slug>.md`, a project's name, or `None` | Links the issue to its project card, progress and plan. |
| `Labels` | Comma-separated, or `None` | Labels listed in `hub.json` groups get their group's color and filter. |
| `Created At`, `Updated At` | `YYYY-MM-DD` or `YYYY-MM-DD HH:MM:SS` | Optional. In a git repo the board also uses commit dates. |

**Relationships:** each line under `## Relationships` is `- <kind>: <ids>`,
such as `- Blocks: ABC-13, ABC-14`. The board adds the opposite side for you
(`Blocks` ↔ `Blocked by`, `Follows` ↔ `Followed by`, `Related`, `Duplicate
of` ↔ `Duplicated by`). A `- Project:` line is ignored here.

**Comments:** under `## Comments` (or `### Comments`), each comment starts
with `**YYYY-MM-DD** —` or with a quoted author line, `> **Name**
(YYYY-MM-DD HH:MM:SS):`. The count shows on the issue's row.

**Files and pages:** every local file an issue links to appears in its panel,
plus everything in `documents/<lower-case id>/` and any
`documents/<lower-case id>-*` file. HTML, images, video and PDFs open inside
the board; other files download. Links to other markdown files open as
pages. Bare issue ids in the text, such as ABC-10, become links.

## Projects

A file in `projects/`, named by its slug:

```markdown
# Project: Radar Rewrite

## Metadata
- **Status:** In Progress
- **Lead:** Priya
- **Start Date:** 2026-09-15
- **Target Date:** 2026-12-01
- **Release:** [Release 2.6](../releases/release-2-6.md)

## Documents
- Illustrated plan: [`radar-rewrite.html`](./radar-rewrite.html)

## Description
...

## Status

2026-10-15: GPU tiles nearly done.
```

The project's issues are the issues whose `Project` names it; progress is
Done out of everything not Canceled. A `projects/<slug>.html` next to the
file is its **illustrated plan**: the board opens it with one click or `p`.
Links under `## Documents` show on the project and on each of its issues. The
last line under `## Status` is shown as the project's summary.

## hub.json

Optional. Without it, the hub's name is its folder name.

```json
{
  "name": "Pocket Weather",
  "prefix": "PW",
  "kinds": ["Bug", "Feature", "Improvement", "Task"],
  "labels": {
    "area": ["Forecast", "Offline", "Radar"],
    "platform": ["iOS", "watchOS"],
    "focus": ["Performance", "Accessibility"]
  },
  "dates": "metadata"
}
```

| Key | Meaning |
| --- | --- |
| `name` | Shown in the sidebar and the hub switcher; its slug is the hub's URL, such as `/pocket-weather/`. |
| `prefix` | The issue id prefix, used by the command bar. |
| `kinds` | The Kind values, in the order the sidebar lists them. |
| `labels` | Label groups. `area` labels get the sidebar's Areas list; every group becomes a filter. |
| `dates` | `metadata` uses only `Created At`/`Updated At`; the default also looks at git history and uses the later date. |
