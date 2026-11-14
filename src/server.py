"""MCP Server for Autodesk Inventor parametric modeling."""

import json
from mcp.server.fastmcp import FastMCP
from . import inventor_api as _api

mcp = FastMCP(
    "Autodesk Inventor",
    instructions=(
        "MCP server for parametric 3D modeling in Autodesk Inventor. "
        "All dimensions are in millimeters. "
        "Typical workflow: connect → create_part → create_sketch → draw geometry → extrude/revolve → save. "
        "For anything not covered by a dedicated tool, use execute_python "
        "(persistent namespace, live inv/app/comp/body/tg objects). "
        "After editing inventor_api.py on disk, call reload_api — no server restart needed."
    ),
)

inv = _api.InventorConnection()

# Persistent namespace for execute_python (variables survive between calls)
_exec_ns: dict = {}


# ---------- Power tools (token savers) ----------

@mcp.tool()
def execute_python(code: str) -> str:
    """Execute Python code against the live Inventor connection.

    Pre-bound objects (re-resolved fresh on every call):
      inv  — InventorConnection wrapper (all high-level methods, mm units)
      app  — Inventor.Application COM object
      doc  — active document          comp — its ComponentDefinition
      body — comp.SurfaceBodies.Item(1) (or None)
      tg   — TransientGeometry        math — math module
    Variables you assign persist between calls (one shared namespace).
    Internal COM units are CENTIMETERS — divide mm by 10.
    Returns captured stdout and stderr (print your results!) or the traceback on error.
    """
    import io, contextlib, traceback, math as _math
    ctx = {"inv": inv, "math": _math}
    try:
        if not inv.is_connected():
            inv.connect()
        ctx["app"] = inv.app
        ctx["tg"] = inv.app.TransientGeometry
        ctx["doc"] = inv.app.ActiveDocument
        if ctx["doc"] is not None:
            ctx["comp"] = ctx["doc"].ComponentDefinition
            try:
                ctx["body"] = ctx["comp"].SurfaceBodies.Item(1)
            except Exception:
                ctx["body"] = None
    except Exception:
        pass
    _exec_ns.update(ctx)
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            exec(compile(code, "<mcp>", "exec"), _exec_ns)
        out = buf.getvalue().strip()
        if len(out) > 6000:
            out = out[:6000] + "\n... (truncated at 6000 chars)"
        return out if out else "(ok, no output)"
    except Exception:
        partial = buf.getvalue().strip()
        tb = traceback.format_exc(limit=3)
        return (partial + "\n" if partial else "") + f"ERROR:\n{tb}"


@mcp.tool()
def reload_api() -> str:
    """Hot-reload inventor_api.py from disk. Use after editing the wrapper —
    no Claude Code restart needed. Keeps the existing COM connection."""
    import importlib
    global inv
    importlib.reload(_api)
    old_app = inv._app
    inv = _api.InventorConnection()
    inv._app = old_app
    _exec_ns.clear()
    return "inventor_api.py reloaded (connection preserved)"


@mcp.tool()
def inspect() -> str:
    """Compact snapshot of the active part: volume, bbox, faces/edges count,
    feature tree with names, sketches, sheet metal thickness. One call instead
    of several diagnostic queries."""
    return json.dumps(inv.inspect(), indent=1, ensure_ascii=False)


@mcp.tool()
def list_edges(min_length: float = 0, max_count: int = 60) -> str:
    """Compact edge table of body 1: '[i] L=200.0 mid=(0.0,-225.0,0.8)' per line,
    or '[i] circle R=20.0 c=(0.0,0.0,10.0) L=125.7' for a full circle.
    Use to locate edges for flange/fillet/chamfer. min_length filters short edges (mm)."""
    return inv.list_edges(min_length=min_length, max_count=max_count)


@mcp.tool()
def list_faces(min_area: float = 0, max_count: int = 60) -> str:
    """Compact face table of body 1: '[i] Plane A=90000 c=(0.0,225.0,12.5)' per line.
    Use to locate faces for sketching/cuts. min_area filters small faces (mm²)."""
    return inv.list_faces(min_area=min_area, max_count=max_count)


