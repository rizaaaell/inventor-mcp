"""Phase 2 acceptance drawing: coupling flange on A3, built only through the MCP tools.

Run from the repo root:  python -X utf8 -u experiments/drawing_flange.py
Needs C:\\inventor-test\\coupling\\Flens.ipt from the coupling test. Writes
Flens_A3.idw, .png and .pdf to C:\\inventor-test\\drawing\\.

Layout (sheet mm, first angle): front view (looking along the flange axis) top left,
top view below it, section A-A through the two bolt holes on x = 0 to its right.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import src.server as srv  # noqa: E402

MODEL = r"C:\inventor-test\coupling\Flens.ipt"
OUT = Path(r"C:\inventor-test\drawing")
OUT.mkdir(parents=True, exist_ok=True)


def view_name(result: str) -> str:
    # "Base view VIEW1: front, ..." / "Section view A from VIEW1: ..."
    return result.split()[2].rstrip(":")


print(srv.connect())
for doc in list(srv.inv.app.Documents):
    if doc.FullFileName.lower() == str(OUT / "Flens_A3.idw").lower():
        doc.Close(True)  # a previous run's drawing would block the save below
print(srv.create_drawing("iso", "A3"))
front = view_name(out := srv.add_base_view(MODEL, 110, 200)); print(out)
top = view_name(out := srv.add_projected_view(front, 110, 80)); print(out)
section = view_name(out := srv.add_section_view(front, 0, -70, 0, 70, 250, 200, "A")); print(out)
for v in (front, top, section):
    print(srv.add_centerlines(v))
for v in (front, top, section):
    print(srv.retrieve_dimensions(v))
print(srv.set_title_block(json.dumps({
    "title": "Flens kopling",
    "part_number": "KF-001",
    "description": "Flens kopling D120, 4x D11 PCD 90",
    "designer": "Rizal",
    "company": "Arjuna EV",
})))
layout = json.loads(srv.list_views())
print("problems:", layout["problems"] or "none")
print(srv.save_document(str(OUT / "Flens_A3.idw")))
print(srv.export_sheet_png(str(OUT / "Flens_A3.png")))
print(srv.export_pdf(str(OUT / "Flens_A3.pdf")))
