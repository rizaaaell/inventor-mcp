"""Flange coupling assembly, built through execute_python on Inventor 2027.1.

Record of the code that worked, kept as a reference for future assembly tools.
Expects the five part files in PART_DIR (built beforehand with the MCP part
tools) and writes Kopling_Flens.iam next to them.

Result of the original run: 20 occurrences, 38 constraints, 0 free DOF,
4 interferences (bolt shank vs. tapped nut bore, 187.51 mm3 each).

No assembly call failed during that run. The comments mark the API behaviour
that had to be probed first and the one slip made while building the parts.
"""

import math

# execute_python pre-binds app and tg; bind them here when run as a plain script.
if "app" not in globals():
    import win32com.client

    app = win32com.client.GetActiveObject("Inventor.Application")
    tg = app.TransientGeometry

PART_DIR = "C:\\inventor-test\\coupling\\"

K_ASSEMBLY_DOCUMENT = 12291
K_CIRCLE_CURVE = 5124
K_HEALTHY = 11778


def placement(dx=0, dy=0, dz=0, flip_x=False):
    """Rough starting pose in mm. Constraints do the real positioning."""
    m = tg.CreateMatrix()
    if flip_x:
        m.SetToRotation(math.pi, tg.CreateVector(1, 0, 0), tg.CreatePoint(0, 0, 0))
    # SetTranslation keeps the rotation part of the matrix.
    m.SetTranslation(tg.CreateVector(dx / 10, dy / 10, dz / 10))
    return m


def circ_edge(occ, center, radius, tol=0.01):
    """Circular edge of an occurrence, picked by its center and radius in part space (mm).

    occ.SurfaceBodies already returns proxies, so the edge can go straight into
    a constraint. NativeObject gives part coordinates that do not move with the
    occurrence.
    """
    edges = occ.SurfaceBodies.Item(1).Edges
    for i in range(1, edges.Count + 1):
        e = edges.Item(i)
        if e.GeometryType != K_CIRCLE_CURVE:
            continue
        g = e.NativeObject.Geometry
        if (
            abs(g.Radius * 10 - radius) < tol
            and abs(g.Center.X * 10 - center[0]) < tol
            and abs(g.Center.Y * 10 - center[1]) < tol
            and abs(g.Center.Z * 10 - center[2]) < tol
        ):
            return e
    raise LookupError(f"no circular edge at {center} r={radius} in {occ.Name}")


def origin_plane(occ, index):
    """Origin work plane of an occurrence as a proxy. 1 = YZ, 2 = XZ, 3 = XY.

    Under pywin32 late binding CreateGeometryProxy returns the proxy directly
    instead of filling an out-parameter.
    """
    return occ.CreateGeometryProxy(occ.Definition.WorkPlanes.Item(index))


def pose(occ):
    t = occ.Transformation
    origin = [round(t.Cell(r, 4) * 10, 3) for r in (1, 2, 3)]
    z_axis = [round(t.Cell(r, 3), 3) for r in (1, 2, 3)]
    return f"{occ.Name} origin={origin} Z={z_axis}"


asm = app.Documents.Add(
    K_ASSEMBLY_DOCUMENT,
    app.FileLocations.TemplatesPath + "Metric\\Standard (mm).iam",
    True,
)
ad = asm.ComponentDefinition
constraints = ad.Constraints
tm = app.TransactionManager


# Flanges: A is grounded, B is flipped so the disk faces meet and the hubs point outward.
tx = tm.StartTransaction(asm, "Flens A+B")
try:
    flange_a = ad.Occurrences.Add(PART_DIR + "Flens.ipt", placement())
    flange_a.Grounded = True
    flange_b = ad.Occurrences.Add(PART_DIR + "Flens.ipt", placement(15, 10, -40, flip_x=True))

    c = constraints.AddInsertConstraint(
        circ_edge(flange_a, (0, 0, 0), 15), circ_edge(flange_b, (0, 0, 0), 15), True, 0
    )
    c.Name = "Insert_FlensA_FlensB"
    # Insert leaves rotation about the bore free; the XZ planes line up the bolt holes.
    c = constraints.AddMateConstraint(origin_plane(flange_a, 2), origin_plane(flange_b, 2), 0)
    c.Name = "Mate_XZ_FlensA_FlensB"
    tx.End()
except Exception:
    tx.Abort()
    raise
print(pose(flange_b))


def add_shaft(label, flange, start):
    tx = tm.StartTransaction(asm, label)
    try:
        shaft = ad.Occurrences.Add(PART_DIR + "Poros.ipt", start)
        # Offset is in cm. Negative puts the shaft end 40 mm inside the hub face;
        # +4.0 would leave it 40 mm outside.
        c = constraints.AddInsertConstraint(
            circ_edge(flange, (0, 0, 50), 15), circ_edge(shaft, (0, 0, 0), 15), True, -4.0
        )
        c.Name = f"Insert_{label}"
        c = constraints.AddFlushConstraint(origin_plane(flange, 2), origin_plane(shaft, 2), 0)
        c.Name = f"Flush_XZ_{label}"
        tx.End()
    except Exception:
        tx.Abort()
        raise
    print(pose(shaft))
    return shaft