@mcp.tool()
def transaction(action: str = "begin", name: str = "MCP batch") -> str:
    """Wrap multiple operations in one undo unit with rollback.

    Args:
        action: "begin" before a risky multi-step build, then "commit" on success
                or "abort" to roll back EVERYTHING since begin in one step.
        name: label shown in Inventor's undo list.
    """
    return inv.transaction(action, name)


# ---------- Connection ----------

@mcp.tool()
def connect(visible: bool = True) -> str:
    """Connect to Autodesk Inventor. Starts Inventor if not running.

    Args:
        visible: Show Inventor window (default True).
    """
    return inv.connect(visible)


@mcp.tool()
def status() -> str:
    """Check connection status and active document info."""
    if not inv.is_connected():
        return "Not connected to Inventor. Call connect() first."
    try:
        info = inv.get_document_info()
        return json.dumps(info, indent=2, ensure_ascii=False)
    except RuntimeError:
        return "Connected to Inventor, but no document is open."


# ---------- Document management ----------

@mcp.tool()
def create_part(name: str = "", template: str = "metric") -> str:
    """Create a new empty part document.

    Args:
        name: Display name for the part (optional).
        template: Template type — "metric" (mm, default), "english" (inches), or full path to .ipt file.
    """
    return inv.create_part(name or None, template)


@mcp.tool()
def save_document(path: str = "") -> str:
    """Save the active document.

    Args:
        path: Full file path to save as (e.g. "D:/parts/flange.ipt"). If empty, saves in place.
    """
    return inv.save_document(path or None)


@mcp.tool()
def export_document(path: str, format: str = "STEP") -> str:
    """Export active document to another format.

    Args:
        path: Output file path (e.g. "D:/export/part.step").
        format: Export format — STEP, STL, SAT, or IGES.
    """
    return inv.export_document(path, format)


# ---------- Sketches ----------

@mcp.tool()
def create_sketch(plane: str = "XY", face_index: int = 0, offset: float = 0) -> str:
    """Create a new sketch on a work plane, a body face, or an offset work plane.

    Args:
        plane: Work plane — XY, XZ, or YZ. Ignored if face_index > 0.
        face_index: Index of body face to sketch on (1-based). 0 = use work plane. Use list_faces() to locate.
        offset: mm — sketch on a hidden work plane parallel to 'plane' at this distance
                (positive = along plane normal: XY→+Z, XZ→+Y, YZ→+X). For ribs/bosses at a height.
    """
    fi = face_index if face_index > 0 else None
    return inv.create_sketch(plane, fi, offset)


@mcp.tool()
def draw_rectangle(
    x: float = 0, y: float = 0,
    width: float = 100, height: float = 50,
    sketch_index: int = 0,
) -> str:
    """Draw a centered rectangle in a sketch. Dimensions in mm.

    Args:
        x: Center X coordinate in mm.
        y: Center Y coordinate in mm.
        width: Width in mm.
        height: Height in mm.
        sketch_index: Sketch number (0 = latest sketch).
    """
    idx = sketch_index if sketch_index > 0 else None
    return inv.draw_rectangle(x, y, width, height, idx)


@mcp.tool()
def draw_circle(
    x: float = 0, y: float = 0,
    diameter: float = 50,
    sketch_index: int = 0,
    construction: bool = False,
) -> str:
    """Draw a circle in a sketch with an automatic diameter dimension. Dimensions in mm.

    Args:
        x: Center X coordinate in mm.
        y: Center Y coordinate in mm.
        diameter: Diameter in mm. A diameter constraint is added automatically.
        sketch_index: Sketch number (0 = latest sketch).
        construction: If True, draws a reference (construction) circle — not part of profile.
                      Useful for showing bolt PCD (pitch circle diameter) without cutting.
    """
    idx = sketch_index if sketch_index > 0 else None
    return inv.draw_circle(x, y, diameter, idx, construction)


