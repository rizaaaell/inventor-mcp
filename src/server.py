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
                  orientation: str = "front", style: str = "visible",
                  design_view: str = "", positional: str = "",
                  spin: float = 0, spin_axis: str = "Z", weldment_state: str = "") -> str:
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
        design_view: assembly design view representation to show, e.g. "Default".
        positional: assembly positional representation to show.
        spin: degrees to turn the view camera about the model axis spin_axis (X, Y or Z).
              An iso view of a flange with holes at 0/90/180/270 degrees shows pairs of
              bolts on one line; spin 30 about the flange axis separates them.
        weldment_state: for a weldment: assembly, preparations, welds (default for a
              weldment, shows the welds) or machining.
    """
    return inv.add_base_view(model_path, x, y, scale, orientation, style, design_view, positional,
                             spin, spin_axis, weldment_state)


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
                     x: float, y: float, label: str = "A", style: str = "from_base",
                     no_hatch: str = "") -> str:
    """Section view cut along the line (x1, y1)-(x2, y2) of the parent view, centered at (x, y).

    Args:
        parent: name of the parent view.
        x1, y1, x2, y2: section line ends, model mm from the parent view center.
                        Extend the line past the part outline.
        x, y: section view center on the sheet, mm. It stays aligned with the parent.
        label: section letter, e.g. "A" for A-A.
        style: from_base, visible, hidden, shaded, shaded_hidden.
        no_hatch: assembly components to draw unhatched, comma-separated, e.g.
                  "Poros:1, Poros:2" for shafts cut along their axis. Content Center
                  fasteners are left unhatched by Inventor already.
    """
    return inv.add_section_view(parent, x1, y1, x2, y2, x, y, label, style, no_hatch)


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
                  text_x: float = 0, text_y: float = 0, prefix: str = "",
                  vertex_x: float = 0, vertex_y: float = 0, suffix: str = "") -> str:
    """Add one dimension to a view. Points are model mm from the view center; each picks
    the nearest visible curve.

    Args:
        view: view name.
        kind: diameter or radius (curve nearest x1, y1); pcd (circular centerline such as
              a bolt circle nearest x1, y1, after add_centerlines); horizontal, vertical,
              aligned (distance between the curves nearest x1, y1 and x2, y2); or angle
              (between the centers of the circles nearest x1, y1 and x2, y2, around the
              center of the circle nearest vertex_x, vertex_y; e.g. bolt hole spacing).
              Without x2, y2 the angle runs from the horizontal axis through the vertex
              (its right side, 0°) to the hole at x1, y1: the orientation of holes that are off the axes.
        x1, y1, x2, y2: points on or near the curves to dimension.
        text_x, text_y: where the dimension text goes, same frame. Keep it outside the part.
        prefix: text before the value, "Ø" for a diameter dimensioned in a side or section
                view (the usual place for diameters of turned parts).
        vertex_x, vertex_y: for kind "angle", a point on the circle at the vertex (e.g. the bore).
        suffix: text after the value, "
" starts a new line. A hole pattern is one diameter
                dimension: prefix "4x ", suffix " THRU
ON PCD 76, EQ SP".
    """
    return inv.add_dimension(view, kind, x1, y1, x2, y2, text_x, text_y, prefix, vertex_x, vertex_y,
                             suffix)


@mcp.tool()
def add_hole_note(view: str, x: float, y: float, text_x: float, text_y: float,
                  second_line: str = "", count: int = 0) -> str:
    """Hole note on the hole edge nearest (x, y), e.g. "4x Ø11 THRU" for patterned holes, or a
    thread note on a threaded shaft seen from the side (point on the thread line), e.g.
    "M42x1.5 - 6g".
    The quantity prefix comes from the drawing profile and only counts holes of one
    patterned feature; count > 0 writes "<count>x" for holes made as separate features.
    second_line goes under it, e.g. "EQ SP ON PCD Ø90" to give the bolt circle in the same
    note. Points are model mm from the view center."""
    return inv.add_hole_note(view, x, y, text_x, text_y, second_line, count)


@mcp.tool()
def add_chamfer_note(view: str, x: float, y: float, ref_x: float, ref_y: float,
                     text_x: float, text_y: float, prefix: str = "") -> str:
    """Chamfer note ("1 x 45°") on the chamfer line nearest (x, y), against the adjacent
    edge nearest (ref_x, ref_y). Use a view where the chamfer shows as a slanted line.

    Args:
        prefix: count of equal chamfers, e.g. "2x ".
        text_x, text_y: note position, model mm from the view center, outside the part.
    """
    return inv.add_chamfer_note(view, x, y, ref_x, ref_y, text_x, text_y, prefix)


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
            diameter_zone: bool = False, attach: bool = True, leader: bool = True,
            dimension: int = 0) -> str:
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
        attach: False ends the leader exactly at (x, y), e.g. on an extension line.
        leader: False places the bare frame at (text_x, text_y).
        dimension: index from list_dimensions; the frame goes right under that dimension's
                   text with no leader (x, y, text_x, text_y ignored). Use it for a size
                   feature: position under the hole note, runout under a diameter.
    """
    return inv.add_gdt(view, x, y, text_x, text_y, characteristic, tolerance, datums,
                       diameter_zone, attach, leader, dimension)


