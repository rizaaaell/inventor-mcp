"""Smoke regression: build parts in a running Inventor and check volume and key sizes.

Run from the repo root:  python -X utf8 tests/smoke.py
Exits 1 if any case fails. Parts are closed without saving.
"""

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.inventor_api import InventorConnection  # noqa: E402

TOLERANCE = 0.001
K_CIRCLE_CURVE = 5124


def cylinder_volume(diameter, length):
    return math.pi * (diameter / 2) ** 2 * length


def build_cylinder(inv):
    inv.create_sketch("XY")
    inv.draw_circle(0, 0, 50)
    inv.extrude(10, "positive", "join")
    return cylinder_volume(50, 10)


def build_flange(inv):
    """Flange from the coupling test: disk 120x20, hub 60x30, bore 30, 4x11 on PCD 90."""
    inv.create_sketch("XY")
    inv.draw_circle(0, 0, 120)
    inv.extrude(20, "positive", "join")
    inv.create_sketch("XY")
    inv.draw_circle(0, 0, 60)
    inv.extrude(50, "positive", "join")
    inv.hole(x=0, y=0, diameter=30)
    inv.hole(x=45, y=0, diameter=11)
    inv.circular_pattern(feature_index=inv.list_features()[-1]["index"], count=4, axis="Z")

    # Edge indices shift between builds, so the two outer disk edges are found by radius.
    edges = inv.active_part().SurfaceBodies.Item(1).Edges
    outer = [
        i
        for i in range(1, edges.Count + 1)
        if edges.Item(i).GeometryType == K_CIRCLE_CURVE
        and abs(edges.Item(i).Geometry.Radius * 10 - 60) < 0.01
    ]
    inv.chamfer(1, edge_indices=outer)

    # A 1 mm chamfer removes a triangular ring: area 0.5 mm2, centroid at r = 60 - 1/3.
    chamfer_ring = 2 * math.pi * (60 - 1 / 3) * 0.5
    return (
        cylinder_volume(120, 20)
        + cylinder_volume(60, 30)
        - cylinder_volume(30, 50)
        - 4 * cylinder_volume(11, 20)
        - 2 * chamfer_ring
    )


def build_filleted_block(inv):
    """100x100x20 block, R5 fillet on the four vertical edges."""
    inv.create_sketch("XY")
    inv.draw_rectangle(0, 0, 100, 100)
    inv.extrude(20)
    corners = [inv.find_edge(x=sx * 50, y=sy * 50, z=10) for sx in (1, -1) for sy in (1, -1)]
    inv.fillet(5, corners)
    return 100 * 100 * 20 - 4 * (1 - math.pi / 4) * 5**2 * 20


def build_tapped_plate(inv):
    """30x30x8 plate with a through M10x1.5 tapped hole."""
    inv.create_sketch("XY")
    inv.draw_rectangle(0, 0, 30, 30)
    inv.extrude(8)
    inv.hole(0, 0, 10, 0, tapped=True)
    minor = 10 - 1.082532 * 1.5  # ISO 965 internal thread minor diameter, 8.376 mm
    return 30 * 30 * 8 - cylinder_volume(minor, 8)


def sheet_metal_case(inv):
    """100x60x2 plate with a 30 mm flange, then a flat pattern.

    Expected values come from the Default_mm sheet metal style in 2027.1
    (bend radius and K-factor), recorded during the phase 1 audit.
    """
    inv.create_part(name="smoke_sheet", template="sheet_metal")
    doc = inv.active_document()
    try:
        inv.set_sheet_metal_thickness(2)
        inv.create_sketch("XY")
        inv.draw_rectangle(0, 0, 100, 60)
        inv.sheet_metal_face()
        inv.flange([inv.find_edge(x=0, y=-30, z=2)], 30, 90)
        c = doc.ComponentDefinition
        volume = c.MassProperties.Volume * 1000
        c.Unfold()
        flat = (c.FlatPattern.Length * 10, c.FlatPattern.Width * 10)
        c.FlatPattern.ExitEdit()
    finally:
        doc.Close(True)
    for label, actual, expected in (
        ("volume", volume, 17342.5), ("flat length", flat[0], 100.0), ("flat width", flat[1], 86.5)
    ):
        error = abs(actual - expected) / expected
        assert error <= TOLERANCE, f"{label} {actual:.2f}, expected {expected}"
    return f"volume {volume:.1f} mm3, flat pattern {flat[0]:.1f} x {flat[1]:.1f} mm"


