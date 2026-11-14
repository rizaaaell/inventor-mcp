"""Phase 5 acceptance drawing: exploded flange coupling on A3, built only through MCP tools.

Run from the repo root:  python -X utf8 -u experiments/drawing_coupling_exploded.py
Needs C:\\inventor-test\\coupling\\Kopling_Flens_tools.iam from
experiments/assembly_coupling_tools.py. Writes Kopling_Flens_exploded.iam (a copy with
the components moved apart) and Kopling_Flens_exploded_A3.idw, .png and .pdf.

Flens:1 stays; everything else moves along the coupling axis (Z) in assembly order:
head washers then bolts to +Z, Flens:2 then its washers then the nuts to -Z, and each
shaft out of its hub. The iso view is turned 30 degrees about the axis so the four
bolt lines do not overlap in pairs.
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
WASHER = "DIN 125-1 A A 10,5"
BOLT = "DIN 933 - replaced by DIN EN 24017 M10  x 60"
NUT = "DIN 934 - replaced by DIN EN 24032/28673/28674 M10"


def names(base, numbers):
    return ", ".join(f"{base}:{n}" for n in numbers)


print(srv.connect())
srv.inv.close_documents_in(str(OUT))  # drawings of the copy first, they use it
srv.inv.close_documents_in(str(PART_DIR))
print(srv.create_exploded_copy(str(SOURCE), str(COPY)))

# Washers 1, 3, 5, 7 sit under the bolt heads (Flens:1 side), 2, 4, 6, 8 under the nuts.
print(srv.explode_components(names(WASHER, (1, 3, 5, 7)), dz=40))
print(srv.explode_components(names(BOLT, (1, 2, 3, 4)), dz=120))
print(srv.explode_components("Flens:2", dz=-40))
print(srv.explode_components(names(WASHER, (2, 4, 6, 8)), dz=-70))
print(srv.explode_components(names(NUT, (1, 2, 3, 4)), dz=-100))
print(srv.explode_components("Poros:1", dz=60))
print(srv.explode_components("Poros:2", dz=-100))
print(srv.save_document(""))

print(srv.create_drawing())
view = (out := srv.add_base_view(str(COPY), 160, 165, 0.5, "iso_top_right", spin=30)).split()[2].rstrip(":")
print(out)
print(srv.add_explode_trails(view))
print(srv.add_parts_list(view))
print(srv.add_balloons(view))
print(srv.set_title_block(json.dumps({"TITLE": "Kopling Flens Exploded", "PART NUMBER": "KF-000-E",
                                      "ENGINEER": "Rizal", "REVISION NUMBER": "1"})))
print(json.dumps(json.loads(srv.list_views())["problems"]))
print(srv.save_document(str(IDW)))
print(srv.export_sheet_png(str(OUT / "Kopling_Flens_exploded_A3.png"), 2400))
print(srv.export_pdf(str(OUT / "Kopling_Flens_exploded_A3.pdf")))
