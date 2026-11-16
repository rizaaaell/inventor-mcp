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
    srv.inv.close_documents_in(str(OUT))


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
    def iso_profile():
        out = srv.create_drawing("iso")
        close_active()
        return out
    check("create_drawing with the iso profile", iso_profile)

    def create():
        out = srv.create_drawing()
        std = srv.inv.active_drawing().StylesManager.ActiveStandardStyle
        assert "third angle" in out and not std.FirstAngleProjection, out
        assert std.GetViewAnnotationDefaults(10503) == "<DrawingViewName/>", "section line label not from profile"
        return out
    check("create_drawing applies the default profile", create)

    def unknown_profile():
        try:
            srv.create_drawing("no_such_profile")
        except ValueError as exc:
            return str(exc)
        raise AssertionError("unknown profile accepted")
    check("create_drawing rejects an unknown profile", unknown_profile)

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
        assert out.split()[2] == "100", out  # the default profile drops trailing zeros
        return out
    check("add_dimension horizontal", linear)

    def title():
        out = json.loads(srv.set_title_block(json.dumps({
            "title": "Audit block", "part_number": "AUD-1", "MATERIAL": "Aluminum 6061"})))
        shown = out["title_block"]
        assert shown["TITLE"] == "Audit block" and shown["PART NUMBER"] == "AUD-1", shown
        assert shown["MATERIAL"] == "Aluminum 6061", shown
        assert "TITLE" in out["model_changed"]["fields"], out
        return shown
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

    def hole_note():
        out = srv.add_hole_note(state["front"], 0, 39, -55, 60)
        assert "4x" in out and "n8" in out, out
        return out
    check("add_hole_note on the patterned hole", hole_note)

    def pcd():
        out = srv.add_dimension(state["front"], "pcd", 0, -35, text_x=-55, text_y=-62)
        assert out.split()[2] == "n70", out
        return out
    check("add_dimension pcd", pcd)

    def delete_dims():
        listed = json.loads(srv.list_dimensions())
        target = [d for d in listed if d["view"] == state["front"] and d["text"] == "n8"]
        assert target, f"no retrieved n8 in the front view: {listed}"
        out = srv.delete_dimension(str(target[0]["index"]))
        assert len(json.loads(srv.list_dimensions())) == len(listed) - 1, "count did not drop"
        return out
    check("list_dimensions + delete_dimension", delete_dims)

    def tolerance_and_move():
        listed = json.loads(srv.list_dimensions())
        target = next(d for d in listed if d["view"] == state["top"] and d["text"] == "100")
        out = srv.set_tolerance(target["index"], "symmetric", 0.1)
        moved = srv.move_dimension(target["index"], 0, -32)
        after = next(d for d in json.loads(srv.list_dimensions()) if d["index"] == target["index"])
        assert after["text_mm"] != target["text_mm"], "text did not move"
        return f"{out}; {moved}"
    check("set_tolerance + move_dimension", tolerance_and_move)

    def angle():
        out = srv.add_dimension(state["front"], "angle", 35, 0, 0, 35, text_x=45, text_y=45,
                                vertex_x=10, vertex_y=0)
        assert out.split()[2] == "90°", out
        index = len(json.loads(srv.list_dimensions()))
        return f"{out}; {srv.set_tolerance(index, 'basic')}"
    check("add_dimension angle + basic", angle)

    def angle_from_axis():
        out = srv.add_dimension(state["front"], "angle", 0, 35, text_x=30, text_y=30,
                                vertex_x=10, vertex_y=0)
        assert out.split()[2] == "90°", out
        return out
    check("add_dimension angle from the axis", angle_from_axis)

    def chamfer_note():
        # The block's 1 mm bottom chamfer shows as a slant at one bottom corner of section A
        # (z across, y up); which side is the bottom depends on the cut direction.
        errors = []
        for side in (-1, 1):
            try:
                out = srv.add_chamfer_note(state["section"], side * 15.6, -49.6, side * 16, -40,
                                           side * 30, -62, prefix="2x ")
                assert "±" not in out and "2x" in out, out
                return out
            except ValueError as exc:
                errors.append(str(exc)[:60])
        raise AssertionError(f"no chamfer found at either bottom corner: {errors}")
    check("add_chamfer_note", chamfer_note)

    def fit():
        listed = json.loads(srv.list_dimensions())
        target = next(d for d in listed if d["view"] == state["front"] and d["text"].startswith("n20"))
        out = srv.set_tolerance(target["index"], "fit", fit="H7")
        text = next(d["text"] for d in json.loads(srv.list_dimensions()) if d["index"] == target["index"])
        assert text.endswith("H7"), text
        return out
    check("set_tolerance fit", fit)

    def on_dimension():
        sheet = srv.inv.active_drawing().ActiveSheet
        target = next(d for d in json.loads(srv.list_dimensions())
                      if d["view"] == state["front"] and d["text"].startswith("n20"))
        before = sheet.DrawingDimensions.GeneralDimensions.Item(target["index"]).Text.FormattedText
        dims = sheet.DrawingDimensions.GeneralDimensions
        out = srv.add_dimension(state["front"], "diameter", 10, 0, text_x=-45, text_y=-40,
                                prefix="2x ", suffix=" THRU\nEQ SP")
        assert "<Br/>" in dims.Item(dims.Count).Text.FormattedText, out
        frames = sheet.FeatureControlFrames.Count
        outs = [srv.add_datum(state["front"], 0, 0, "B", 0, 0, dimension=target["index"]),
                srv.add_gdt(state["front"], 0, 0, 0, 0, "position", 0.1, "A,B", diameter_zone=True,
                            dimension=dims.Count)]
        frame = sheet.FeatureControlFrames.Item(frames + 1).Position
        r = dims.Item(dims.Count).Text.RangeBox
        assert frame.Y < r.MinPoint.Y and r.MinPoint.X < frame.X < r.MaxPoint.X, "frame not under the note"
        assert sheet.DrawingDimensions.GeneralDimensions.Item(target["index"]).Text.FormattedText == before
        return " / ".join(o.split(" (")[0] for o in [out] + outs)
    check("suffix note, datum and frame on a dimension", on_dimension)

    def gdt():
        sheet = srv.inv.active_drawing().ActiveSheet
        frames, symbols, finishes = (sheet.FeatureControlFrames.Count, sheet.SketchedSymbols.Count,
                                     sheet.SurfaceTextureSymbols.Count)
        outs = [
            srv.add_datum(state["top"], 50, 0, "A", 62, 10),
            srv.add_gdt(state["top"], -50, 0, -70, 25, "perpendicularity", 0.05, "A"),
            srv.add_gdt(state["front"], 35, 4, 58, 52, "position", 0.2, "A", diameter_zone=True),
            srv.add_surface_finish(state["top"], 0, 16, 20, 26, "Ra 3,2"),
        ]
        assert (sheet.FeatureControlFrames.Count, sheet.SketchedSymbols.Count,
                sheet.SurfaceTextureSymbols.Count) == (frames + 2, symbols + 1, finishes + 1), "counts"
        assert "Ø0,2" in outs[2], outs[2]
        return " / ".join(o.split(" (")[0] for o in outs)
    check("add_datum + add_gdt + add_surface_finish", gdt)

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


