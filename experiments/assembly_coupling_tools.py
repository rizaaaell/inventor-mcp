"""Phase 3 acceptance: the flange coupling rebuilt only through the MCP assembly tools.

Run from the repo root:  python -X utf8 -u experiments/assembly_coupling_tools.py
Needs Flens.ipt and Poros.ipt in C:\\inventor-test\\coupling\\ and writes
Kopling_Flens_tools.iam plus Kopling_Flens_tools.constraints.json next to them.
Fasteners come from Content Center (DIN 933, DIN 934, DIN 125-1 A). One bolt set is
constrained at the hole on +X, then patterned four times about the flange axis.
"""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import src.server as srv  # noqa: E402

PART_DIR = Path(r"C:\inventor-test\coupling")
OUT = PART_DIR / "Kopling_Flens_tools.iam"
FLANGE, SHAFT = PART_DIR / "Flens.ipt", PART_DIR / "Poros.ipt"
BOLT = ("Fasteners/Bolts/Hex Head", "DIN 933", "M10 x 60")
NUT = ("Fasteners/Nuts/Hex", "DIN 934", "M10")
WASHER = ("Fasteners/Washers/Plain", "DIN 125-1 A", "A 10.5")
files = {}


def placed(out):
    print(out)
    name = re.match(r"Placed (.+?)( \(grounded\))?: origin", out).group(1)
    if "| file " in out:
        files[Path(out.split("| file ")[1]).name] = name
    return name


def place(path, x=0, y=0, z=0, flip=False, grounded=False):
    return placed(srv.place_component(str(path), x, y, z, rx=180 if flip else 0, grounded=grounded))


def place_cc(part, x, y, z):
    return placed(srv.place_content_center(*part, x=x, y=y, z=z))


def constrain(*args, **kwargs):
    out = srv.add_constraint(*args, **kwargs)
    print("  ", out)
    if "(healthy)" not in out:
        raise RuntimeError(out)


print(srv.connect())
for doc in list(srv.inv.app.Documents):
    if doc.FullFileName.lower() == str(OUT).lower():
        doc.Close(True)  # a previous run's assembly would block the save
print(srv.create_assembly())
print(srv.transaction("begin", "Coupling from tools"))
try:
    flange_a = place(FLANGE, grounded=True)
    flange_b = place(FLANGE, 15, 10, -40, flip=True)
    constrain("insert", flange_a, "circle:0,0,0,15", flange_b, "circle:0,0,0,15")
    # Insert leaves rotation about the bore free; the XZ planes line up the bolt holes.
    constrain("mate", flange_a, "plane:XZ", flange_b, "plane:XZ")

    for flange, z, flip in ((flange_a, 80, False), (flange_b, -80, True)):
        shaft = place(SHAFT, 20, 15, z, flip=flip)
        # Negative offset puts the shaft end 40 mm inside the hub.
        constrain("insert", flange, "circle:0,0,50,15", shaft, "circle:0,0,0,15", offset=-40)
        constrain("flush", flange, "plane:XZ", shaft, "plane:XZ")

    # Content Center parts run along their X axis with the seating face on x = 0.
    # Their XY plane contains that axis, so flushing it to the flange XZ plane stops the spin.
    head_washer = place_cc(WASHER, 53, 6, 35)
    constrain("insert", flange_a, "circle:45,0,20,5.5", head_washer, "circle:0,0,0,5.25")
    constrain("flush", flange_a, "plane:XZ", head_washer, "plane:XY")
    bolt = place_cc(BOLT, 53, 6, 60)
    constrain("insert", head_washer, "circle:2,0,0,5.25", bolt, "circle:0,0,0,7.7")
    constrain("flush", flange_b, "plane:XZ", bolt, "plane:XY")
    nut_washer = place_cc(WASHER, 53, 6, -35)
    constrain("insert", flange_b, "circle:45,0,20,5.5", nut_washer, "circle:0,0,0,5.25")
    constrain("flush", flange_b, "plane:XZ", nut_washer, "plane:XY")
    nut = place_cc(NUT, 53, 6, -50)
    constrain("insert", nut_washer, "circle:2,0,0,5.25", nut, "circle:0,0,0,7.65")
    constrain("flush", flange_b, "plane:XZ", nut, "plane:XY")

    print(srv.pattern_component(", ".join((head_washer, bolt, nut_washer, nut)), flange_a, "axis:Z", 4))
    print(srv.transaction("commit"))
except Exception:
    print(srv.transaction("abort"))
    raise

print(srv.save_document(str(OUT)))
print("BOM structured:", srv.get_bom("structured"))
print("Occurrences:", srv.list_occurrences())

bom = {row["file"]: row["quantity"] for row in json.loads(srv.get_bom("parts"))}
by_name = {v.split(":")[0]: k for k, v in files.items()}
expected = {FLANGE.name: 2, SHAFT.name: 2,
            by_name[bolt.split(":")[0]]: 4, by_name[nut.split(":")[0]]: 4,
            by_name[head_washer.split(":")[0]]: 8}
dof = json.loads(srv.get_dof())
clashes = json.loads(srv.analyze_interference())
print("BOM parts only:", bom)
print("Free DOF:", dof["with_free_dof"])
print("Interference:", json.dumps(clashes, indent=1, ensure_ascii=False))
bolt_nut = {srv.inv._cc_key(bolt.split(":")[0]), srv.inv._cc_key(nut.split(":")[0])}
pairs_ok = all({srv.inv._cc_key(c["first"].split(":")[0]), srv.inv._cc_key(c["second"].split(":")[0])}
               == bolt_nut and c["cause"].startswith("thread artifact") for c in clashes)
print("BOM ok:", bom == expected, "| DOF 0:", dof["fully_constrained"],
      "| only bolt-nut thread artifacts:", pairs_ok and len(clashes) == 4)
