"""Weldment acceptance: a welded L bracket and its drawing, built only through MCP tools.

Run from the repo root:  python -X utf8 -u experiments/weldment_bracket.py
Writes C:\\inventor-test\\weld\\: Base_Plate.ipt, Upright_Plate.ipt, Bracket_Weldment.iam
and Bracket_Weldment_A3.idw, .png, .pdf.

A 60 x 60 x 10 upright plate stands on a 100 x 60 x 10 base plate, fillet welded along
both sides (a4, leg 6). A weldment drawing shows the assembled bracket, not an exploded
one: front and side views, an iso view, the welding symbol, parts list and balloons.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import src.server as srv  # noqa: E402

W = Path(r"C:\inventor-test\weld")
W.mkdir(parents=True, exist_ok=True)
BASE, UPRIGHT = W / "Base_Plate.ipt", W / "Upright_Plate.ipt"
ASM, IDW = W / "Bracket_Weldment.iam", W / "Bracket_Weldment_A3.idw"

print(srv.connect())
srv.inv.close_documents_in(str(W))

for path, width, height, number, text in ((BASE, 100, 60, "WB-001", "Base plate 100x60x10"),
                                          (UPRIGHT, 60, 60, "WB-002", "Upright plate 60x60x10")):
    print(srv.create_part(path.stem))
    print(srv.create_sketch("XY"))
    print(srv.draw_rectangle(0, 0, width, height))
    print(srv.extrude(10))
    print(srv.save_document(str(path)))
    print(srv.set_properties(str(path), json.dumps({"Part Number": number, "Description": text,
                                                    "MATERIAL": "Steel"})))
    srv.inv.close_documents_in(str(W))

print(srv.create_weldment())
print(srv.place_component(str(BASE), grounded=True))
print(srv.place_component(str(UPRIGHT), 0, 0, 60, rx=90))
# The upright's -Y side face sits on the base; its thickness runs along X from 0 to 10.
print(srv.add_constraint("mate", "Base_Plate:1", "face:0,0,10", "Upright_Plate:1", "face:0,-30,5"))
print(srv.add_constraint("flush", "Base_Plate:1", "plane:YZ", "Upright_Plate:1", "plane:XY"))
print(srv.add_constraint("flush", "Base_Plate:1", "plane:XZ", "Upright_Plate:1", "plane:YZ"))
print(srv.get_dof())
# Fillets along both long edges where the upright meets the base.
print(srv.add_cosmetic_weld("Upright_Plate:1", "edge:0,-30,0; edge:0,-30,10", leg=6))
print(srv.analyze_interference())
print(srv.save_document(str(ASM)))

print(srv.create_drawing())
front = (out := srv.add_base_view(str(ASM), 120, 180, 1)).split()[2].rstrip(":"); print(out)
print(srv.add_projected_view(front, 240, 180))
print(srv.add_base_view(str(ASM), 340, 230, 0.5, "iso_top_right"))
# In the front view the joint sits at x 0 and x 10, 25 mm under the view centre.
print(srv.add_weld_symbol(front, 0, -24, -45, 25, "fillet", "a4", sides="both", tail="135"))
print(srv.add_parts_list(front))
print(srv.add_balloons(front))
print(srv.set_title_block(json.dumps({"TITLE": "Welded Bracket", "PART NUMBER": "WB-000",
                                      "ENGINEER": "Rizal", "REVISION NUMBER": "1"})))
print(json.dumps(json.loads(srv.list_views())["problems"]))
print(srv.save_document(str(IDW)))
print(srv.export_sheet_png(str(W / "Bracket_Weldment_A3.png"), 2400))
print(srv.export_pdf(str(W / "Bracket_Weldment_A3.pdf")))