@mcp.tool()
def draw_line(
    x1: float = 0, y1: float = 0,
    x2: float = 100, y2: float = 0,
    sketch_index: int = 0,
    construction: bool = False,
) -> str:
    """Draw a line in a sketch. Coordinates in mm.

    Args:
        x1: Start X in mm.
        y1: Start Y in mm.
        x2: End X in mm.
        y2: End Y in mm.
        sketch_index: Sketch number (0 = latest sketch).
        construction: If True, line becomes a construction line (used as revolve axis, not part of profile).
    """
    idx = sketch_index if sketch_index > 0 else None
    return inv.draw_line(x1, y1, x2, y2, idx, construction)


@mcp.tool()
def draw_polygon(
    x: float = 0, y: float = 0,
    radius: float = 25,
    sides: int = 6,
    sketch_index: int = 0,
) -> str:
    """Draw a regular polygon in a sketch. Dimensions in mm.

    Args:
        x: Center X in mm.
        y: Center Y in mm.
        radius: Circumscribed radius in mm.
        sides: Number of sides (e.g. 6 for hexagon).
        sketch_index: Sketch number (0 = latest sketch).
    """
    idx = sketch_index if sketch_index > 0 else None
    return inv.draw_polygon(x, y, radius, sides, idx)


@mcp.tool()
def draw_closed_profile(
    points: str,
    sketch_index: int = 0,
) -> str:
    """Draw a closed profile (polygon) from connected points. All coordinates in mm.
    Lines share endpoints so Inventor recognizes the closed loop for extrude/revolve.

    Args:
        points: JSON array of [x,y] pairs in mm. Example: "[[0,0],[50,0],[25,40]]" for a triangle.
        sketch_index: Sketch number (0 = latest sketch).
    """
    import json as _json
    pts = _json.loads(points)
    idx = sketch_index if sketch_index > 0 else None
    return inv.draw_closed_profile(pts, idx)


# ---------- Features ----------

@mcp.tool()
def extrude(
    distance: float = 10,
    direction: str = "positive",
    operation: str = "join",
    sketch_index: int = 0,
    extent_type: str = "distance",
) -> str:
    """Extrude a sketch profile to create 3D geometry. Distance in mm.

    Args:
        distance: Extrusion distance in mm. Ignored when extent_type="all".
        direction: Direction — positive, negative, or symmetric. Positive follows the sketch
                   normal; on a body-face sketch that points out of the body, so cut with "negative".
        operation: Boolean operation — join, cut, intersect, surface, or new.
        sketch_index: Sketch number to extrude (0 = latest sketch).
        extent_type: Extent type — "distance" (fixed distance, default) or "all" (through entire
                     body, on the chosen side only; use direction="symmetric" for both sides).
    """
    idx = sketch_index if sketch_index > 0 else None
    return inv.extrude(distance, direction, operation, idx, extent_type=extent_type)


@mcp.tool()
def revolve(
    angle: float = 360,
    axis: str = "Y",
    sketch_index: int = 0,
    operation: str = "join",
) -> str:
    """Revolve a sketch profile around a work axis to create or cut 3D geometry.

    PREFERRED workflow — no construction line needed in sketch:
      1. create_sketch("XY")
      2. draw_closed_profile([[0,0],[30,0],[30,8],[15,60],[0,60]])  ← profile only
      3. revolve(axis="Y", operation="join")

    For a revolve CUT (e.g. groove):
      1. create_sketch("XY")
      2. draw_closed_profile([[8,26],[15,26],[15,34],[8,34]])  ← groove cross-section
      3. revolve(axis="Y", operation="cut")

    Profile must be on one side of the axis (all X ≥ 0 when axis="Y").

    Args:
        angle: Revolution angle in degrees (360 = full revolution, default).
        axis: Rotation axis — "X", "Y", or "Z". Default "Y" for lathe parts on XY plane.
        sketch_index: Sketch number (0 = latest sketch).
        operation: Boolean operation — join (add material), cut (remove), intersect, or new.
    """
    idx = sketch_index if sketch_index > 0 else None
    return inv.revolve(angle, idx, axis, operation)


