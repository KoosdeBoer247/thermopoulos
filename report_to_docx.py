"""
report_to_docx.py -- shared Word-export layer for this suite's three report
generators (generate_event_report.py, generate_klimatos_report.py,
generate_recommendation_report.py).

Deliberately a SEPARATE module rather than baked into each generator: all
three already produce a well-defined, consistent Markdown dialect (this
suite's own -- not arbitrary user Markdown), so a single parser + a single
Node/docx-js renderer covers all three without duplicating styling logic
three times. Each generator's own function keeps returning plain Markdown
text unchanged; this module is an additional, optional step a caller can
take with that same text to also get a styled .docx.

Usage
-----
    from generate_klimatos_report import generate_klimatos_report
    from report_to_docx import export_report_docx

    md_text = generate_klimatos_report(..., output_path="report.md")
    export_report_docx(md_text, output_path="report.docx",
                       report_kind="facts", event_name="Utrecht Marathon")

report_kind is "facts" (steady blue-teal palette, "FEITENRAPPORT" badge) or
"advisory" (distinct amber palette, "ADVIESRAPPORT" badge) -- matching, in
visual form, the same facts-vs-recommendation distinction the Markdown
reports already make in their own opening disclaimer line.
"""

import json
import re
import subprocess
import os


def parse_markdown_report(md_text: str) -> dict:
    """
    Parse this suite's own report-generator Markdown dialect into a
    structured block list a renderer can consume directly.

    Recognised dialect (this suite's own generate_*_report.py functions,
    not arbitrary Markdown): '# Title', italic auto-generated note directly
    below it, a **bold** disclaimer paragraph, '---' rule, '## N. Section'
    headings, '### N.M Subsection' headings, GitHub-style '| a | b |' /
    '|---|---|' tables, '- bullet' lines (including one level of '  '
    indented continuation for multi-line bullets), plain paragraphs, and a
    final italic '*Einde rapport.*' line (dropped -- the docx has its own
    end-of-document treatment via the footer instead).
    """
    lines = md_text.split("\n")
    blocks = []
    title = None
    subtitle_note = None
    i = 0

    # Title (first '# ' line)
    while i < len(lines) and not lines[i].startswith("# "):
        i += 1
    if i < len(lines):
        title = lines[i][2:].strip()
        i += 1

    # Auto-generated note + bold-led disclaimer, up to the first '---' rule
    disclaimer_runs = None
    while i < len(lines) and lines[i].strip() != "---":
        stripped = lines[i].strip()
        if stripped.startswith("*") and stripped.endswith("*") and not stripped.startswith("**"):
            subtitle_note = stripped.strip("*")
        elif stripped.startswith("**"):
            # The disclaimer paragraph starts bold ("**Dit is een ...**") but
            # typically continues as a mix of bold/plain prose across the
            # rest of the sentence -- NOT necessarily bold all the way to
            # the end of the line, so this cannot require the whole line to
            # be **-wrapped. Keep the raw text (with its ** markers intact)
            # for parse_inline() to split into proper bold/plain runs later.
            disclaimer_runs = stripped
        i += 1
    i += 1  # skip the '---' line itself

    def parse_inline(text):
        """Split a line into (text, bold) runs on '**bold**' markers."""
        runs = []
        parts = re.split(r"(\*\*[^*]+\*\*)", text)
        for part in parts:
            if not part:
                continue
            if part.startswith("**") and part.endswith("**"):
                runs.append({"text": part[2:-2], "bold": True})
            else:
                runs.append({"text": part, "bold": False})
        return runs

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if not stripped:
            i += 1
            continue

        if stripped == "*Einde rapport.*":
            i += 1
            continue

        if stripped.startswith("!["):
            m = re.match(r"!\[([^\]]*)\]\(([^)]+)\)", stripped)
            if m:
                blocks.append({"type": "image", "alt": m.group(1), "path": m.group(2)})
                i += 1
                continue

        if stripped.startswith("### "):
            blocks.append({"type": "heading", "level": 3, "runs": parse_inline(stripped[4:])})
            i += 1
            continue

        if stripped.startswith("## "):
            blocks.append({"type": "heading", "level": 2, "runs": parse_inline(stripped[3:])})
            i += 1
            continue

        if stripped.startswith("|"):
            table_lines = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                table_lines.append(lines[i].strip())
                i += 1
            rows = []
            for tl in table_lines:
                cells = [c.strip() for c in tl.strip("|").split("|")]
                if all(re.fullmatch(r"-+", c) for c in cells):
                    continue  # the '|---|---|' separator row
                rows.append(cells)
            if rows:
                blocks.append({
                    "type": "table",
                    "header": [parse_inline(c) for c in rows[0]],
                    "rows": [[parse_inline(c) for c in r] for r in rows[1:]],
                })
            continue

        if stripped.startswith("- "):
            items = []
            while i < len(lines) and (lines[i].strip().startswith("- ") or
                                      (lines[i].startswith("  ") and lines[i].strip()
                                       and not lines[i].strip().startswith(("#", "|", "-")))):
                if lines[i].strip().startswith("- "):
                    items.append(lines[i].strip()[2:])
                else:
                    items[-1] += " " + lines[i].strip()
                i += 1
            blocks.append({"type": "bullets", "items": [parse_inline(it) for it in items]})
            continue

        if stripped.startswith("*") and stripped.endswith("*") and not stripped.startswith("**"):
            blocks.append({"type": "caption", "runs": parse_inline(stripped[1:-1])})
            i += 1
            continue

        # Plain paragraph (possibly wrapped across lines by the generator's
        # own A(f"...") calls that were split with trailing/leading spaces --
        # each such call is already one line here, so no further joining).
        blocks.append({"type": "paragraph", "runs": parse_inline(stripped)})
        i += 1

    return {
        "title": title or "Report",
        "subtitle_note": subtitle_note or "",
        "disclaimer_runs": parse_inline(disclaimer_runs) if disclaimer_runs else [],
        "blocks": blocks,
    }


