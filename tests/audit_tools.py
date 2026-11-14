"""Exercise every MCP tool in src/server.py against a running Inventor.

Run from the repo root:  python -X utf8 -u tests/audit_tools.py
Calls the tool functions directly, the same code path the MCP server uses.
Saved and exported files go to C:\\inventor-test\\audit\\. Exits 1 on any FAIL.
WARN marks a tool that worked only after a workaround the caller has to know.
"""

import json
import math
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import src.server as srv  # noqa: E402

OUT = Path(r"C:\inventor-test\audit")
HEX_AREA = 3 * math.sqrt(3) / 2 * 10**2  # regular hexagon, circumradius 10
counts = {"PASS": 0, "WARN": 0, "FAIL": 0}
state: dict = {}


class Warn(Exception):
    """The tool worked, but not the way its docstring says."""


def check(name, fn):
    started = time.time()
    try:
        status, detail = "PASS", fn()
    except Warn as exc:
        status, detail = "WARN", str(exc)
    except Exception as exc:
        status, detail = "FAIL", f"{type(exc).__name__}: {exc}"
    counts[status] += 1
    print(f"{status}  {name} ({time.time() - started:.1f}s): {detail}", flush=True)


def comp():
    return srv.inv.active_document().ComponentDefinition


def vol():
    return comp().MassProperties.Volume * 1000


def last_feature():
    features = comp().Features
    return features.Item(features.Count)


def bbox():
    rb = comp().SurfaceBodies.Item(1).RangeBox
    lo, hi = rb.MinPoint, rb.MaxPoint
    return tuple(round(v * 10, 2) for v in (lo.X, hi.X, lo.Y, hi.Y, lo.Z, hi.Z))


def expect_delta(call, expected, tol=0.001):
    v0 = vol()
    out = call()
    dv = vol() - v0
    assert abs(dv - expected) <= tol * abs(expected) + 0.5, (
        f"volume change {dv:+.1f} mm3, expected {expected:+.1f} | {out}"
    )
    return f"dV {dv:+.1f} mm3 | {out}"


def edge_index(**coords):
    flags = {f"use_{k}": True for k in coords}
    return int(srv.find_edge(**coords, **flags).split()[1])


def close_active():
    srv.inv.active_document().Close(True)


def close_audit_files():
    """Close documents opened from OUT, e.g. the model a drawing view loaded."""
    for doc in list(srv.inv.app.Documents):
        if doc.FullFileName and Path(doc.FullFileName).parent == OUT:
            doc.Close(True)


def sketch_point_for_world(x, y, z):
    """Sketch coordinates (mm) of a world point, for sketches on body faces."""
    sketches = comp().Sketches
    sk = sketches.Item(sketches.Count)
    tg = srv.inv.app.TransientGeometry
    p = sk.ModelToSketchSpace(tg.CreatePoint(x / 10, y / 10, z / 10))
    origin = sk.SketchToModelSpace(tg.CreatePoint2d(0, 0))
    return p.X * 10, p.Y * 10, (round(origin.X * 10, 1), round(origin.Y * 10, 1), round(origin.Z * 10, 1))