@mcp.tool()
def fillet(radius: float = 2, edge_indices: str = "1") -> str:
    """Add fillet (rounded edge) to edges of the solid body. Radius in mm.

    Args:
        radius: Fillet radius in mm.
        edge_indices: Comma-separated edge indices (e.g. "1,2,3"). Use status() to see edge count.
    """
    indices = [int(i.strip()) for i in edge_indices.split(",")]
    return inv.fillet(radius, indices)


@mcp.tool()
def chamfer(distance: float = 2, edge_indices: str = "1") -> str:
    """Add chamfer (angled edge) to edges of the solid body. Distance in mm.

    Args:
        distance: Chamfer distance in mm.
        edge_indices: Comma-separated edge indices (e.g. "1,2,3").
    """
    indices = [int(i.strip()) for i in edge_indices.split(",")]
    return inv.chamfer(distance, indices)


@mcp.tool()
def hole(
    x: float = 0, y: float = 0,
    diameter: float = 10,
    depth: float = 0,
    tapped: bool = False,
    pitch: float = 0,
) -> str:
    """Create a native Inventor HoleFeature. Dimensions in mm.
    Creates a proper Hole feature (not extrude cut) — works with circular_pattern.
    Supports both plain drilled holes and tapped (threaded) metric holes.

    Args:
        x: Hole center X in mm.
        y: Hole center Y in mm.
        diameter: Hole diameter in mm. For tapped holes this is the nominal thread diameter (e.g. 16 for M16).
        depth: Hole depth in mm. 0 = through-all (default).
        tapped: True = create tapped (threaded) hole with ISO Metric profile (6H). False = plain drilled hole.
        pitch: Thread pitch in mm (e.g. 2.0 for M16x2). 0 = auto-select standard coarse pitch.
    """
    p = pitch if pitch > 0 else None
    return inv.hole(x, y, diameter, depth, tapped, p)


@mcp.tool()
def hole_linear(
    face_axis: str, face_value: float,
    ref1_axis: str, ref1_value: float, dist1: float,
    ref2_axis: str, ref2_value: float, dist2: float,
    diameter: float = 5.5,
    depth: float = 0,
    tapped: bool = False,
    pitch: float = 0,
    cbore_diameter: float = 0,
    cbore_depth: float = 0,
) -> str:
    """Hole placed parametrically from two edges of a face (Linear placement).
    Survives part resizing — hole keeps its distance from the edges.
    Drill direction resolved automatically (volume check).

    Args:
        face_axis/face_value: planar face to drill into, e.g. ("z", 25) = top face at Z=25mm.
        ref1_axis/ref1_value/dist1: first edge of that face + distance from it, e.g. ("x", -34.5, 8).
        ref2_axis/ref2_value/dist2: second edge + distance.
        diameter: hole diameter mm (or thread nominal if tapped, e.g. 5 for M5).
        depth: 0 = through-all, otherwise depth in mm.
        tapped: True = ISO metric thread 6H (standard coarse pitch unless pitch given).
        pitch: thread pitch mm (0 = auto standard coarse).
        cbore_diameter/cbore_depth: >0 adds counterbore seat (M5 ISO 4762: 10 and 5.5).
    """
    p = pitch if pitch > 0 else None
    return inv.hole_linear(face_axis, face_value, ref1_axis, ref1_value, dist1,
                           ref2_axis, ref2_value, dist2, diameter, depth,
                           tapped, p, cbore_diameter, cbore_depth)


@mcp.tool()
def circular_pattern(
    feature_index: int,
    count: int = 8,
    angle: float = 360,
    axis: str = "Z",
) -> str:
    """Create a circular (rotational) pattern of a feature around a work axis.
    Ideal for bolt holes around a flange — one hole + circular_pattern instead of 8 holes.

    Args:
        feature_index: Index of the feature to pattern (from list_features()).
        count: Number of instances (total including the original).
        angle: Total span angle in degrees (360 = full circle).
        axis: Rotation axis — X, Y, or Z (default Z for flanges).
    """
    return inv.circular_pattern(feature_index, count, angle, axis)