def assembly():
    """Disk with a center hole and pins: every constraint kind, DOF, BOM, interference, pattern."""
    close_audit_files()
    disk, pin = OUT / "audit_disk.ipt", OUT / "audit_pin.ipt"
    srv.create_part("audit_disk")
    srv.create_sketch("XY")
    srv.draw_circle(0, 0, 60)
    srv.extrude(10)
    srv.create_sketch("XY")
    srv.draw_circle(0, 0, 10)
    srv.extrude(10, operation="cut")
    srv.save_document(str(disk))
    srv.create_part("audit_pin")
    srv.create_sketch("XY")
    srv.draw_circle(0, 0, 10)
    srv.extrude(30)
    srv.save_document(str(pin))

    check("create_assembly", srv.create_assembly)
    check("place_component grounded", lambda: srv.place_component(str(disk), grounded=True))
    check("place_component rotated", lambda: srv.place_component(str(pin), 30, 0, 20, rx=90))

    def circles():
        found = json.loads(srv.list_occurrence_geometry("audit_disk:1"))
        assert "circle:0,0,10,5" in found, found
        return found
    check("list_occurrence_geometry circles", circles)
    check("list_occurrence_geometry planes",
          lambda: json.loads(srv.list_occurrence_geometry("audit_disk:1", "planes")))

    def insert():
        out = srv.add_constraint("insert", "audit_disk:1", "circle:0,0,10,5",
                                 "audit_pin:1", "circle:0,0,0,5")
        assert "origin [0.0, 0.0, 10.0]" in out, out
        free = json.loads(srv.get_dof())["with_free_dof"]
        assert free == ["audit_pin:1"], f"only the pin's spin should be free: {free}"
        return out
    check("add_constraint insert + get_dof", insert)

    def angle():
        out = srv.add_constraint("angle", "audit_disk:1", "plane:XZ", "audit_pin:1", "plane:XZ",
                                 angle=30)
        assert json.loads(srv.get_dof())["fully_constrained"], srv.get_dof()
        return out
    check("add_constraint angle", angle)

    def mate_tangent():
        srv.place_component(str(pin), 20, 5, 15)
        out = srv.add_constraint("mate", "audit_disk:1", "face:20,0,10", "audit_pin:2", "face:0,0,0")
        out += " | " + srv.add_constraint("tangent", "audit_pin:1", "cylinder:5,0,15",
                                          "audit_pin:2", "cylinder:5,0,15")
        z = json.loads(srv.list_occurrences())[2]["origin_mm"][2]
        assert abs(z - 10) < 0.01, f"pin 2 base at z={z}, expected 10"
        return out
    check("add_constraint mate face + tangent cylinder", mate_tangent)

    def flush_assembly():
        return srv.add_constraint("flush", "assembly", "plane:YZ", "audit_pin:2", "plane:YZ",
                                  offset=0)
    check("add_constraint flush to assembly plane", flush_assembly)

    def edge_selector():
        e = srv.inv._geometry("audit_disk:1", "edge:30,0,10")
        assert e.GeometryType == 5124, e.GeometryType
        try:
            srv.inv._geometry("audit_disk:1", "face:0,0,50")
        except ValueError as exc:
            return f"edge found; far point refused: {exc}"
        raise AssertionError("a point 40 mm away still matched a face")
    check("edge selector and distance limit", edge_selector)

    def pattern():
        out = srv.pattern_component("audit_pin:2", "audit_disk:1", "axis:Z", 4)
        names = [o["name"] for o in json.loads(srv.list_occurrences())]
        assert len(names) == 6, names
        return out
    check("pattern_component", pattern)

    def bom():
        rows = {r["file"]: r["quantity"] for r in json.loads(srv.get_bom("parts"))}
        assert rows == {"audit_disk.ipt": 1, "audit_pin.ipt": 5}, rows
        structured = json.loads(srv.get_bom("structured"))
        return f"parts {rows}; structured {len(structured)} rows"
    check("get_bom", bom)

    def interference():
        assert json.loads(srv.analyze_interference()) == [], srv.analyze_interference()
        srv.place_component(str(pin), 20, 0, 0, grounded=True)
        clashes = json.loads(srv.analyze_interference())
        assert len(clashes) == 1 and clashes[0]["cause"] == "real overlap", clashes
        assert abs(clashes[0]["volume_mm3"] - math.pi * 25 * 10) < 1, clashes
        return clashes
    check("analyze_interference", interference)

    def browse_cc():
        top = json.loads(srv.list_content_center())["subcategories"]
        assert "Fasteners" in top, top
        fams = json.loads(srv.list_content_center("Fasteners/Nuts/Hex", contains="DIN 934"))["families"]
        sizes = json.loads(srv.list_content_center("Fasteners/Nuts/Hex", "DIN 934", "M10"))["sizes"]
        assert "M10" in sizes, sizes
        return f"{fams}; sizes {sizes}"
    check("list_content_center", browse_cc)

    def cc_thread():
        # Bolt and nut on the same origin: the shank runs through the nut's minor-diameter bore.
        srv.place_content_center("Fasteners/Bolts/Hex Head", "DIN 933", "M10 x 60", 200, grounded=True)
        out = srv.place_content_center("Fasteners/Nuts/Hex", "DIN 934", "m10", 200, grounded=True)
        clashes = [c for c in json.loads(srv.analyze_interference()) if "DIN" in c["first"] + c["second"]]
        assert len(clashes) == 1 and clashes[0]["cause"].startswith("thread artifact"), clashes
        return f"{out.split(' | ')[0]}; {clashes[0]['volume_mm3']} mm3 thread artifact"
    check("place_content_center + thread artifact", cc_thread)

    def save_log():
        out = srv.save_document(str(OUT / "audit_assembly.iam"))
        log = json.loads((OUT / "audit_assembly.constraints.json").read_text(encoding="utf-8"))
        kinds = [c["kind"] for c in log["constraints"]]
        assert kinds == ["insert", "angle", "mate", "tangent", "flush"], kinds
        return out
    check("save_document writes the constraint log", save_log)

    def assembly_drawing():
        srv.create_drawing()
        srv.add_base_view(str(OUT / "audit_assembly.iam"), 150, 200, 0.5, design_view="Default")
        out = srv.add_section_view("VIEW1", -160, 0, 160, 0, 150, 120, "A", no_hatch="audit_pin:1")
        assert "unhatched: audit_pin:1" in out, out
        parts = srv.add_parts_list("A")
        assert "4 items" in parts, parts
        balloons = srv.add_balloons("A")
        n = int(balloons.split()[0])
        assert n >= 2, balloons
        problems = json.loads(srv.list_views())["problems"]
        assert not problems, problems
        srv.inv.active_document().Close(True)
        return f"{parts} | {balloons}"
    check("assembly drawing: design view, no_hatch, parts list, balloons", assembly_drawing)

    def hidden_variant():
        srv.create_drawing()
        srv.add_base_view(str(OUT / "audit_assembly.iam"), 150, 200, 0.5)
        out = srv.set_component_visibility("VIEW1", "DIN 933 - replaced by DIN EN 24017 M10  x 60:1", False)
        pl = srv.add_parts_list("VIEW1", hide="DIN 933 - M10  x 60")
        assert "3 items" in pl and "DIN 933" not in pl, pl
        srv.inv.active_document().Close(True)
        return f"{out} | {pl}"
    check("set_component_visibility + parts list hide", hidden_variant)

    def disc_details():
        # Four equal holes cut in one sketch: no pattern, yet a pitch circle and PCD; a
        # 12.35 mm wide plate keeps its second decimal.
        srv.create_part("audit_disc")
        srv.create_sketch("XY")
        srv.draw_circle(0, 0, 100)
        for x, y in ((35, 0), (0, 35), (-35, 0), (0, -35)):
            srv.draw_circle(x, y, 8, sketch_index=0)
        srv.extrude(12.35)
        srv.save_document(str(OUT / "audit_disc.ipt"))
        srv.create_drawing()
        srv.add_base_view(str(OUT / "audit_disc.ipt"), 120, 180, 1)
        srv.add_projected_view("VIEW1", 230, 180)
        cl = srv.add_centerlines("VIEW1")
        assert "1 bolt circle(s) added" in cl, cl
        pcd = srv.add_dimension("VIEW1", "pcd", 24.75, 24.75, text_x=-60, text_y=60, prefix="PCD ")
        thick = srv.add_dimension("VIEW2", "horizontal", -6.175, 30, 6.175, 30, text_x=0, text_y=60)
        assert "12,35" in thick, thick
        srv.inv.active_document().Close(True)
        return f"{pcd} | {thick}"
    check("bolt circle for sketch holes + automatic dimension precision", disc_details)

    def exploded():
        copy = OUT / "audit_exploded.iam"
        out = srv.create_exploded_copy(str(OUT / "audit_assembly.iam"), str(copy))
        ad = srv.inv.active_assembly().ComponentDefinition
        assert ad.Constraints.Count == 0 and ad.OccurrencePatterns.Count == 0, out
        before = next(o for o in json.loads(srv.list_occurrences()) if o["name"] == "audit_pin:1")
        srv.explode_components("audit_pin:1, audit_pin:3", dz=40)
        after = next(o for o in json.loads(srv.list_occurrences()) if o["name"] == "audit_pin:1")
        assert abs(after["origin_mm"][2] - before["origin_mm"][2] - 40) < 0.01, (before, after)
        srv.save_document("")
        srv.create_drawing()
        view = srv.add_base_view(str(copy), 150, 180, 0.5, "iso_top_right", spin=30)
        assert view.startswith("Base view VIEW1"), view
        trails = srv.add_explode_trails("VIEW1")
        assert trails.startswith("2 trail"), trails
        srv.inv.active_document().Close(True)
        return f"{out} | {trails}"
    check("create_exploded_copy + explode_components + spin view + trails", exploded)

    def auto():
        close_audit_files()
        srv.create_exploded_copy(str(OUT / "audit_assembly.iam"), str(OUT / "audit_auto.iam"))
        before = {o["name"]: o["origin_mm"][2] for o in json.loads(srv.list_occurrences())}
        out = srv.auto_explode(15, "Z")
        after = {o["name"]: o["origin_mm"][2] for o in json.loads(srv.list_occurrences())}
        # The pin inserted on the disk's top face goes up by the gap; the disk stays.
        assert abs(after["audit_pin:1"] - before["audit_pin:1"] - 15) < 0.01, (before, after)
        assert after["audit_disk:1"] == before["audit_disk:1"], (before, after)
        return out
    check("auto_explode", auto)
    close_audit_files()