def solid_block():
    """100x100x20 block on XY: face sketches, holes, pattern, edge features, parameters, files."""
    check("connect", srv.connect)

    def make():
        started = time.time()
        out = srv.create_part("audit_solid")
        took = time.time() - started
        # A modal dialog (e.g. Style Conflict) shows up as a create_part that waits for a click.
        assert took < 15, f"create_part took {took:.0f}s, a dialog probably waited for a click"
        units = srv.inv.active_document().UnitsOfMeasure.LengthUnits
        assert units == 11269, f"length units {units}, expected 11269 (mm)"
        return out
    check("create_part metric", make)
    check("status", lambda: json.loads(srv.status())["name"])
    check("transaction begin", lambda: srv.transaction("begin", "audit"))

    def block():
        srv.create_sketch("XY")
        srv.draw_rectangle(0, 0, 100, 100)
        return expect_delta(lambda: srv.extrude(20), 200000)
    check("create_sketch XY + draw_rectangle + extrude", block)

    def edges():
        out = srv.list_edges()
        lines = out.splitlines()
        assert len(lines) == 12, f"{len(lines)} edges listed"
        return lines[0]
    check("list_edges", edges)

    def faces():
        lines = srv.list_faces().splitlines()
        assert len(lines) == 6, f"{len(lines)} faces listed"
        return lines[0]
    check("list_faces", faces)

    def find_e():
        i = edge_index(x=50, y=0, z=20)
        e = comp().SurfaceBodies.Item(1).Edges.Item(i)
        mid = [(a + b) / 2 * 10 for a, b in zip(
            (e.StartVertex.Point.X, e.StartVertex.Point.Y, e.StartVertex.Point.Z),
            (e.StopVertex.Point.X, e.StopVertex.Point.Y, e.StopVertex.Point.Z))]
        assert [round(m, 3) for m in mid] == [50, 0, 20], mid
        return f"Edge {i}"
    check("find_edge", find_e)

    def find_f():
        out = srv.find_face(z=20, use_z=True)
        state["top"] = int(out.split()[1])
        return out
    check("find_face", find_f)

    def face_pocket():
        # The extrude docstring says a cut from a face sketch needs "negative"; check both halves.
        srv.create_sketch(face_index=state["top"])
        sx, sy, origin = sketch_point_for_world(0, 0, 20)
        srv.draw_circle(sx, sy, 20)
        v0 = vol()
        srv.extrude(5, "positive", "cut")
        assert abs(vol() - v0) < 0.5, "positive cut from a face sketch removed material"
        srv.delete_feature(str(comp().Features.Count))
        srv.create_sketch(face_index=state["top"])
        srv.draw_circle(sx, sy, 60, construction=True)
        srv.draw_circle(sx, sy, 20)
        detail = expect_delta(lambda: srv.extrude(5, "negative", "cut"), -math.pi * 100 * 5)
        return f"face sketch origin at world {origin} | {detail}"
    check("create_sketch on face + construction circle + cut", face_pocket)

    def boss():
        srv.create_sketch("XY", offset=20)
        srv.draw_polygon(-25, -25, 10, 6)
        detail = expect_delta(lambda: srv.extrude(10), HEX_AREA * 10)
        state["boss"] = comp().Features.Count
        return detail
    check("create_sketch offset + draw_polygon + extrude", boss)

    def through_hole():
        detail = expect_delta(lambda: srv.hole(35, 0, 8), -math.pi * 16 * 20)
        state["hole"] = comp().Features.Count
        return detail
    check("hole through-all", through_hole)

    check("circular_pattern", lambda: expect_delta(
        lambda: srv.circular_pattern(state["hole"], 4, 360, "Z"), -3 * math.pi * 16 * 20))

    def tapped():
        # M8x1.25 6H is cut at the 6.647 mm minor diameter; the 118 deg drill point adds ~23 mm3.
        expected = -(math.pi * (6.647 / 2) ** 2 * 15 + 23.1)
        v0 = vol()
        out = srv.hole(25, 25, 8, 15, True)
        dv = vol() - v0
        feat = comp().Features.HoleFeatures.Item(comp().Features.HoleFeatures.Count)
        assert feat.Tapped, "hole is not tapped"
        assert abs(dv - expected) < 25, f"dV {dv:+.1f} mm3, expected about {expected:+.1f} | {out}"
        return f"dV {dv:+.1f} mm3 | {out}"
    check("hole tapped M8 depth 15", tapped)

    def fillets():
        idx = [edge_index(x=sx * 50, y=sy * 50, z=10) for sx in (1, -1) for sy in (1, -1)]
        return expect_delta(
            lambda: srv.fillet(5, ",".join(map(str, idx))), -4 * (1 - math.pi / 4) * 25 * 20)
    check("fillet", fillets)

    def chamfer():
        i = edge_index(x=0, y=-50, z=0)
        v0 = vol()
        out = srv.chamfer(1, str(i))
        dv = vol() - v0
        assert dv < -40, f"dV {dv:+.1f} | {out}"
        chained = " (chained around the tangent loop)" if dv < -60 else ""
        return f"dV {dv:+.1f} mm3{chained} | {out}"
    check("chamfer", chamfer)

    def cbore():
        # Counterbore 10x5.5 plus 5.5 drill to 15 deep plus drill point.
        v0 = vol()
        out = srv.hole_linear("z", 20, "x", 50, 10, "y", 50, 10,
                              diameter=5.5, depth=15, cbore_diameter=10, cbore_depth=5.5)
        dv = vol() - v0
        assert -700 < dv < -640, f"dV {dv:+.1f} mm3, expected about -671 | {out}"
        return f"dV {dv:+.1f} mm3 | {out}"
    check("hole_linear counterbore", cbore)

    def params():
        names = [p["name"] for p in json.loads(srv.get_parameters())]
        assert "d0" in names, names[:5]
        return f"{len(names)} parameters, first {names[:4]}"
    check("get_parameters", params)

    def add_param():
        out = srv.add_parameter("audit_len", "25 mm")
        value = next(p["value"] for p in json.loads(srv.get_parameters()) if p["name"] == "audit_len")
        assert abs(value - 2.5) < 1e-9, f"value {value} cm"
        return out
    check("add_parameter", add_param)

    def set_user():
        out = srv.set_parameter("audit_len", "30 mm")
        assert "value=3.0" in out, out
        return out
    check("set_parameter user", set_user)

    def set_model():
        name = comp().Features.Item(state["boss"]).Definition.Extent.Distance.Name
        return expect_delta(lambda: srv.set_parameter(name, "12 mm"), HEX_AREA * 2)
    check("set_parameter model", set_model)

    def suppress():
        i = str(state["boss"])
        a = expect_delta(lambda: srv.suppress_feature(i, True), -HEX_AREA * 12)
        b = expect_delta(lambda: srv.suppress_feature(i, False), HEX_AREA * 12)
        return f"{a} / {b}"
    check("suppress_feature", suppress)

    def features():
        listed = json.loads(srv.list_features())
        assert len(listed) == comp().Features.Count
        return ", ".join(f["name"] for f in listed)
    check("list_features", features)

    def inspected():
        info = json.loads(srv.inspect())
        assert info["bbox_mm"]["z"] == [0.0, 32.0], info["bbox_mm"]
        return f"V {info['volume_mm3']} mm3, {len(info['features'])} features"
    check("inspect", inspected)

    def delete():
        v_before = vol()
        last = last_feature().Name
        out = srv.delete_feature(str(comp().Features.Count))
        assert vol() > v_before + 600, f"volume did not come back after deleting {last}"
        return out
    check("delete_feature", delete)

    check("transaction commit", lambda: srv.transaction("commit"))

    def abort():
        n0, v0 = comp().Features.Count, vol()
        srv.transaction("begin", "audit abort")
        srv.create_sketch("XY", offset=20)
        srv.draw_rectangle(30, -30, 10, 10)
        srv.extrude(5)
        out = srv.transaction("abort")
        assert comp().Features.Count == n0 and abs(vol() - v0) < 0.5, "abort left changes"
        return out
    check("transaction abort", abort)

    OUT.mkdir(parents=True, exist_ok=True)
    solid = srv.inv.active_document()
    close_audit_files()  # left over from an earlier run; would block the save below
    srv.inv.pin_document(solid)
    for f in OUT.glob("audit_*"):
        f.unlink()
    check("save_document as", lambda: srv.save_document(str(OUT / "audit_solid.ipt")))
    check("save_document in place", lambda: srv.save_document(""))

    def save_onto_open():
        srv.create_part("audit_other")
        try:
            srv.save_document(str(OUT / "audit_solid.ipt"))
        except RuntimeError as exc:
            assert "is open in Inventor" in str(exc), exc
            return str(exc)[:70]
        finally:
            srv.inv.active_document().Close(True)
            srv.inv.pin_document(solid)
        raise AssertionError("saving onto an open file was not refused")
    check("save_document refuses a file that is open", save_onto_open)

    for fmt, ext in (("STEP", "stp"), ("STL", "stl"), ("SAT", "sat"), ("IGES", "igs")):
        def export(fmt=fmt, ext=ext):
            path = OUT / f"audit_solid.{ext}"
            out = srv.export_document(str(path), fmt)
            assert path.exists() and path.stat().st_size > 0, f"{path.name} missing or empty"
            return f"{path.stat().st_size} bytes | {out}"
        check(f"export_document {fmt}", export)

    close_active()