@mcp.tool()
def add_datum(view: str, x: float, y: float, label: str, text_x: float, text_y: float,
              attach: bool = True, dimension: int = 0) -> str:
    """Datum feature symbol: the letter in a box at (text_x, text_y), with a filled triangle
    on the curve nearest (x, y). attach False puts the triangle exactly at (x, y), e.g. on
    the extension line of a diameter dimension to make the axis the datum.
    dimension: index from list_dimensions; the triangle goes on the outer end of that size
    dimension's text shoulder, box below it (x, y, text_x, text_y ignored). This is how an
    axis (bore, shaft seat) becomes a datum.
    Points are model mm from the view center."""
    return inv.add_datum(view, x, y, label, text_x, text_y, attach, dimension)


@mcp.tool()
def add_surface_finish(view: str, x: float, y: float, text_x: float, text_y: float,
                       roughness: str = "Ra 3,2", removal: str = "required",
                       attach: bool = True) -> str:
    """Surface texture symbol with a leader to the curve nearest (x, y).

    Args:
        roughness: e.g. "Ra 3,2" or "Ra 1,6".
        removal: required (machined surface), prohibited, or any.
        attach: False ends the leader exactly at (x, y), e.g. on an extension line.
    """
    return inv.add_surface_finish(view, x, y, text_x, text_y, roughness, removal, attach)


