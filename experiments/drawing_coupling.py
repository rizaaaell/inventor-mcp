"""Phase 4 acceptance drawing: the flange coupling assembly on A3, built only through MCP tools.

Run from the repo root:  python -X utf8 -u experiments/drawing_coupling.py
Needs C:\\inventor-test\\coupling\\Kopling_Flens_tools.iam from
experiments/assembly_coupling_tools.py. Writes Kopling_Flens_A3.idw, .png and .pdf
to C:\\inventor-test\\drawing\\.

Layout (sheet mm, third angle): end view of the coupling left, section A-A through the
shaft axis and two bolts to its right with balloons above and below, isometric view top
right, parts list on the title block as in the Arjuna assembly drawings.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import src.server as srv  # noqa: E402

MODEL = r"C:\inventor-test\coupling\Kopling_Flens_tools.iam"
OUT = Path(r"C:\inventor-test\drawing")
OUT.mkdir(parents=True, exist_ok=True)
IDW = OUT / "Kopling_Flens_A3.idw"


def view_name(result: str) -> str:
    return result.split()[2].rstrip(":")


print(srv.connect())
srv.inv.close_documents_in(str(OUT))  # a previous run's drawing would block the save below
print(srv.create_drawing())
front = view_name(out := srv.add_base_view(MODEL, 70, 190, 0.5)); print(out)
# Shafts cut along their axis are drawn unhatched; the fasteners are standard parts.
section = view_name(out := srv.add_section_view(front, 0, -70, 0, 70, 215, 190, "A",
                                                no_hatch="Poros:1, Poros:2")); print(out)
print(srv.add_base_view(MODEL, 350, 225, 0.3, "iso_top_right"))
for v in (front, section):
    print(srv.add_centerlines(v))
print(srv.add_parts_list(section))
print(srv.add_balloons(section))
print(srv.set_title_block(json.dumps({"TITLE": "Kopling Flens Assembly", "PART NUMBER": "KF-000",
                                      "ENGINEER": "Rizal", "REVISION NUMBER": "1"})))
print(srv.list_views())
print(srv.save_document(str(IDW)))
print(srv.export_sheet_png(str(OUT / "Kopling_Flens_A3.png"), 2400))
print(srv.export_pdf(str(OUT / "Kopling_Flens_A3.pdf")))
