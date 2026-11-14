"""Phase 3 acceptance: the flange coupling rebuilt only through the MCP assembly tools.

Run from the repo root:  python -X utf8 -u experiments/assembly_coupling_tools.py
Needs the five part files in C:\\inventor-test\\coupling\\ and writes
Kopling_Flens_tools.iam plus Kopling_Flens_tools.constraints.json next to them.
Same constraint scheme as assembly_coupling.py, with geometry picked by selectors.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import src.server as srv  # noqa: E402

PART_DIR = Path(r"C:\inventor-test\coupling")
OUT = PART_DIR / "Kopling_Flens_tools.iam"
FLANGE, SHAFT = PART_DIR / "Flens.ipt", PART_DIR / "Poros.ipt"
BOLT, NUT, WASHER = (PART_DIR / f for f in
                     ("Baut_DIN933_M10x60.ipt", "Mur_DIN934_M10.ipt", "Ring_DIN125_M10.ipt"))


def place(path, x=0, y=0, z=0, flip=False, grounded=False):
    out = srv.place_component(str(path), x, y, z, rx=180 if flip else 0, grounded=grounded)
    print(out)
    return out.split()[1].rstrip(":")  # "Placed Flens:1 (grounded): ..."


def constrain(*args, **kwargs):
    out = srv.add_constraint(*args, **kwargs)
    print("  ", out)
    if "healthy" not in out.split("(")[1]:
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

    # Flange B is flipped about X, so its hole at assembly (x, y) is (x, -y) in its part space.
    for x, y in ((45, 0), (0, 45), (-45, 0), (0, -45)):
        lock = "plane:XZ" if y == 0 else "plane:YZ"  # must contain the hole axis
        head_washer = place(WASHER, x + 8, y + 6, 35)
        constrain("insert", flange_a, f"circle:{x},{y},20,5.5", head_washer, "circle:0,0,0,5.25")
        constrain("flush", flange_a, lock, head_washer, lock)
        bolt = place(BOLT, x + 8, y + 6, 60, flip=True)
        constrain("insert", head_washer, "circle:0,0,2,5.25", bolt, "circle:0,0,6.4,5")
        constrain("flush", flange_b, lock, bolt, lock)
        nut_washer = place(WASHER, x + 8, y + 6, -35, flip=True)
        constrain("insert", flange_b, f"circle:{x},{-y},20,5.5", nut_washer, "circle:0,0,0,5.25")
        constrain("flush", flange_b, lock, nut_washer, lock)
        nut = place(NUT, x + 8, y + 6, -50, flip=True)
        constrain("insert", nut_washer, "circle:0,0,2,5.25", nut, "circle:0,0,0,7")
        constrain("flush", flange_b, lock, nut, lock)
    print(srv.transaction("commit"))
except Exception:
    print(srv.transaction("abort"))
    raise

print(srv.save_document(str(OUT)))
print("BOM parts only:", srv.get_bom("parts"))
print("BOM structured:", srv.get_bom("structured"))
print("DOF:", srv.get_dof())
print("Interference:", srv.analyze_interference())

bom = {row["file"]: row["quantity"] for row in json.loads(srv.get_bom("parts"))}
expected = {FLANGE.name: 2, SHAFT.name: 2, BOLT.name: 4, NUT.name: 4, WASHER.name: 8}
dof = json.loads(srv.get_dof())
clashes = json.loads(srv.analyze_interference())
pairs_ok = all({c["first"].split(":")[0], c["second"].split(":")[0]} ==
               {BOLT.stem, NUT.stem} and c["cause"].startswith("thread") for c in clashes)
print("BOM ok:", bom == expected, "| DOF 0:", dof["fully_constrained"],
      "| only bolt-nut thread artifacts:", pairs_ok and len(clashes) == 4)
