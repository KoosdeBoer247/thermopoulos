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

Engine [2026-11-26]: the Word file is built in Python with python-docx (already
a suite requirement, also used by the personal runner report), so no Node.js
or 'npm install' is needed. The original Node/docx-js renderer
(build_report_docx.js) is kept and can be chosen with the environment
variable THERMOPOULOS_DOCX_ENGINE=node.

report_kind is "facts" (steady blue-teal palette, "FEITENRAPPORT" badge) or
"advisory" (distinct amber palette, "ADVIESRAPPORT" badge) -- matching, in
visual form, the same facts-vs-recommendation distinction the Markdown
reports already make in their own opening disclaimer line.
"""

from taal import vt
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
    # [2026-11-26] The preamble also ends at the first '## ' heading: the event
    # report puts its key-figure section before the first '---' rule, and it
    # was swallowed here (only its last italic line survived, as the note).
    # Only the FIRST italic line is the auto-generated note.
    while i < len(lines) and lines[i].strip() != "---" and not lines[i].startswith("## "):
        stripped = lines[i].strip()
        if (stripped.startswith("*") and stripped.endswith("*") and not stripped.startswith("**")
                and subtitle_note is None):
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
    if i < len(lines) and lines[i].strip() == "---":
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

        if stripped == "---":
            i += 1
            continue

        if stripped in ("*Einde rapport.*", "*End of report.*"):
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
        "badge": vt("FEITENRAPPORT", "FACT REPORT"),
        "accent": "1F5C7A",       # steady blue-teal
        "accent_light": "DCEBF0",
        "badge_text": "FFFFFF",
    },
    "advisory": {
        "badge": vt("ADVIESRAPPORT", "ADVISORY REPORT"),
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

    engine = os.environ.get("THERMOPOULOS_DOCX_ENGINE", "python").strip().lower()
    if engine != "node":
        return _render_python_docx(payload, output_path)

    script_dir = os.path.dirname(os.path.abspath(__file__))

    # [2026-08-31] Early, plain-language check before shelling out to node at
    # all. Without this, a missing node_modules/docx (e.g. a freshly
    # extracted copy of this suite in a NEW folder -- npm install's result
    # lives inside node_modules, which does not travel with a folder copy
    # unless that folder was copied whole) surfaces as a raw Node.js stack
    # trace ("Cannot find module 'docx'", with a require() call stack) --
    # correct, but not something to expect a non-programmer to diagnose.
    # [2026-10-25] The public release does NOT bundle node_modules (11 MB of
    # third-party code); the one-time 'npm install' below installs the docx
    # package from package.json.
    if not os.path.isfile(os.path.join(script_dir, "node_modules", "docx", "package.json")):
        raise RuntimeError(vt(
            "De Node-route voor Word (THERMOPOULOS_DOCX_ENGINE=node) heeft een "
            "eenmalige stap in DEZE map nodig: open hier een opdrachtvenster en "
            "typ 'npm install' (vereist Node.js, https://nodejs.org, LTS-versie). "
            "Zonder die variabele maakt de suite het Word-bestand zelf.",
            "The Node route for Word (THERMOPOULOS_DOCX_ENGINE=node) needs a "
            "one-time setup step in THIS folder: open a terminal here and run "
            "'npm install' (requires Node.js, https://nodejs.org, the LTS "
            "version). Without that variable the suite builds the Word file itself."))
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


# =============================================================================
# Python renderer (python-docx) -- default since 2026-11-26
# =============================================================================
# Same block list and theme as build_report_docx.js, so the look stays close:
# accent rule and badge, large title, italic note, shaded disclaimer with an
# accent bar, accent-coloured section headings, tables with an accent header
# row, bullets, italic captions, images at full content width, event name in
# the header and badge + page number in the footer. Page size A4. Body text
# 11 pt (slightly larger than the Node version's 10.5 pt).

def _shade(el, fill_hex):
    """Background shading for a paragraph (pPr) or table cell (tcPr)."""
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fill_hex)
    el.append(shd)


def _border(paragraph, side, color_hex, size_eighths, space=4):
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    pPr = paragraph._p.get_or_add_pPr()
    bdr = pPr.find(qn("w:pBdr"))
    if bdr is None:
        bdr = OxmlElement("w:pBdr")
        pPr.append(bdr)
    b = OxmlElement(f"w:{side}")
    b.set(qn("w:val"), "single")
    b.set(qn("w:sz"), str(int(size_eighths)))
    b.set(qn("w:space"), str(int(space)))
    b.set(qn("w:color"), color_hex)
    bdr.append(b)


def _runs(paragraph, inline_runs, size=11.0, color="1A1A1A", bold=None,
          italic=False, font="Calibri"):
    from docx.shared import Pt, RGBColor
    for r in inline_runs:
        run = paragraph.add_run(r["text"])
        run.font.name = font
        run.font.size = Pt(size)
        run.font.color.rgb = RGBColor.from_string(color)
        run.bold = bool(r.get("bold")) if bold is None else bold
        run.italic = italic
    return paragraph


def _page_field(paragraph, size, color):
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Pt, RGBColor
    run = paragraph.add_run()
    run.font.size = Pt(size)
    run.font.color.rgb = RGBColor.from_string(color)
    for tag, attr in (("w:fldChar", "begin"), ("w:instrText", None), ("w:fldChar", "end")):
        el = OxmlElement(tag)
        if attr:
            el.set(qn("w:fldCharType"), attr)
        else:
            el.set(qn("xml:space"), "preserve")
            el.text = "PAGE"
        run._r.append(el)


def _repeat_header(row):
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    trPr = row._tr.get_or_add_trPr()
    el = OxmlElement("w:tblHeader")
    el.set(qn("w:val"), "true")
    trPr.append(el)


def _render_python_docx(payload: dict, output_path: str) -> str:
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.enum.table import WD_TABLE_ALIGNMENT
    from docx.shared import Pt, Cm, RGBColor

    theme = payload["theme"]
    acc, acc_l = theme["accent"], theme["accent_light"]
    doc = Document()
    sec = doc.sections[0]
    sec.page_width, sec.page_height = Cm(21.0), Cm(29.7)
    sec.left_margin = sec.right_margin = Cm(2.2)
    sec.top_margin = sec.bottom_margin = Cm(2.2)
    breedte = sec.page_width - sec.left_margin - sec.right_margin

    st = doc.styles["Normal"]
    st.font.name = "Calibri"
    st.font.size = Pt(11)

    # Header and footer
    hp = sec.header.paragraphs[0]
    _runs(hp, [{"text": payload.get("event_name") or payload["title"]}], size=8.5, color="888888")
    _border(hp, "bottom", acc, 4)
    fp = sec.footer.paragraphs[0]
    fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _runs(fp, [{"text": theme["badge"] + " — "}], size=8.5, color="999999")
    _page_field(fp, 8.5, "999999")

    # Title block
    p = doc.add_paragraph()
    _border(p, "bottom", acc, 24, space=8)
    p.paragraph_format.space_after = Pt(10)
    p = doc.add_paragraph()
    run = p.add_run(" " + theme["badge"] + " ")
    run.bold = True
    run.font.size = Pt(10)
    run.font.color.rgb = RGBColor.from_string(theme["badge_text"])
    _shade(run._r.get_or_add_rPr(), acc)
    p = doc.add_paragraph()
    _runs(p, [{"text": payload["title"]}], size=26, bold=True)
    p.paragraph_format.space_after = Pt(6)
    if payload.get("subtitle_note"):
        p = doc.add_paragraph()
        _runs(p, [{"text": payload["subtitle_note"]}], size=11, color="555555", italic=True)
    if payload.get("disclaimer_runs"):
        p = doc.add_paragraph()
        _shade(p._p.get_or_add_pPr(), acc_l)
        _border(p, "left", acc, 18, space=8)
        p.paragraph_format.space_before = Pt(8)
        p.paragraph_format.space_after = Pt(12)
        _runs(p, payload["disclaimer_runs"], size=10.5)

    base = payload.get("image_base_dir") or "."
    for b in payload["blocks"]:
        t = b["type"]
        if t == "heading":
            lvl = b["level"]
            p = doc.add_heading(level=1 if lvl == 2 else 2)
            _runs(p, b["runs"], size=15 if lvl == 2 else 12.5, bold=True,
                  color=acc if lvl == 2 else "1A1A1A")
            p.paragraph_format.space_before = Pt(16 if lvl == 2 else 10)
            p.paragraph_format.space_after = Pt(6)
            p.paragraph_format.keep_with_next = True
            if lvl == 2:
                _border(p, "bottom", acc, 8)
        elif t == "paragraph":
            p = doc.add_paragraph()
            _runs(p, b["runs"])
            p.paragraph_format.space_after = Pt(6)
        elif t == "bullets":
            for item in b["items"]:
                p = doc.add_paragraph(style="List Bullet")
                _runs(p, item)
        elif t == "caption":
            p = doc.add_paragraph()
            _runs(p, b["runs"], size=9.5, color="666666", italic=True)
            p.paragraph_format.space_after = Pt(12)
        elif t == "table":
            header, rows = b["header"], b["rows"]
            ncol = max([len(header)] + [len(r) for r in rows])
            tab = doc.add_table(rows=1 + len(rows), cols=ncol)
            tab.style = "Table Grid"
            tab.alignment = WD_TABLE_ALIGNMENT.CENTER
            for j in range(ncol):
                c = tab.rows[0].cells[j]
                c.text = ""
                _shade(c._tc.get_or_add_tcPr(), acc)
                if j < len(header):
                    _runs(c.paragraphs[0], header[j], size=10, color="FFFFFF", bold=True)
            _repeat_header(tab.rows[0])
            for i, r in enumerate(rows, start=1):
                for j in range(ncol):
                    c = tab.rows[i].cells[j]
                    c.text = ""
                    if j < len(r):
                        _runs(c.paragraphs[0], r[j], size=10)
            doc.add_paragraph().paragraph_format.space_after = Pt(4)
        elif t == "image":
            pad = os.path.join(base, b["path"])
            if os.path.isfile(pad):
                p = doc.add_paragraph()
                p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                p.paragraph_format.space_before = Pt(6)
                p.add_run().add_picture(pad, width=breedte)
            else:
                p = doc.add_paragraph()
                _runs(p, [{"text": vt(f"[afbeelding niet gevonden: {b['path']}]",
                                      f"[image not found: {b['path']}]")}],
                      size=9.5, color="AA0000", italic=True)
    doc.save(output_path)
    return output_path