def revolves():
    """Shaft by full revolve, groove by revolve cut, partial revolve, revolve about a sketch line."""
    srv.create_part("audit_revolve")

    def shaft():
        srv.create_sketch("XY")
        srv.draw_closed_profile("[[0,0],[20,0],[20,60],[0,60]]")
        return expect_delta(lambda: srv.revolve(axis="Y"), math.pi * 400 * 60)
    check("draw_closed_profile + revolve full", shaft)

    def groove():
        srv.create_sketch("XY")
        srv.draw_closed_profile("[[16,25],[20,25],[20,35],[16,35]]")
        return expect_delta(lambda: srv.revolve(axis="Y", operation="cut"), -math.pi * (400 - 256) * 10)
    check("revolve cut", groove)

    def circle_edges():
        rows = [r for r in srv.list_edges().splitlines() if "circle R=20.0" in r]
        assert rows, "no full circle of R=20 listed"
        assert "L=125.7" in rows[0], rows[0]
        i = edge_index(x=0, y=60, z=0)
        e = comp().SurfaceBodies.Item(1).Edges.Item(i)
        assert e.GeometryType == 5124 and abs(e.Geometry.Radius * 10 - 20) < 1e-6, f"edge {i}"
        return f"{rows[0]} | find_edge by center -> Edge {i}"
    check("list_edges + find_edge on full circles", circle_edges)

    def partial():
        srv.create_sketch("XY")
        srv.draw_closed_profile("[[20,0],[30,0],[30,10],[20,10]]")
        return expect_delta(lambda: srv.revolve(90, axis="Y"), math.pi * (900 - 400) * 10 / 4)
    check("revolve 90 deg", partial)

    def about_line():
        srv.create_sketch("XY")
        srv.draw_line(0, 60, 0, 70, construction=True)
        srv.draw_closed_profile("[[0,60],[10,60],[10,70],[0,70]]")
        return expect_delta(lambda: srv.revolve(axis="line"), math.pi * 100 * 10)
    check("draw_line construction + revolve about sketch line", about_line)

    close_active()