# ---------- Parameters ----------

@mcp.tool()
def get_parameters() -> str:
    """Get all parameters of the active document. Returns JSON list."""
    params = inv.get_parameters()
    return json.dumps(params, indent=2, ensure_ascii=False)


@mcp.tool()
def set_parameter(name: str, expression: str) -> str:
    """Set a parameter value by name.

    Args:
        name: Parameter name (e.g. "d0", "width").
        expression: New value or expression (e.g. "50 mm", "d0 * 2").
    """
    return inv.set_parameter(name, expression)


@mcp.tool()
def add_parameter(name: str, expression: str, units: str = "mm") -> str:
    """Add a new user parameter.

    Args:
        name: Parameter name (e.g. "flange_diameter").
        expression: Value or expression (e.g. "100", "width * 2").
        units: Units — mm, cm, m, deg, etc.
    """
    return inv.add_parameter(name, expression, units)


# ---------- Sheet Metal ----------

@mcp.tool()
def set_sheet_metal_thickness(thickness: float = 0.8) -> str:
    """Set the active sheet metal style's thickness. Use after create_part(template="sheet_metal")."""
    return inv.set_sheet_metal_thickness(thickness)


@mcp.tool()
def sheet_metal_face(sketch_index: int = 0) -> str:
    """Create a base Sheet Metal Face from a closed sketch profile.
    The first flat panel in a sheet metal part. Uses style's Thickness automatically."""
    idx = sketch_index if sketch_index > 0 else None
    return inv.sheet_metal_face(idx)


@mcp.tool()
def flange(edge_indices: str, distance: float = 25, angle: float = 90) -> str:
    """Add a Sheet Metal Flange (bent wall) to one or more edges.

    Real sheet-metal feature (vs Extrude) — supports Flat Pattern unfolding,
    has proper bend radius, depth ties to Thickness.

    Args:
        edge_indices: Comma-separated edge indices (use find_edge to locate).
        distance: Flange height in mm (default 25 = Inventor default).
        angle: Bend angle in degrees (default 90 = perpendicular).
    """
    idx_list = [int(i.strip()) for i in edge_indices.split(",")]
    return inv.flange(idx_list, distance, angle)


@mcp.tool()
def sheet_metal_cut(sketch_index: int = 0) -> str:
    """Cut through the panel — depth = Thickness automatically (parametric!).
    Sketch should be on the panel face (not a work plane) for correct behavior.
    One sketch with multiple closed shapes = one Cut feature with multiple holes.
    """
    idx = sketch_index if sketch_index > 0 else None
    return inv.sheet_metal_cut(idx)


@mcp.tool()
def find_edge(x: float = 0, y: float = 0, z: float = 0,
              use_x: bool = False, use_y: bool = False, use_z: bool = False,
              tolerance: float = 0.1) -> str:
    """Find an edge by its midpoint coordinates (mm). Returns edge index (string).
    The midpoint is taken along the curve; a full circle matches by its center.
    Useful for flange — locate the edge to bend without printing all edges.

    Args:
        x/y/z: Target midpoint coordinates (mm).
        use_x/y/z: Set True for each coord that should be matched (False = ignored).
        tolerance: How close midpoint must be (mm). Default 0.1.
    """
    kwargs = {}
    if use_x: kwargs['x'] = x
    if use_y: kwargs['y'] = y
    if use_z: kwargs['z'] = z
    idx = inv.find_edge(tolerance=tolerance, **kwargs)
    return f"Edge {idx}"