def drawing_case(inv):
    """A3 drawing of the coupling flange: views, section, dimensions, PDF."""
    import re
    out = Path(r"C:\inventor-test\smoke")
    out.mkdir(parents=True, exist_ok=True)
    pdf = out / "smoke_drawing.pdf"
    pdf.unlink(missing_ok=True)

    inv.create_part(name="smoke_drawing_part")
    part = inv.active_document()
    build_flange(inv)
    part_path = out / "smoke_drawing_part.ipt"
    if part_path.exists():
        part_path.unlink()
    part.SaveAs(str(part_path), False)

    inv.create_drawing()
    drawing = inv.active_document()
    try:
        front = inv.add_base_view(str(part_path), 110, 200).split()[2].rstrip(":")
        top = inv.add_projected_view(front, 110, 80).split()[2]
        section = inv.add_section_view(front, 0, -70, 0, 70, 250, 200, "A").split()[2]
        for v in (front, top, section):
            inv.add_centerlines(v)
            inv.retrieve_dimensions(v)
        layout = inv.list_views()
        texts = [d["text"] for d in inv.list_dimensions()]
        inv.export_pdf(str(pdf))
    finally:
        drawing.Close(True)
        part.Close(True)
    assert [v["name"] for v in layout["views"]] == [front, top, section], layout["views"]
    assert layout["dimensions"] == 8, f"{layout['dimensions']} dimensions, expected 8"
    assert not any(",00" in t for t in texts), f"trailing zeros despite the profile: {texts}"
    assert not layout["problems"], layout["problems"]
    box = re.search(rb"/MediaBox\s*\[0 0 (\d+) (\d+)\]", pdf.read_bytes())
    assert box and (int(box.group(1)), int(box.group(2))) == (1191, 842), "PDF is not one A3 landscape page"
    return f"3 views, 8 dimensions, no layout problems, A3 PDF {pdf.stat().st_size} bytes"


def volume_case(build):
    def case(inv):
        inv.create_part(name="smoke_volume")
        doc = inv.active_document()
        try:
            expected = build(inv)
            actual = doc.ComponentDefinition.MassProperties.Volume * 1000  # cm3 to mm3
        finally:
            doc.Close(True)
        error = abs(actual - expected) / expected
        detail = f"volume {actual:.1f} mm3, expected {expected:.1f} mm3, error {error:.4%}"
        assert error <= TOLERANCE, detail
        return detail

    return case


def pinned_document_case(inv):
    """Tools must keep acting on the part from create_part after another tab is activated."""
    inv.create_part(name="smoke_pin_first")
    first = inv.active_document()
    inv.create_part(name="smoke_pin_second")
    second = inv.active_document()
    try:
        first.Activate()  # what a click on the other document tab does
        target = inv.active_document()
        assert target.InternalName == second.InternalName, (
            f"tools followed the tab switch to {target.DisplayName}"
        )
        return f"target stayed {target.DisplayName} after switching tabs"
    finally:
        second.Close(True)
        first.Close(True)


CASES = [
    ("cylinder_d50x10", volume_case(build_cylinder)),
    ("coupling_flange", volume_case(build_flange)),
    ("fillet_block", volume_case(build_filleted_block)),
    ("tapped_hole_m10", volume_case(build_tapped_plate)),
    ("sheet_metal_flange", sheet_metal_case),
    ("flange_drawing", drawing_case),
    ("pinned_document", pinned_document_case),
]


def main():
    inv = InventorConnection()
    print(inv.connect())
    passed = 0
    for name, case in CASES:
        try:
            print(f"PASS  {name}: {case(inv)}")
            passed += 1
        except Exception as exc:
            print(f"FAIL  {name}: {type(exc).__name__}: {exc}")
    print(f"{passed}/{len(CASES)} passed")
    return 0 if passed == len(CASES) else 1


if __name__ == "__main__":
    sys.exit(main())
