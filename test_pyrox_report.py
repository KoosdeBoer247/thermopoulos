import warnings; warnings.filterwarnings("ignore")
import sys; sys.path.insert(0, ".")
from suite_smoke_test import build_synthetic_excel
from thermopoulos_loader import ThermopoulosData
from run_pyrox import assess_population
from pyrox_groups import TARGET_GROUPS
from generate_pyrox_report import generate_pyrox_report
from report_to_docx import export_report_docx
import os, tempfile

# [2026-10-01, C6] tijdelijke map i.p.v. vast /tmp-pad: werkt ook op Windows
# en faalt niet meer als de map nog niet bestaat.
OUT = tempfile.mkdtemp(prefix="pyrox_report_test_")
import atexit as _ax, shutil as _sh
_ax.register(_sh.rmtree, OUT, True)  # [2026-10-25] clean up

path = build_synthetic_excel(os.path.join(OUT, "Thermopoulos_Test.xlsx"))
data = ThermopoulosData(path)
sheet = "Forecast_7d" if "Forecast_7d" in data.available_sheets else data.available_sheets[0]
report = assess_population(data, sheet=sheet, group_names=list(TARGET_GROUPS.keys()))

md_path = os.path.join(OUT, "pyrox_report.md")
text = generate_pyrox_report(
    event_name="TestCity heatwave", pyrox_report=report,
    output_path=md_path, plot_dir=OUT,
)
print(f"Markdown geschreven, {len(text)} tekens")

import glob
pngs = glob.glob(os.path.join(OUT, "*.png"))
print(f"PNG's geschreven: {len(pngs)}")
for p in sorted(pngs):
    print(" ", p)

docx_path = os.path.join(OUT, "pyrox_report.docx")
# [2026-11-26] The Word export is built in Python (python-docx) by default; no
# Node.js needed. Check that it opens and holds the report's tables and images.
export_report_docx(text, docx_path, report_kind="facts", event_name="TestCity heatwave")
print("Word-document geschreven:", docx_path)
import docx as _docx
_d = _docx.Document(docx_path)
_n_tab, _n_img = len(_d.tables), len(_d.inline_shapes)
print(f"Word: {_n_tab} tabellen, {_n_img} afbeeldingen, {len(_d.paragraphs)} alinea's")
assert _n_tab > 0, "geen tabellen in het Word-rapport"
assert _n_img == len([l for l in text.splitlines() if l.strip().startswith("![")]), "aantal afbeeldingen klopt niet"
# The Node route stays available (THERMOPOULOS_DOCX_ENGINE=node); test it when
# 'npm install' was done here (CI does so).
_here = os.path.dirname(os.path.abspath(__file__))
if os.path.isfile(os.path.join(_here, "node_modules", "docx", "package.json")):
    os.environ["THERMOPOULOS_DOCX_ENGINE"] = "node"
    try:
        export_report_docx(text, docx_path.replace(".docx", "_node.docx"), report_kind="facts",
                           event_name="TestCity heatwave")
        print("Word-document (Node-route) geschreven")
    finally:
        os.environ.pop("THERMOPOULOS_DOCX_ENGINE", None)
elif os.environ.get("HESTIA_REQUIRE_DOCX"):
    raise SystemExit("HESTIA_REQUIRE_DOCX set but node_modules/docx missing")