@mcp.tool()
def find_face(x: float = 0, y: float = 0, z: float = 0,
              use_x: bool = False, use_y: bool = False, use_z: bool = False,
              min_area: float = 100, tolerance: float = 0.5) -> str:
    """Find a planar face by its centroid coordinates (mm). Returns face index (string).
    Useful for sheet metal Cut — locate the outer panel face to sketch on.

    Args:
        x/y/z: Target centroid coordinates (mm).
        use_x/y/z: Set True for each coord that should be matched.
        min_area: Minimum area in mm² (filters tiny edge faces). Default 100.
        tolerance: Centroid match tolerance (mm). Default 0.5.
    """
    kwargs = {}
    if use_x: kwargs['x'] = x
    if use_y: kwargs['y'] = y
    if use_z: kwargs['z'] = z
    idx = inv.find_face(min_area=min_area, tolerance=tolerance, **kwargs)
    return f"Face {idx}"


# ---------- Query ----------

@mcp.tool()
def list_features() -> str:
    """List all features in the active part. Returns JSON list."""
    features = inv.list_features()
    return json.dumps(features, indent=2, ensure_ascii=False)


@mcp.tool()
def delete_feature(indices: str) -> str:
    """Delete one or more features by index. Use list_features() to find indices.

    Args:
        indices: Comma-separated feature indices to delete (e.g. "3,4,5"). Deletes in reverse order automatically.
    """
    idx_list = [int(i.strip()) for i in indices.split(",")]
    return inv.delete_feature(idx_list)


@mcp.tool()
def suppress_feature(indices: str, suppressed: bool = True) -> str:
    """Suppress or unsuppress features (hide without deleting). Use list_features() to find indices.

    Args:
        indices: Comma-separated feature indices (e.g. "3,4,5").
        suppressed: True to suppress (hide), False to unsuppress (show).
    """
    idx_list = [int(i.strip()) for i in indices.split(",")]
    return inv.suppress_feature(idx_list, suppressed)


# ---------- Drawings ----------
# Sheet positions are mm from the sheet's bottom-left corner. Points inside a view
# are mm in model units from the view center (x right, y up on the sheet).

@mcp.tool()
def create_drawing(profile: str = "default", template: str = "", sheet_size: str = "") -> str:
    """Create a drawing (.idw) set up by a drawing profile. Following drawing tools act on it.

    A profile (drawing_profiles/<name>.json, see docs/drawing-profiles.md) sets template,
    sheet size, projection angle, units, dimension format and view label formats.
    The default profile: third angle, mm, no trailing zeros, no sheet-zone references.

    Args:
        profile: profile name.
        template: optional .idw path overriding the profile's template. Templates from
                  older Inventor releases must be opened and saved once first.
        sheet_size: optional A0..A4 overriding the profile's sheet size.
    """
    return inv.create_drawing(profile, template, sheet_size)


@mcp.tool()
def add_base_view(model_path: str, x: float, y: float, scale: float = 1.0,
                  orientation: str = "front", style: str = "visible") -> str:
    """Place the first view of a part or assembly file, centered at (x, y) on the sheet.
    A view that would leave the border or overlap the title block or another view is
    removed again and an error says why.

    Args:
        model_path: .ipt or .iam file.
        x, y: view center on the sheet, mm.
        scale: 1.0 = 1:1, 0.5 = 1:2.
        orientation: front, top, right, back, bottom, left, iso_top_right, iso_top_left,
                     iso_bottom_right, iso_bottom_left. "front" looks along the part's -Z axis.
        style: visible (hidden lines removed), hidden (hidden lines shown), shaded, shaded_hidden.
    """
    return inv.add_base_view(model_path, x, y, scale, orientation, style)


@mcp.tool()
def add_projected_view(parent: str, x: float, y: float, style: str = "from_base") -> str:
    """Orthographic or isometric view projected from a parent view, centered at (x, y).
    Third angle (default profile): a view placed above the parent is the top view, to the
    right the right-side view. First angle swaps the sides.

    Args:
        parent: name of the parent view (from list_views, e.g. "VIEW1").
        x, y: view center on the sheet, mm.
        style: from_base, visible, hidden, shaded, shaded_hidden.
    """
    return inv.add_projected_view(parent, x, y, style)