def extrude_variants():
    """Directions, through-all, intersect, new body, surface, and the other templates."""
    srv.create_part("audit_extrude")

    def symmetric():
        srv.create_sketch("XY")
        srv.draw_rectangle(0, 0, 40, 40)
        detail = expect_delta(lambda: srv.extrude(20, "symmetric"), 32000)
        assert bbox()[4:] == (-10, 10), bbox()
        return detail
    check("extrude symmetric", symmetric)

    def intersect():
        srv.create_sketch("XY")
        srv.draw_circle(0, 0, 40)
        return expect_delta(
            lambda: srv.extrude(30, "symmetric", "intersect"), math.pi * 400 * 20 - 32000)
    check("extrude intersect", intersect)

    def negative():
        srv.create_sketch("XY")
        srv.draw_rectangle(0, 0, 10, 10)
        detail = expect_delta(lambda: srv.extrude(15, "negative"), 500)
        assert bbox()[4] == -15, bbox()
        return detail
    check("extrude negative", negative)

    def all_symmetric():
        srv.create_sketch("XY")
        srv.draw_circle(0, 0, 4)
        return expect_delta(
            lambda: srv.extrude(extent_type="all", direction="symmetric", operation="cut"),
            -math.pi * 4 * 25)
    check("extrude through-all symmetric cut", all_symmetric)

    def all_positive():
        srv.create_sketch("XY")
        srv.draw_circle(12, 0, 4)
        v0 = vol()
        out = srv.extrude(extent_type="all", operation="cut")
        dv = vol() - v0
        one_side = -math.pi * 4 * 10
        assert abs(dv - one_side) < 0.5 or abs(dv - 2 * one_side) < 0.5, f"dV {dv:+.1f} | {out}"
        side = "only the +Z side" if abs(dv - one_side) < 0.5 else "both sides"
        return f"dV {dv:+.1f} mm3, cuts {side} of the sketch plane | {out}"
    check("extrude through-all positive cut", all_positive)

    def new_body():
        srv.create_sketch("XY")
        srv.draw_rectangle(40, 0, 5, 5)
        out = srv.extrude(5, operation="new")
        n = comp().SurfaceBodies.Count
        assert n == 2, f"{n} bodies"
        return f"2 bodies | {out}"
    check("extrude new body", new_body)

    def surface():
        srv.create_sketch("XY")
        srv.draw_circle(60, 0, 6)
        out = srv.extrude(5, operation="surface")
        return f"{comp().SurfaceBodies.Count} solid bodies, {comp().WorkSurfaces.Count} work surfaces | {out}"
    check("extrude surface", surface)

    close_active()

    def english():
        out = srv.create_part("audit_english", "english")
        doc = srv.inv.active_document()
        units = doc.UnitsOfMeasure.LengthUnits
        template = "inch" if units == 11272 else f"length units {units}"
        doc.Close(True)
        assert units == 11272, f"english template opened with {template}"
        return out
    check("create_part english", english)

    def by_path():
        path = srv.inv.app.FileLocations.TemplatesPath + r"Metric\Standard (mm).ipt"
        out = srv.create_part("audit_path", path)
        close_active()
        return out
    check("create_part template path", by_path)


