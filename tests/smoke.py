"""Smoke regression: build two parts in a running Inventor and check their volume.

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