def weldment():
    """Weldment with two plates, a cosmetic weld, and a drawing with welding symbols."""
    close_audit_files()
    base, upright = OUT / "audit_weld_base.ipt", OUT / "audit_weld_upright.ipt"
    for path, w in ((base, 100), (upright, 60)):
        srv.create_part(path.stem)
        srv.create_sketch("XY")
        srv.draw_rectangle(0, 0, w, 60)
        srv.extrude(10)
        srv.save_document(str(path))
        srv.inv.active_document().Close(True)

    check("create_weldment", srv.create_weldment)

    def build():
        srv.place_component(str(base), grounded=True)
        srv.place_component(str(upright), 0, 0, 60, rx=90)
        srv.add_constraint("mate", "audit_weld_base:1", "face:0,0,10", "audit_weld_upright:1", "face:0,-30,5")
        a = srv.add_constraint("flush", "audit_weld_base:1", "plane:YZ", "audit_weld_upright:1", "plane:XY")
        b = srv.add_constraint("flush", "audit_weld_base:1", "plane:XZ", "audit_weld_upright:1", "plane:YZ")
        assert "_2 (healthy)" in b, f"second flush on the same pair needs its own name: {a} / {b}"
        names = [o["name"] for o in json.loads(srv.list_occurrences())]
        assert names == ["audit_weld_base:1", "audit_weld_upright:1"], names
        assert json.loads(srv.get_dof())["fully_constrained"], srv.get_dof()
        return b
    check("weldment constraints, unique names, welds component left out", build)

    def weld():
        out = srv.add_cosmetic_weld("audit_weld_upright:1", "edge:0,-30,0; edge:0,-30,10", leg=6)
        welds = srv.inv.active_assembly().ComponentDefinition.Welds.CosmeticWelds
        assert welds.Count == 1, welds.Count
        assert json.loads(srv.analyze_interference()) == [], srv.analyze_interference()
        srv.save_document(str(OUT / "audit_weldment.iam"))
        return out
    check("add_cosmetic_weld", weld)

    def drawing():
        srv.create_drawing()
        srv.add_base_view(str(OUT / "audit_weldment.iam"), 120, 180, 1)
        state = srv.inv._view("VIEW1").GetWeldmentState()[0]
        assert state == 80899, f"weldment view in state {state}, expected welds (80899)"
        out = [srv.add_weld_symbol("VIEW1", 0, -24, -45, 25, "fillet", "a4", sides="both", tail="135"),
               srv.add_weld_symbol("VIEW1", 50, -30, 70, -50, "v", "s8", "50", sides="arrow", field=True)]
        assert srv.inv.active_drawing().ActiveSheet.WeldingSymbols.Count == 2
        srv.add_parts_list("VIEW1")
        balloons = srv.add_balloons("VIEW1")
        assert balloons.startswith("2 balloons"), balloons
        shown = json.loads(srv.set_title_block('{"TITLE": "Audit weldment"}'))["title_block"]["MATERIAL"]
        assert shown == "NONE", shown
        problems = json.loads(srv.list_views())["problems"]
        assert not problems, problems
        srv.inv.active_document().Close(True)
        return " | ".join(out + [balloons])
    check("weldment drawing: welds state, add_weld_symbol, balloons", drawing)
    close_audit_files()


