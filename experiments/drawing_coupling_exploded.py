"""Assembly drawing of the flange coupling: exploded iso view on A3, built only through MCP tools.

Run from the repo root:  python -X utf8 -u experiments/drawing_coupling_exploded.py
Needs C:\\inventor-test\\coupling\\Kopling_Flens_tools.iam and its constraint log from
experiments/assembly_coupling_tools.py. Writes Kopling_Flens_exploded.iam (a copy with the
components moved apart) and Kopling_Flens_exploded_A3.idw, .png and .pdf.

auto_explode moves each component off the face it was constrained to, along the coupling
axis: head washers then bolts to +Z, Flens:2 then its washers then the nuts to -Z, each
shaft out of its hub; Flens:1 stays. The iso view is turned 30 degrees about the axis so
the four bolt lines do not overlap in pairs. MATERIAL fills itself: the parts differ, so it
gets the profile's statement.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import src.server as srv  # noqa: E402

PART_DIR = Path(r"C:\inventor-test\coupling")
SOURCE = PART_DIR / "Kopling_Flens_tools.iam"
COPY = PART_DIR / "Kopling_Flens_exploded.iam"
OUT = Path(r"C:\inventor-test\drawing")
OUT.mkdir(parents=True, exist_ok=True)
IDW = OUT / "Kopling_Flens_exploded_A3.idw"

print(srv.connect())
srv.inv.close_documents_in(str(OUT))  # drawings of the copy first, they use it
srv.inv.close_documents_in(str(PART_DIR))

# Part numbers and descriptions are what the parts list prints.
print(srv.set_properties(str(PART_DIR / "Flens.ipt"),
                         json.dumps({"Part Number": "KF-001", "Description": "Coupling flange"})))
print(srv.set_properties(str(PART_DIR / "Poros.ipt"),
                         json.dumps({"Part Number": "KF-002", "Description": "Shaft Ø30"})))
srv.inv.close_documents_in(str(PART_DIR))

print(srv.create_exploded_copy(str(SOURCE), str(COPY)))
print(srv.auto_explode(spacing=20, axis="Z"))
print(srv.save_document(""))

print(srv.create_drawing())
view = (out := srv.add_base_view(str(COPY), 160, 165, 0.5, "iso_top_right", spin=30)).split()[2].rstrip(":")
print(out)
print(srv.add_explode_trails(view))
print(srv.add_parts_list(view))
print(srv.add_balloons(view))
print(srv.set_title_block(json.dumps({"TITLE": "Kopling Flens Assembly", "PART NUMBER": "KF-000",
                                      "ENGINEER": "Rizal", "REVISION NUMBER": "1"})))
print(json.dumps(json.loads(srv.list_views())["problems"]))
print(srv.save_document(str(IDW)))
print(srv.export_sheet_png(str(OUT / "Kopling_Flens_exploded_A3.png"), 2400))
print(srv.export_pdf(str(OUT / "Kopling_Flens_exploded_A3.pdf")))
