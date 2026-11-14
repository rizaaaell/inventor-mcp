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
# Hidden lines in the top view show the bolt holes and the bore through the part.
top = view_name(out := srv.add_projected_view(front, 115, 255, style="hidden")); print(out)
section = view_name(out := srv.add_section_view(front, 0, -70, 0, 70, 255, 150, "A")); print(out)
print(srv.add_base_view(MODEL, 350, 220, 0.5, "iso_top_right"))
for v in (front, top, section):
    print(srv.add_centerlines(v))
# Lengths come from the model in the top view; its diameters are drawn in the section
# instead, and only the chamfer on the right-hand stack is kept.
print(srv.retrieve_dimensions(top))
top_right = srv.inv._view_rect(srv.inv._view(top))[2]
drop = [d["index"] for d in json.loads(srv.list_dimensions()) if d["view"] == top
        and (d["text"].startswith("n") or (d["text"] == "1" and d["text_mm"][0] < top_right))]
print(srv.delete_dimension(",".join(map(str, drop))))

# Section A-A (hub left, x -25..5; disk right, x 5..25; bore ±15, hub ±30, disk ±60):
# diameters of the turned part as Ø-prefixed linear dimensions, stacked outside on the left.
print(srv.add_dimension(section, "vertical", -15, 15, -15, -15, text_x=-37, text_y=0, prefix="Ø"))
print(srv.add_dimension(section, "vertical", -15, 30, -15, -30, text_x=-47, text_y=0, prefix="Ø"))
print(srv.add_dimension(section, "vertical", 15, 60, 15, -60, text_x=-57, text_y=0, prefix="Ø"))

# Front view: only what the circular view shows best, the bolt circle and the holes.
print(srv.add_hole_note(front, 0, 50.5, -55, 72))
print(srv.add_dimension(front, "pcd", 0, -45, text_x=-58, text_y=-72))
# Hole spacing from the bore center, outside the flange rim.
print(srv.add_dimension(front, "angle", 45, 0, 0, 45, text_x=50, text_y=50, vertex_x=15, vertex_y=0))

# Tolerances and GD&T. These are proposals for a shaft coupling flange, not values
# from a released design: bore H7 on the shaft, mating face A, bore axis B; face A flat
# and square to the bore, bolt holes located from A and B.
bore = next(d["index"] for d in json.loads(srv.list_dimensions())
            if d["view"] == section and d["text"].startswith("Ø30"))
print(srv.set_tolerance(bore, "fit", fit="H7"))
# The position tolerance locates the holes from basic (exact, boxed) PCD and spacing.
for d in json.loads(srv.list_dimensions()):
    if d["view"] == front and (d["text"] == "n90" or d["text"].endswith("°")):
        print(srv.set_tolerance(d["index"], "basic"))
print(srv.add_gdt(front, 0, 0, -52, 63, "position", 0.2, "A,B", diameter_zone=True, leader=False))
print(srv.add_datum(section, 25, 40, "A", 42, 62))
# On the extension line of Ø30 H7 the triangle makes the bore axis the datum.
print(srv.add_datum(section, -31, -15, "B", -31, -23, attach=False))
print(srv.add_surface_finish(section, -29, 15, -29, 24, "Ra 1,6", attach=False))
print(srv.add_gdt(section, 25, -40, 45, -72, "flatness", 0.03))
print(srv.add_gdt(section, 25, -48, 45, -84, "perpendicularity", 0.05, "B"))
print(srv.add_surface_finish(section, 25, -10, 50, -20, "Ra 3,2"))

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