@mcp.tool()
def add_section_view(parent: str, x1: float, y1: float, x2: float, y2: float,
                     x: float, y: float, label: str = "A", style: str = "from_base") -> str:
    """Section view cut along the line (x1, y1)-(x2, y2) of the parent view, centered at (x, y).

    Args:
        parent: name of the parent view.
        x1, y1, x2, y2: section line ends, model mm from the parent view center.
                        Extend the line past the part outline.
        x, y: section view center on the sheet, mm. It stays aligned with the parent.
        label: section letter, e.g. "A" for A-A.
        style: from_base, visible, hidden, shaded, shaded_hidden.
    """
    return inv.add_section_view(parent, x1, y1, x2, y2, x, y, label, style)


@mcp.tool()
def add_detail_view(parent: str, cx: float, cy: float, radius: float, x: float, y: float,
                    scale: float = 2.0, label: str = "B", style: str = "from_base") -> str:
    """Enlarged circular detail of part of a view, centered at (x, y) on the sheet.

    Args:
        parent: name of the parent view.
        cx, cy: detail circle center, model mm from the parent view center.
        radius: detail circle radius, model mm.
        x, y: detail view center on the sheet, mm.
        scale: detail scale, e.g. 2.0 for 2:1.
        label: detail letter.
    """
    return inv.add_detail_view(parent, cx, cy, radius, x, y, scale, label, style)


@mcp.tool()
def retrieve_dimensions(view: str) -> str:
    """Bring the model's sketch and feature dimensions into a view, arrange them, and
    push overlapping texts apart. Reports any text overlaps that remain on the sheet."""
    return inv.retrieve_dimensions(view)


@mcp.tool()
def add_centerlines(view: str) -> str:
    """Automatic centerlines and center marks for holes, cylinders, revolved features
    and circular patterns in a view."""
    return inv.add_centerlines(view)


@mcp.tool()
def add_dimension(view: str, kind: str, x1: float, y1: float,
                  x2: float | None = None, y2: float | None = None,
                  text_x: float = 0, text_y: float = 0) -> str:
    """Add one dimension to a view. Points are model mm from the view center; each picks
    the nearest visible curve.

    Args:
        view: view name.
        kind: diameter or radius (curve nearest x1, y1); pcd (circular centerline such as
              a bolt circle nearest x1, y1, after add_centerlines); or horizontal, vertical,
              aligned (distance between the curves nearest x1, y1 and x2, y2).
        x1, y1, x2, y2: points on or near the curves to dimension.
        text_x, text_y: where the dimension text goes, same frame.
    """
    return inv.add_dimension(view, kind, x1, y1, x2, y2, text_x, text_y)


@mcp.tool()
def add_hole_note(view: str, x: float, y: float, text_x: float, text_y: float) -> str:
    """Hole note on the hole edge nearest (x, y), e.g. "4x Ø11 THRU" for patterned holes.
    The quantity prefix comes from the drawing profile. Points are model mm from the view center."""
    return inv.add_hole_note(view, x, y, text_x, text_y)


@mcp.tool()
def list_dimensions() -> str:
    """Dimensions on the active sheet: index, text, text center (sheet mm), nearest view.
    Use the index with delete_dimension, e.g. to drop a dimension shown twice."""
    return json.dumps(inv.list_dimensions(), indent=1, ensure_ascii=False)


@mcp.tool()
def delete_dimension(indices: str) -> str:
    """Delete dimensions by index from list_dimensions.

    Args:
        indices: comma-separated, e.g. "4,5".
    """
    return inv.delete_dimension([int(i.strip()) for i in indices.split(",")])


@mcp.tool()
def move_dimension(index: int, text_x: float, text_y: float) -> str:
    """Move a dimension's text (index from list_dimensions), e.g. off another note.
    text_x, text_y: model mm from the center of the dimension's view."""
    return inv.move_dimension(index, text_x, text_y)


