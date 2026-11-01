# -*- coding: utf-8 -*-
"""
test_fit_lezer.py -- controles voor fit_lezer.py.

FIT-bestanden van deelnemers horen NIET in de suite. Geef daarom een eigen
bestand op via de omgevingsvariabele FIT_TEST_BESTAND; zonder die variabele
worden alleen de bestandsonafhankelijke controles gedaan.

    set FIT_TEST_BESTAND=C:\\pad\\naar\\bestand.fit   (Windows)
    PYTHONPATH=. python3 test_fit_lezer.py
"""
import os, sys, tempfile
from pathlib import Path
import fit_lezer as fl

FOUT = []
def check(naam, ok, info=""):
    print(f"[{'OK ' if ok else 'FOUT'}] {naam}" + (f"  ({info})" if info else ""))
    if not ok:
        FOUT.append(naam)

VERBODEN = ("position_lat", "position_long", "serial_number", "user_profile", "hrv")
check("geen GPS of serienummer op de toegestane lijst",
      not any(v in fl.TOEGESTAAN for v in VERBODEN))

pad = os.environ.get("FIT_TEST_BESTAND")
if pad and Path(pad).is_file():
    rit = fl.lees_fit(pad, "T01")
    kol = set(rit.data.columns)
    check("alleen toegestane kolommen", kol <= set(fl.TOEGESTAAN.values()) | {"t_s", "t_min", "hoogteverschil_m", "core_niveau", "core_hartslag_gebruikt"}, str(sorted(kol)))
    check("tijd begint bij 0 s", rit.data.t_s.iloc[0] == 0)
    check("geen absolute tijdstempel in de data", "timestamp" not in kol)
    with tempfile.TemporaryDirectory() as d:
        uit = fl.exporteer(rit, d)
        namen = " ".join(p.name for p in uit.values())
        check("uitvoernamen gebruiken de code", all(p.name.startswith("T01_") for p in uit.values()), namen)
        tekst = Path(uit["csv"]).read_text(encoding="utf-8", errors="ignore")
        check("geen e-mailadres in de CSV", "@" not in tekst)
else:
    print("(FIT_TEST_BESTAND niet gezet: bestandscontroles overgeslagen)")



def test_fit_lezer():
    """[2026-10-17] pytest entry point: the checks above ran at import."""
    assert not FOUT, FOUT


if __name__ == "__main__":
    # [2026-10-17] Was an unconditional sys.exit() at module level, which made
    # pytest abort during collection ("INTERNALERROR").
    print("\nALLES OK" if not FOUT else f"\n{len(FOUT)} FOUT(EN)")
    sys.exit(1 if FOUT else 0)