# Two visual themes -- deliberately distinct, matching this suite's own
# facts-vs-advisory distinction already made in the Markdown disclaimer line.
THEMES = {
    "facts": {
        "badge": "FEITENRAPPORT",
        "accent": "1F5C7A",       # steady blue-teal
        "accent_light": "DCEBF0",
        "badge_text": "FFFFFF",
    },
    "advisory": {
        "badge": "ADVIESRAPPORT",
        "accent": "B7621B",       # distinct warm amber -- flags "contains a recommendation"
        "accent_light": "F6E4D2",
        "badge_text": "FFFFFF",
    },
}


def export_report_docx(md_text: str, output_path: str, report_kind: str = "facts",
                       event_name: str = "", image_base_dir: str = None) -> str:
    """
    Render this suite's own Markdown report dialect as a styled .docx.

    Parameters
    ----------
    md_text : str
        The Markdown text a generate_*_report() call already produced/returned.
    output_path : str
        Where to write the .docx.
    report_kind : str
        "facts" or "advisory" -- selects the visual theme (see THEMES above).
    event_name : str
        Used on the title page footer line; falls back to the parsed
        Markdown title if not given.
    image_base_dir : str, optional
        Directory the Markdown's `![alt](filename.png)` references are
        relative to (e.g. generate_pyrox_report.py's own `plot_dir`).
        Defaults to output_path's own directory -- correct whenever the
        .md and the plot PNGs were written to the same folder, which is
        this suite's own default (see each report generator's own
        plot_dir handling).

    Returns
    -------
    str
        output_path, for convenient chaining.
    """
    if report_kind not in THEMES:
        raise ValueError(f"report_kind must be one of {list(THEMES)}, got {report_kind!r}")

    parsed = parse_markdown_report(md_text)
    theme = THEMES[report_kind]

    if image_base_dir is None:
        image_base_dir = os.path.dirname(os.path.abspath(output_path)) or "."

    payload = {
        **parsed,
        "theme": theme,
        "event_name": event_name or parsed["title"],
        "image_base_dir": os.path.abspath(image_base_dir),
    }

    script_dir = os.path.dirname(os.path.abspath(__file__))

    # [2026-08-31] Early, plain-language check before shelling out to node at
    # all. Without this, a missing node_modules/docx (e.g. a freshly
    # extracted copy of this suite in a NEW folder -- npm install's result
    # lives inside node_modules, which does not travel with a folder copy
    # unless that folder was copied whole) surfaces as a raw Node.js stack
    # trace ("Cannot find module 'docx'", with a require() call stack) --
    # correct, but not something to expect a non-programmer to diagnose.
    # This suite's own packaged .zip bundles node_modules directly for
    # exactly this reason (see MANIFEST.md); this check is the fallback for
    # whenever that bundling didn't happen or the folder was assembled by
    # hand.
    if not os.path.isfile(os.path.join(script_dir, "node_modules", "docx", "package.json")):
        raise RuntimeError(
            "Word export needs a one-time setup step in THIS folder: open a "
            "terminal here and run 'npm install' (requires Node.js -- "
            "https://nodejs.org, the LTS version). This suite's own .zip "
            "normally already includes this; if you copied only some files "
            "out of it, node_modules did not come along."
        )
    json_path = output_path + ".content.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)

    node_script = os.path.join(script_dir, "build_report_docx.js")
    node_exe = _resolve_node_executable()
    result = subprocess.run(
        [node_exe, node_script, json_path, output_path],
        capture_output=True, text=True, timeout=60,
    )
    os.remove(json_path)
    if result.returncode != 0:
        raise RuntimeError(f"build_report_docx.js failed:\n{result.stdout}\n{result.stderr}")

    return output_path


def _resolve_node_executable() -> str:
    """
    Find a working 'node' to call. Tries plain 'node' first (respects
    PATH, the normal/expected case). If that fails to launch at all
    (WinError 2 / FileNotFoundError -- not a node.js error, a "this
    executable does not exist as far as this process can see" error),
    falls back to the standard Windows install locations directly.

    [2026-08-31] Added after a real, repeated case: Node.js was installed
    and confirmed working in a freshly-opened terminal (`node --version`
    succeeded there), but the SAME check inside an already-running Python
    process (Spyder, started before Node.js was installed) still failed
    with WinError 2 -- that process's own view of PATH was set at its own
    startup and never refreshed, exactly like the terminal windows in the
    same troubleshooting session needed to be closed and reopened. A full
    restart of the calling application (Spyder, in that case) is still the
    first thing to try; this fallback exists so a report can still export
    successfully even when that restart hasn't happened yet or isn't
    practical in the moment.
    """
    import shutil
    if shutil.which("node"):
        return "node"

    candidates = [
        r"C:\Program Files\nodejs\node.exe",
        r"C:\Program Files (x86)\nodejs\node.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\nodejs\node.exe"),
    ]
    for path in candidates:
        if os.path.isfile(path):
            return path

    # No working node found anywhere -- report_to_docx.py's caller (each
    # generate_*_report()'s CLI prompt) already catches and reports
    # exceptions from this module without crashing the rest of the run, so
    # raising a clear, actionable message here is enough.
    raise FileNotFoundError(
        "Could not find a working Node.js installation (tried PATH and the "
        "standard Windows install locations). If Node.js was just installed, "
        "close and restart the application calling this (e.g. Spyder) so it "
        "picks up the updated PATH, then try again."
    )