@mcp.tool()
def set_tolerance(index: int, kind: str, upper: float = 0, lower: float = 0, fit: str = "") -> str:
    """Put a tolerance on a dimension (index from list_dimensions). Values in mm.

    Args:
        index: dimension index.
        kind: symmetric (±upper), deviation (+upper / -lower), limits, fit, basic,
              reference, or default (removes the tolerance).
        upper, lower: tolerance values in mm (lower as a positive number).
        fit: ISO fit for kind "fit": upper case for a hole ("H7"), lower case for a shaft ("h6").
    """
    return inv.set_tolerance(index, kind, upper, lower, fit)


@mcp.tool()
def add_gdt(view: str, x: float, y: float, text_x: float, text_y: float,
            characteristic: str, tolerance: float, datums: str = "",
            diameter_zone: bool = False) -> str:
    """Feature control frame, with a leader to the curve nearest (x, y).

    Args:
        view: view name.
        x, y: point on the controlled feature, model mm from the view center.
        text_x, text_y: where the frame goes, same frame.
        characteristic: straightness, flatness, circularity, cylindricity, profile_line,
                        profile_surface, angularity, perpendicularity, parallelism,
                        position, concentricity, symmetry, circular_runout, total_runout.
        tolerance: tolerance value in mm, e.g. 0.05.
        datums: datum letters in order of precedence, e.g. "A,B".
        diameter_zone: True puts Ø before the value (cylindrical zone, e.g. for position).
    """
    return inv.add_gdt(view, x, y, text_x, text_y, characteristic, tolerance, datums, diameter_zone)


@mcp.tool()
def add_datum(view: str, x: float, y: float, label: str, text_x: float, text_y: float) -> str:
    """Datum feature symbol: the letter in a box at (text_x, text_y), with a filled triangle
    on the curve nearest (x, y). Points are model mm from the view center."""
    return inv.add_datum(view, x, y, label, text_x, text_y)


@mcp.tool()
def add_surface_finish(view: str, x: float, y: float, text_x: float, text_y: float,
                       roughness: str = "Ra 3,2", removal: str = "required") -> str:
    """Surface texture symbol with a leader to the curve nearest (x, y).

    Args:
        roughness: e.g. "Ra 3,2" or "Ra 1,6".
        removal: required (machined surface), prohibited, or any.
    """
    return inv.add_surface_finish(view, x, y, text_x, text_y, roughness, removal)


@mcp.tool()
def set_title_block(fields: str) -> str:
    """Fill title block fields by the names the title block shows, and return what it shows.

    Each field goes where the title block reads it: a prompt on the sheet, an iProperty of
    the drawing, or an iProperty of the model in the first view (then the model changes
    and save_document saves it too). MATERIAL sets the part's material from the active
    material library. An unknown name lists the fields the title block has.

    Args:
        fields: JSON object. Arjuna template: {"TITLE": "Flens Kopling", "PART NUMBER": "KF-001",
                "ENGINEER": "Rizal", "CHECKED BY": "...", "REVISION NUMBER": "1",
                "MATERIAL": "Aluminum 6061", "SURFACE FINISH": "Ra 3.2"}.
                Underscores and lower case work too ("part_number").
    """
    return inv.set_title_block(json.loads(fields))


@mcp.tool()
def list_views() -> str:
    """Views on the active sheet with scale, center and box (mm), plus layout problems:
    views outside the border, overlapping views or title block, overlapping texts."""
    return json.dumps(inv.list_views(), indent=1, ensure_ascii=False)


@mcp.tool()
def export_sheet_png(path: str, width: int = 2000) -> str:
    """Save a picture of the whole active sheet. Open it to check the layout by eye.

    Args:
        path: output .png path.
        width: image width in pixels; height follows the sheet's aspect ratio.
    """
    return inv.export_sheet_png(path, width)


@mcp.tool()
def export_pdf(path: str, all_sheets: bool = True, black_lines: bool = True) -> str:
    """Export the active drawing to PDF.

    Args:
        path: output .pdf path.
        all_sheets: False exports only the active sheet.
        black_lines: print all colors as black.
    """
    return inv.export_pdf(path, all_sheets, black_lines)


def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
