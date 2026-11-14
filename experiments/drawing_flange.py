"""Phase 2 acceptance drawing: coupling flange on A3, built only through the MCP tools.

Run from the repo root:  python -X utf8 -u experiments/drawing_flange.py
Needs C:\\inventor-test\\coupling\\Flens.ipt from the coupling test. Writes
Flens_A3.idw, .png and .pdf to C:\\inventor-test\\drawing\\.

Layout (sheet mm, third angle, default Arjuna profile): front view (looking along the
flange axis) left, top view above it, section A-A through the two bolt holes on x = 0
to its right, isometric view top right as in the Arjuna baseline drawings.
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
print(srv.create_drawing())
front = view_name(out := srv.add_base_view(MODEL, 115, 150)); print(out)
top = view_name(out := srv.add_projected_view(front, 115, 250)); print(out)
section = view_name(out := srv.add_section_view(front, 0, -70, 0, 70, 255, 150, "A")); print(out)
print(srv.add_base_view(MODEL, 350, 220, 0.5, "iso_top_right"))
for v in (front, top, section):
    print(srv.add_centerlines(v))
for v in (front, top):
    print(srv.retrieve_dimensions(v))

# The hole note replaces the retrieved Ø11, and the chamfer is already shown in the top view.
duplicates = [d["index"] for d in json.loads(srv.list_dimensions())
              if d["view"] == front and d["text"] in ("n11", "1")]
print(srv.delete_dimension(",".join(map(str, duplicates))))
print(srv.add_hole_note(front, 0, 50.5, -62, 68))
print(srv.add_dimension(front, "pcd", 0, -45, text_x=-58, text_y=-72))

# Tolerances and GD&T. These are proposals for a shaft coupling flange, not values
# from a released design: bore H7 on the shaft, mating face A, bore axis B; face A flat
# and square to the bore, bolt holes located from A and B.
bore = next(d["index"] for d in json.loads(srv.list_dimensions()) if d["view"] == front and d["text"] == "n30")
print(srv.set_tolerance(bore, "fit", fit="H7"))
print(srv.move_dimension(bore, 62, -75))
print(srv.add_datum(section, 25, 40, "A", 42, 62))
print(srv.add_datum(section, -12, -15, "B", -50, -8))  # leader enters through the open bore
print(srv.add_gdt(section, 25, -40, 45, -72, "flatness", 0.03))
print(srv.add_gdt(section, 25, -48, 45, -84, "perpendicularity", 0.05, "B"))
print(srv.add_gdt(front, 0, 50.5, -78, 58, "position", 0.2, "A,B", diameter_zone=True))
print(srv.add_surface_finish(section, 25, -10, 50, -20, "Ra 3,2"))
print(srv.add_surface_finish(section, -12, 15, -50, 12, "Ra 1,6"))

print(srv.set_title_block(json.dumps({
    "TITLE": "Flens Kopling",
    "PART NUMBER": "KF-001",
    "ENGINEER": "Rizal",
    "REVISION NUMBER": "1",
    "MATERIAL": "Aluminum 6061",
    "SURFACE FINISH": "Ra 6,3",
})))
layout = json.loads(srv.list_views())
print("problems:", layout["problems"] or "none")
print(srv.save_document(str(OUT / "Flens_A3.idw")))
print(srv.export_sheet_png(str(OUT / "Flens_A3.png")))
print(srv.export_pdf(str(OUT / "Flens_A3.pdf")))