def sheet_metal():
    """Face, flange, cut and flat pattern on a 100x60x2 plate."""
    check("create_part sheet_metal", lambda: srv.create_part("audit_sheet", "sheet_metal"))

    def thickness():
        out = srv.set_sheet_metal_thickness(2)
        value = comp().Thickness.Value * 10
        assert abs(value - 2) < 1e-6, f"Thickness parameter is {value} mm | {out}"
        return out
    check("set_sheet_metal_thickness", thickness)

    def face():
        srv.create_sketch("XY")
        srv.draw_rectangle(0, 0, 100, 60)
        detail = expect_delta(srv.sheet_metal_face, 12000)
        state["plate_top"] = bbox()[5]
        return f"{detail} | Z {bbox()[4:]}"
    check("sheet_metal_face", face)

    def flange():
        i = edge_index(x=0, y=-30, z=state["plate_top"])
        v0 = vol()
        out = srv.flange(str(i), 30, 90)
        dv = vol() - v0
        height = bbox()[5] - bbox()[4]
        assert dv > 4000 and abs(height - 30) < 0.5, f"dV {dv:+.1f}, height {height} | {out}"
        return f"dV {dv:+.1f} mm3, part height {height} mm | {out}"
    check("flange", flange)

    def cut():
        top = int(srv.find_face(z=state["plate_top"], use_z=True, min_area=4000).split()[1])
        srv.create_sketch(face_index=top)
        sx, sy, origin = sketch_point_for_world(0, 0, state["plate_top"])
        srv.draw_circle(sx, sy, 20)
        detail = expect_delta(srv.sheet_metal_cut, -math.pi * 100 * 2)
        return f"{detail} | face sketch origin at world {origin}"
    check("find_face + sheet_metal_cut", cut)

    def flat():
        c = comp()
        if not c.HasFlatPattern:
            c.Unfold()
        fp = c.FlatPattern
        size = (round(fp.Length * 10, 1), round(fp.Width * 10, 1))
        fp.ExitEdit()
        return f"flat pattern {size[0]} x {size[1]} mm"
    check("flat pattern", flat)

    close_active()


