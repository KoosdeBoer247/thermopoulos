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
export_report_docx(text, docx_path, report_kind="facts", event_name="TestCity heatwave")
print("Word-document geschreven:", docx_path)