def drawing_edits():
    """Moving and deleting views, hole note count, notes, iProperties, MATERIAL statement."""
    close_audit_files()
    plate = OUT / "audit_plate.ipt"
    srv.create_part("audit_plate")
    srv.create_sketch("XY")
    srv.draw_rectangle(0, 0, 80, 50)
    srv.extrude(10)
    srv.hole(x=-30, y=0, diameter=11)
    srv.hole(x=30, y=0, diameter=11)
    srv.save_document(str(plate))

    def props():
        out = srv.set_properties(str(plate), json.dumps({"Part Number": "AU-001", "Description": "Audit plate",
                                                         "Heat Treatment": "none"}))
        doc = srv.inv._open_model(str(plate))
        dt = doc.PropertySets.Item("Design Tracking Properties")
        assert dt.Item("Part Number").Value == "AU-001" and dt.Item("Description").Value == "Audit plate"
        return out
    check("set_properties", props)

    srv.create_drawing()
    srv.add_base_view(str(plate), 100, 200, 1)
    srv.add_projected_view("VIEW1", 100, 120)

    def material():
        shown = json.loads(srv.set_title_block('{"TITLE": "Audit plate"}'))["title_block"]["MATERIAL"]
        assert shown == "NONE", f"a Generic part should state NONE, shows {shown!r}"
        return shown
    check("MATERIAL stated as NONE for a Generic part", material)

    def move():
        out = srv.move_view("VIEW1", 150, 210, 1.5)
        v = next(v for v in json.loads(srv.list_views())["views"] if v["name"] == "VIEW1")
        assert v["center_mm"] == [150.0, 210.0] and v["scale"] == 1.5, v
        try:
            srv.move_view("VIEW1", 400, 280)
        except ValueError as exc:
            v = next(v for v in json.loads(srv.list_views())["views"] if v["name"] == "VIEW1")
            assert v["center_mm"] == [150.0, 210.0], v
            return f"{out} | refused: {exc}"
        raise AssertionError("a view moved past the border was accepted")
    check("move_view (and refusal)", move)

    def notes():
        srv.add_hole_note("VIEW1", 30, 5.5, 60, 45, count=2)
        found = json.loads(srv.list_notes())
        assert found and found[0]["text"].startswith("2x"), found
        srv.delete_note("1")
        assert json.loads(srv.list_notes()) == [], srv.list_notes()
        return found[0]["text"]
    check("add_hole_note count + list_notes + delete_note", notes)

    def delete():
        out = srv.delete_view("VIEW2")
        names = [v["name"] for v in json.loads(srv.list_views())["views"]]
        assert names == ["VIEW1"], names
        return out
    check("delete_view", delete)
    srv.inv.active_document().Close(True)
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
    for group in (solid_block, revolves, extrude_variants, sheet_metal, drawing, assembly, weldment,
                  drawing_edits,
                  server_only):
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