def drawing():
    """All drawing tools on an A3 sheet of the solid block saved by solid_block()."""
    model = str(OUT / "audit_solid.ipt")
    check("create_drawing", lambda: srv.create_drawing("iso", "A3"))

    def rejected():
        try:
            srv.add_base_view(model, 110, 270)
        except ValueError as exc:
            assert "outside the border" in str(exc), exc
            return str(exc).split(":")[0]
        raise AssertionError("a view past the top border was accepted")
    check("add_base_view rejects a view outside the border", rejected)

    def base():
        out = srv.add_base_view(model, 110, 200)
        state["front"] = out.split()[2].rstrip(":")
        return out
    check("add_base_view", base)

    def projected():
        out = srv.add_projected_view(state["front"], 110, 90)
        state["top"] = out.split()[2]
        return out
    check("add_projected_view", projected)

    def section():
        out = srv.add_section_view(state["front"], -70, 0, 70, 0, 110, 90, "A")
        raise AssertionError(f"section on top of the projected view was accepted: {out}")

    def section_rejected():
        try:
            section()
        except ValueError as exc:
            assert "overlaps view" in str(exc), exc
            return "overlap with the projected view rejected"
    check("add_section_view rejects an overlap", section_rejected)

    def section_ok():
        out = srv.add_section_view(state["front"], 0, -70, 0, 70, 250, 200, "A")
        state["section"] = out.split()[2]
        return out
    check("add_section_view", section_ok)

    def detail():
        out = srv.add_detail_view(state["front"], 35, 0, 10, 355, 200, 2.0, "B")
        state["detail"] = out.split()[2]
        return out
    check("add_detail_view", detail)

    for key in ("front", "top", "section"):
        check(f"add_centerlines {key}", lambda key=key: srv.add_centerlines(state[key]))
    for key in ("front", "top"):
        def retrieve(key=key):
            out = srv.retrieve_dimensions(state[key])
            assert "Retrieved" in out and "remaining text overlaps: none" in out, out
            return out
        check(f"retrieve_dimensions {key}", retrieve)

    def diameter():
        out = srv.add_dimension(state["detail"], "diameter", 4, 0, text_x=-12, text_y=-14)
        assert "n8" in out, out
        return out
    check("add_dimension diameter", diameter)

    def linear():
        out = srv.add_dimension(state["top"], "horizontal", -50, 0, 50, 0, text_x=0, text_y=-25)
        assert out.split()[2] == "100,00", out
        return out
    check("add_dimension horizontal", linear)

    def title():
        out = json.loads(srv.set_title_block(json.dumps({"title": "Audit block", "part_number": "AUD-1"})))
        assert out["title"] == "Audit block" and out["part number"] == "AUD-1", out
        return out
    check("set_title_block", title)

    def title_unknown():
        try:
            srv.set_title_block(json.dumps({"colour": "red"}))
        except ValueError as exc:
            return str(exc)[:60]
        raise AssertionError("unknown title block field accepted")
    check("set_title_block rejects unknown fields", title_unknown)

    def views():
        info = json.loads(srv.list_views())
        assert len(info["views"]) == 4, info["views"]
        return f"{len(info['views'])} views, {info['dimensions']} dimensions, problems: {info['problems'] or 'none'}"
    check("list_views", views)

    def png():
        path = OUT / "audit_drawing.png"
        out = srv.export_sheet_png(str(path), 1600)
        assert path.stat().st_size > 10000, "image suspiciously small"
        return out
    check("export_sheet_png", png)

    def pdf():
        path = OUT / "audit_drawing.pdf"
        out = srv.export_pdf(str(path))
        assert path.read_bytes()[:5] == b"%PDF-", "not a PDF"
        return out
    check("export_pdf", pdf)

    close_active()
    close_audit_files()


def server_only():
    """Tools that live only in server.py."""
    check("execute_python stdout", lambda: _equal(srv.execute_python("print(1 + 1)"), "2"))

    def stderr():
        out = srv.execute_python("import sys; print('to-stderr', file=sys.stderr)")
        if "to-stderr" not in out:
            raise Warn(f"stderr is not captured: {out!r}")
        return out
    check("execute_python stderr", stderr)

    def error():
        out = srv.execute_python("1 / 0")
        assert "ZeroDivisionError" in out, out
        return out.splitlines()[-1]
    check("execute_python error", error)

    def reload():
        out = srv.reload_api()
        assert srv.inv.is_connected(), "connection lost after reload"
        return out
    check("reload_api", reload)


def _equal(actual, expected):
    assert actual == expected, f"{actual!r} != {expected!r}"
    return actual


def main():
    for group in (solid_block, revolves, extrude_variants, sheet_metal, drawing, server_only):
        print(f"\n{group.__name__}: {group.__doc__}", flush=True)
        try:
            group()
        except Exception as exc:
            counts["FAIL"] += 1
            print(f"FAIL  {group.__name__} aborted: {type(exc).__name__}: {exc}", flush=True)
    print(f"\n{counts['PASS']} PASS, {counts['WARN']} WARN, {counts['FAIL']} FAIL")
    return 1 if counts["FAIL"] else 0


if __name__ == "__main__":
    sys.exit(main())