shaft_a = add_shaft("Poros_A", flange_a, placement(20, 15, 80))
shaft_b = add_shaft("Poros_B", flange_b, placement(20, -15, -80, flip_x=True))


placed = {}


def place(label, filename, start, seat_edge, own_center, own_radius, lock_ref, lock_plane):
    """One fastener: an insert seats it, a flush between origin planes stops it spinning."""
    tx = tm.StartTransaction(asm, label)
    try:
        occ = ad.Occurrences.Add(PART_DIR + filename, start)
        c = constraints.AddInsertConstraint(
            seat_edge, circ_edge(occ, own_center, own_radius), True, 0
        )
        c.Name = f"Insert_{label}"
        c = constraints.AddFlushConstraint(
            origin_plane(lock_ref, lock_plane), origin_plane(occ, lock_plane), 0
        )
        c.Name = f"Flush_{label}"
        tx.End()
    except Exception:
        tx.Abort()
        raise
    placed[label] = occ
    print(label, "|", pose(occ))
    return occ


# Bolt holes on PCD 90. Flange B is flipped about X, so its hole at assembly
# (x, y) sits at (x, -y) in its own part space.
for i, (x, y) in enumerate([(45, 0), (0, 45), (-45, 0), (0, -45)], 1):
    # The lock plane has to contain the hole axis: XZ for holes on the X axis, YZ otherwise.
    lock_plane = 2 if y == 0 else 1

    head_washer = place(
        f"RingKepala_{i}", "Ring_DIN125_M10.ipt", placement(x + 8, y + 6, 35),
        circ_edge(flange_a, (x, y, 20), 5.5), (0, 0, 0), 5.25, flange_a, lock_plane,
    )
    # The bolt seats on the edge where the shank meets the underside of the head.
    place(
        f"Baut_{i}", "Baut_DIN933_M10x60.ipt", placement(x + 8, y + 6, 60, flip_x=True),
        circ_edge(head_washer, (0, 0, 2), 5.25), (0, 0, 6.4), 5.0, flange_b, lock_plane,
    )
    nut_washer = place(
        f"RingMur_{i}", "Ring_DIN125_M10.ipt", placement(x + 8, y + 6, -35, flip_x=True),
        circ_edge(flange_b, (x, -y, 20), 5.5), (0, 0, 0), 5.25, flange_b, lock_plane,
    )
    # r=7 is where the nut's chamfer cone meets its flat face.
    place(
        f"Mur_{i}", "Mur_DIN934_M10.ipt", placement(x + 8, y + 6, -50, flip_x=True),
        circ_edge(nut_washer, (0, 0, 2), 5.25), (0, 0, 0), 7.0, flange_b, lock_plane,
    )

asm.Update()
asm.SaveAs(PART_DIR + "Kopling_Flens.iam", False)


unhealthy = [
    (constraints.Item(i).Name, constraints.Item(i).HealthStatus)
    for i in range(1, constraints.Count + 1)
    if constraints.Item(i).HealthStatus != K_HEALTHY
]
print("occurrences", ad.Occurrences.Count, "constraints", constraints.Count, "unhealthy", unhealthy)

# GetDegreesOfFreedom comes back as a tuple:
# (translation count, translation vectors, rotation count, rotation vectors, center).
for i in range(1, ad.Occurrences.Count + 1):
    occ = ad.Occurrences.Item(i)
    dof = occ.GetDegreesOfFreedom()
    print(occ.Name, "grounded" if occ.Grounded else "", "trans", dof[0], "rot", dof[2])

# Confirms the DOF readout reacts: with its flush suppressed the last nut shows 1 rotation.
last = constraints.Item(constraints.Count)
last.Suppressed = True
asm.Update()
dof = placed["Mur_4"].GetDegreesOfFreedom()
print("suppressed", last.Name, "-> trans", dof[0], "rot", dof[2])
last.Suppressed = False
asm.Update()

everything = app.TransientObjects.CreateObjectCollection()
for i in range(1, ad.Occurrences.Count + 1):
    everything.Add(ad.Occurrences.Item(i))
# The bolt shank is a plain 10 mm cylinder and the nut bore is modeled at the
# 8.376 mm minor diameter, so every bolt/nut pair overlaps by 187.51 mm3.
results = ad.AnalyzeInterference(everything)
print("interferences", results.Count)
for i in range(1, results.Count + 1):
    r = results.Item(i)
    p = r.Centroid
    print(
        f"{r.OccurrenceOne.Name} <-> {r.OccurrenceTwo.Name}  "
        f"V={r.Volume * 1000:.2f} mm3  at ({p.X * 10:.1f}, {p.Y * 10:.1f}, {p.Z * 10:.1f})"
    )

asm.Save()

# Slip while building Flens.ipt: list_edges(min_length=300) returned nothing,
# because closed circular edges report length 0. The chamfer edges were picked
# from an unfiltered list instead.