@mcp.tool()
def set_title_block(fields: str) -> str:
    """Fill title block fields by the names the title block shows, and return what it shows.

    Each field goes where the title block reads it: a prompt on the sheet, an iProperty of
    the drawing, or an iProperty of the model in the first view (then the model changes
    and save_document saves it too). An unknown name lists the fields the title block has.

    MATERIAL is always stated. The first view fills it automatically: a part's material,
    the one material all parts of an assembly share, the profile's statement for mixed
    materials ("VARIOUS, SEE PART DRAWINGS"), or "NONE" when nothing is assigned (Generic).
    Passing a library material name also gives a part that material; "NONE" or any other
    statement is printed as given; "auto" recomputes it.

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


# ---------- Assemblies ----------

@mcp.tool()
def create_assembly(template: str = "") -> str:
    """Create a new assembly (.iam) and make it the document the next tools work on.

    Args:
        template: template path; empty uses Inventor's Metric "Standard (mm).iam".
    """
    return inv.create_assembly(template)


@mcp.tool()
def place_component(path: str, x: float = 0, y: float = 0, z: float = 0, rx: float = 0,
                    ry: float = 0, rz: float = 0, grounded: bool = False) -> str:
    """Place a saved part or assembly file in the active assembly.

    Args:
        path: .ipt or .iam file. Placing the same file again adds another instance (Name:2, ...).
        x, y, z: position of the part origin in mm.
        rx, ry, rz: rotation in degrees about X, then Y, then Z.
        grounded: fix the component in place (ground the first one).
    """
    return inv.place_component(path, x, y, z, rx, ry, rz, grounded)


@mcp.tool()
def list_content_center(category: str = "", family: str = "", contains: str = "") -> str:
    """Browse Inventor's Content Center library.

    Args:
        category: path such as "Fasteners/Bolts/Hex Head"; empty lists the top categories.
        family: with a category, lists that family's sizes, e.g. "DIN 933".
        contains: filter families or sizes by this text, e.g. "DIN" or "M10".
    """
    return json.dumps(inv.list_content_center(category, family, contains), indent=1, ensure_ascii=False)


@mcp.tool()
def place_content_center(category: str, family: str, size: str, x: float = 0, y: float = 0,
                         z: float = 0, rx: float = 0, ry: float = 0, rz: float = 0,
                         grounded: bool = False) -> str:
    """Place a standard part from Content Center in the active assembly.

    The part file is generated into the active project's Content Center folder on first
    use. Content Center parts have their axis along X: a bolt's head bearing face, a
    nut's face and a washer's face lie on x = 0 (circle:0,0,0,r selectors).

    Args:
        category: e.g. "Fasteners/Bolts/Hex Head", "Fasteners/Nuts/Hex", "Fasteners/Washers/Plain".
        family: full name or unique start, e.g. "DIN 933", "DIN 934", "DIN 125-1 A".
        size: designation as list_content_center shows it; spacing and decimal mark
              are ignored, e.g. "M10 x 60", "M10", "A 10.5".
        x, y, z, rx, ry, rz, grounded: as in place_component.
    """
    return inv.place_content_center(category, family, size, x, y, z, rx, ry, rz, grounded)


@mcp.tool()
def list_occurrences() -> str:
    """Components in the active assembly with file, grounded state, origin (mm) and free DOF."""
    return json.dumps(inv.list_occurrences(), indent=1, ensure_ascii=False)


@mcp.tool()
def list_occurrence_geometry(occurrence: str, kind: str = "circles") -> str:
    """Selectors for a component's circular edges or planar faces, to pick constraint geometry.

    Args:
        occurrence: component name, e.g. "Flens:1".
        kind: "circles" or "planes".
    """
    return json.dumps(inv.list_occurrence_geometry(occurrence, kind), indent=1)


@mcp.tool()
def add_constraint(kind: str, occurrence1: str, geometry1: str, occurrence2: str, geometry2: str,
                   offset: float = 0, angle: float = 0, opposed: bool = True, name: str = "") -> str:
    """Constrain two components. The second one moves to meet the first.

    Args:
        kind: mate, flush, insert, angle or tangent.
        occurrence1, occurrence2: component names, or "assembly".
        geometry1, geometry2: geometry selectors (see below).
        offset: mm. For insert, a negative offset pushes the second component into the first.
        angle: degrees, for kind angle.
        opposed: for insert, True when the two axes point against each other (bolt into hole).
        name: constraint name; empty builds one from the kind and components.

    Geometry selectors, in the component's own part coordinates (mm):
        plane:XY | plane:XZ | plane:YZ   origin work plane
        axis:X | axis:Y | axis:Z         origin work axis
        circle:x,y,z,r                   circular edge with that center and radius
        face:x,y,z                       face nearest the point (within 1 mm)
        cylinder:x,y,z                   cylindrical or conical face nearest the point
        edge:x,y,z                       edge nearest the point
    Component "assembly" means the assembly's own origin planes and axes.

    Every constraint is logged in order; save_document writes the log next to the .iam
    as <name>.constraints.json.
    """
    return inv.add_constraint(kind, occurrence1, geometry1, occurrence2, geometry2,
                              offset, angle, opposed, name)


@mcp.tool()
def get_dof(occurrence: str = "") -> str:
    """Free translations and rotations per component; empty checks all of them."""
    return json.dumps(inv.get_dof(occurrence), indent=1)


@mcp.tool()
def get_bom(view: str = "parts") -> str:
    """Bill of materials of the active assembly.

    Args:
        view: "parts" (parts only, quantities summed) or "structured" (top level).
    """
    return json.dumps(inv.get_bom(view), indent=1, ensure_ascii=False)


@mcp.tool()
def analyze_interference() -> str:
    """Overlapping component pairs with volume (mm³) and centroid. Pairs with a tapped hole
    against a threaded part are thread artifacts, since tapped holes are modelled at the minor diameter."""
    return json.dumps(inv.analyze_interference(), indent=1)


@mcp.tool()
def pattern_component(occurrences: str, axis_occurrence: str, axis: str, count: int,
                      angle: float = 360) -> str:
    """Circular pattern of components about an axis, e.g. a bolt set around a flange.

    Args:
        occurrences: comma-separated component names, e.g. "Baut:1, Mur:1, Ring:1".
        axis_occurrence: component that owns the axis, or "assembly".
        axis: axis selector such as "axis:Z", or "cylinder:x,y,z" for a face's axis.
        count: number of instances including the original.
        angle: total span in degrees; 360 spreads them evenly around.
    """
    return inv.pattern_component(occurrences, axis_occurrence, axis, count, angle)


@mcp.tool()
def add_parts_list(view: str, x: float = 0, y: float = 0, level: str = "parts", hide: str = "") -> str:
    """Parts list (ITEM, QTY, PART NUMBER, DESCRIPTION) of an assembly view.

    Args:
        view: name of a view of the assembly.
        x, y: top right corner on the sheet, mm. Leave both 0 to stack it on the title
              block against the right border, as the Arjuna drawings do.
        level: parts (parts only), structured (first level) or all_levels.
        hide: rows to leave out, by part number or file name separated by ';', e.g. an
              unused variant part kept in the assembly. The other rows are renumbered.
    """
    return inv.add_parts_list(view, x, y, level, hide)


@mcp.tool()
def set_component_visibility(view: str, occurrences: str, visible: bool = False) -> str:
    """Hide (or show) assembly components in one drawing view only; the assembly file and
    its design views stay as they are. Use it for variant or reference parts that should
    not be drawn. Then leave them out of the parts list with add_parts_list(hide=...).

    Args:
        view: view name.
        occurrences: comma-separated component names, e.g. "Shaft_variant:1".
        visible: False hides, True shows.
    """
    return inv.set_component_visibility(view, occurrences, visible)


@mcp.tool()
def add_balloons(view: str, gap: float = 12) -> str:
    """Balloon every parts list item that is visible in an assembly view.

    Balloons go in a row above the view for components in its upper half and below it
    for the lower half, sorted so leaders do not cross. Add the parts list first so the
    item numbers match it. Check the result with list_views or export_sheet_png.

    Args:
        view: name of a view of the assembly.
        gap: distance from the view box to the balloon row, mm.
    """
    return inv.add_balloons(view, gap)


@mcp.tool()
def create_exploded_copy(assembly: str, path: str) -> str:
    """Copy an assembly with its constraints and patterns removed, for an exploded view.

    Inventor 2027's presentation API cannot add tweaks or snapshot views, so exploded
    drawings come from this copy: move components with explode_components, save, then
    place a drawing view of the copy. The copy uses the same part files and the original
    assembly is not changed. The copy becomes the active document.

    Args:
        assembly: .iam to copy.
        path: new .iam path, e.g. "C:/inventor-test/coupling/Kopling_exploded.iam".
    """
    return inv.create_exploded_copy(assembly, path)


@mcp.tool()
def explode_components(occurrences: str, dx: float = 0, dy: float = 0, dz: float = 0) -> str:
    """Move components of the active exploded copy by (dx, dy, dz) mm, assembly coordinates.

    Move outward from the part that stays (usually the grounded one), in assembly order:
    e.g. a nut further than its washer. Each move is logged in <copy>.explode.json for
    add_explode_trails. Run save_document afterwards.

    Args:
        occurrences: comma-separated component names, e.g. "Flens:2, Poros:2".
    """
    return inv.explode_components(occurrences, dx, dy, dz)


@mcp.tool()
def add_explode_trails(view: str) -> str:
    """Thin chain trail lines in a drawing view of an exploded copy, from each moved
    component back to its assembled position; trails on one line are merged."""
    return inv.add_explode_trails(view)


@mcp.tool()
def move_view(view: str, x: float = 0, y: float = 0, scale: float = 0) -> str:
    """Move a drawing view's centre to (x, y) sheet mm and/or change its scale (0 keeps it).
    Views projected from it follow. A position that leaves the border or overlaps the title
    block, another view or the parts list is undone and reported."""
    return inv.move_view(view, x, y, scale)


@mcp.tool()
def delete_view(view: str) -> str:
    """Delete a drawing view; views projected, cut or detailed from it go with it."""
    return inv.delete_view(view)


@mcp.tool()
def list_notes() -> str:
    """Hole and chamfer notes on the active sheet: index, kind, text, centre (sheet mm)."""
    return json.dumps(inv.list_notes(), indent=1, ensure_ascii=False)


@mcp.tool()
def delete_note(indices: str) -> str:
    """Delete hole or chamfer notes by index from list_notes (comma-separated), e.g. to
    place one again with other text or position."""
    return inv.delete_note(indices)


@mcp.tool()
def set_properties(model_path: str, fields: str) -> str:
    """Write iProperties of a part or assembly file and save it.

    Part Number and Description are what BOMs and parts lists show (Part Number defaults to
    the file name). Known names: Part Number, Description, Stock Number, Vendor, Project,
    Designer, Engineer, Checked By, Revision Number, Title, Subject, Author, Comments; MATERIAL
    sets a part's material from the active library; any other name becomes a custom property.

    Args:
        model_path: .ipt or .iam file.
        fields: JSON object, e.g. {"Part Number": "KF-001", "Description": "Coupling flange"}.
    """
    return inv.set_properties(model_path, json.loads(fields))


@mcp.tool()
def auto_explode(spacing: float = 20, axis: str = "Z") -> str:
    """Explode the active exploded copy (from create_exploded_copy) along one assembly axis.

    Uses the constraint log of the source assembly (written by save_document): each
    component moves off the face it was inserted or mated onto, far enough to clear its
    parent plus spacing, and moves add up along the chain (washer, then bolt beyond it).
    Pattern instances follow their original. Works for parts stacked along one axis, such
    as shafts, flanges and bolt sets; move anything else with explode_components. Run
    save_document afterwards.

    Args:
        spacing: gap in mm between a component and the one it sat on.
        axis: X, Y or Z of the assembly.
    """
    return inv.auto_explode(spacing, axis)


@mcp.tool()
def create_weldment(template: str = "") -> str:
    """Create a weldment assembly (Inventor's ISO weldment template by default). Place and
    constrain the parts with place_component / add_constraint as in any assembly, then add
    welds with add_cosmetic_weld. Inventor 2027's API cannot create weld beads (solid fillet
    or groove welds); cosmetic welds plus welding symbols on the drawing are the route."""
    return inv.create_weldment(template)


@mcp.tool()
def add_cosmetic_weld(occurrence: str, edges: str, leg: float = 0) -> str:
    """Cosmetic weld along edges of one component of the active weldment.

    Args:
        occurrence: component whose edges the weld runs along, e.g. "Upright_Plate:1".
        edges: edge selectors in that component's part coordinates, separated by ';'
               (selectors contain commas), e.g. "edge:0,-30,0; edge:0,-30,10".
        leg: fillet leg in mm; the weld's cross-section (leg^2 / 2) then counts in mass.
    """
    return inv.add_cosmetic_weld(occurrence, edges, leg)


@mcp.tool()
def add_weld_symbol(view: str, x: float, y: float, text_x: float, text_y: float,
                    kind: str = "fillet", size: str = "", length: str = "", sides: str = "arrow",
                    all_around: bool = False, field: bool = False, tail: str = "",
                    attach: bool = True) -> str:
    """ISO 2553 welding symbol whose arrow points at the joint nearest (x, y) in a view.

    Args:
        view: view name. Points are model mm from the view center.
        x, y: point on the joint line the arrow points at.
        text_x, text_y: where the reference line starts.
        kind: fillet, square (I butt), v, bevel, u, j, flare_v, flare_bevel, plug, slot,
              spot, seam, back, surfacing, scarf, stud.
        size: "a4" (fillet throat) or "z5" (leg) for fillets, "s8" for butt welds, "d5"
              for spot welds.
        length: weld length, "50", or "3x50(100)" for an intermittent weld.
        sides: arrow (weld on the side the arrow points at; dashed identification line
               under the reference line), other (far side; symbol on the dashed line),
               both (symmetrical, e.g. fillets on both sides of a plate).
        all_around: circle at the joint for a weld all around.
        field: flag for a weld made on site.
        tail: process number or note in the tail, e.g. "135" (MAG).
        attach: False ends the arrow exactly at (x, y).
    """
    return inv.add_weld_symbol(view, x, y, text_x, text_y, kind, size, length, sides,
                               all_around, field, tail, attach)


def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
