---
name: inventor-modeling
description: Build parametric 3D parts in Autodesk Inventor 2027 (also 2026) via the project's MCP server. Use this skill whenever the user wants to create, modify, or inspect Inventor parts (.ipt) — building flanges, shafts, nuts, brackets, machine parts; drilling holes; adding fillets, chamfers, revolves, extrudes; saving or exporting parts; or troubleshooting "why didn't my hole cut" / "edge index changed" / "chamfer failed" issues. Triggers on Indonesian phrases like "bikin part", "buat flens", "tambah lubang", "chamfer", "fillet", Ukrainian phrases like "побудуй деталь", "зроби фланець", "додай отвір", and English equivalents. For drawings use inventor-drawing, for assemblies inventor-assembly. Use whenever the user mentions DIN/ISO standard parts, mechanical engineering CAD work, or the `mcp__inventor__*` tools.
---

# Autodesk Inventor 2027 — Parametric Modeling via MCP

## When this skill applies

Any task involving the inventor-mcp server: `mcp__inventor__connect`, `create_part`, `extrude`, `revolve`, `hole`, `chamfer`, `fillet`, `circular_pattern`, etc. Also any direct Python work against `src/inventor_api.py` in `the inventor-mcp project root\`.

Keep explanations concrete; the result that matters is the model in Inventor, not the code.

## Token-efficient workflow (USE THESE FIRST)

The MCP server has power tools that replace ad-hoc console scripts:

- **`execute_python(code)`** — runs Python against live `inv`/`app`/`doc`/`comp`/`body`/`tg`
  objects with a persistent namespace and auto-connect. Use this instead of
  `python -c "..."` console scripts with 10 lines of import boilerplate.
- **`reload_api()`** — hot-reloads `inventor_api.py` after editing it. No Claude Code
  restart needed (new TOOL schemas still need a restart; new wrapper METHODS don't —
  call them via `execute_python`).
- **`inspect()`** — one-call part snapshot (features, volume, bbox, sketches).
- **`list_edges(min_length=...)` / `list_faces(min_area=...)`** — compact topology
  tables; no more hand-written vertex-iteration loops.
- **`transaction("begin"/"commit"/"abort")`** — wrap risky multi-step builds;
  abort rolls back everything in one call (no manual feature deletion).

Feature tools (extrude, hole, flange, ...) return an auto-report suffix like
`| V 23497 (-503 mm³) | F7 E14` — separate volume-check calls are unnecessary.

## Inventor 2027 differences (verified on 2027.1)

- Face type codes changed meaning against the old notes: 5890 plane, 5891 cylinder,
  5893 cone, 5895 torus, 5896 sphere, 5897 B-spline (5892 / 5894 are the elliptical
  variants). `list_faces` / `find_face` use the 2027 table.
- A cut sketched **on a body face** must go `direction="negative"`: the sketch normal points
  out of the body, and a positive cut removes nothing without an error.
- `hole()` drills from the XY plane and cuts a body above or below it, through-all and blind
  tapped alike. Tapped holes are cut at the minor diameter (M10x1.5: 8.376 mm).
- A chamfer on one edge of a loop tangent to fillets runs around the whole tangent chain.
- New documents can raise a **Style Conflict** dialog that blocks every COM call;
  `create_part` sets `SilentOperation` around `Documents.Add` so it does not appear.
  Other dialogs (template migration, errors) still block: if a call hangs, ask the user
  to look at Inventor. Never click or dismiss them yourself.
- `export_document` finds translators by ClassId (their names changed in 2027).
- Tools act on the document `create_part` / `create_assembly` / `create_drawing` made, even
  if the user clicks another tab meanwhile. `inv.release_document()` drops that pin.
- An extrude with `operation="new"` makes a second body; later cuts and `inspect` see
  body 1 only.

Full notes: `docs/inventor-2027-notes.md`.

## Core mental model

| | Notes |
|---|---|
| Units | API takes **millimeters**; Inventor stores internally in **cm** (the wrapper handles ÷10 automatically) |
| Coordinates | XY is the default sketch plane. Z = "up"/axial in most templates |
| Workflow | `connect → create_part → create_sketch → draw_* → extrude/revolve → hole → fillet/chamfer → save` |
| Feature indices | 1-based, in creation order (`list_features()` to see them) |
| Edge indices | 1-based, in Inventor's internal order — **change after every feature that adds/removes edges** |

## The five rules that prevent 80% of failures

These come from real failures in past sessions. Internalize them.

### 1. Always extrude bodies in `"positive"` direction

```python
inv.extrude(13, "positive", "join")   # ✅ z = 0 .. 13
inv.extrude(13, "negative", "join")   # ❌ subtle: makes hole() not cut!
```

`hole()` is hardcoded to drill from XY plane in `kNegativeExtentDirection`. The hole's `AddDrilledByThroughAllExtent` is "through-all" — it traverses **any** body it intersects regardless of direction — **but only if the body's geometry was created normally**. With a negative-extruded body, the hole feature is created but doesn't remove material (verified by volume check). Always extrude positive; `hole()` will pass through whether body is above or below the XY plane.

### 2. `draw_polygon(radius=R, sides=6)` — `R` is the **circumradius**, not apothem

For a hex with width across flats `s`:
```python
circumradius = s / math.sqrt(3)    # M16 nut s=24 → R = 13.856
apothem      = s / 2                # = 12mm — the radial distance to flat midpoint
```

### 3. Revolve: prefer `axis="Y"` (or X/Z) over construction lines

Old way (still works): draw construction line FIRST, then profile, then `revolve(axis_line_index=1)`.

New way (preferred — added in this codebase):
```python
inv.create_sketch("XY")
inv.draw_closed_profile([[0,0],[30,0],[30,8],[15,60],[0,60]])   # profile only
inv.revolve(axis="Y", operation="join")
```

For a sketch on **XZ plane**, 2D-Y maps to **part +Z** (verified empirically). So a profile at `[[11, 13], [16, 13], [16, 10]]` revolved around `axis="Z"` chamfers material near the top of a body that goes from z=0 to z=13.

### 4. All chamfer edges go in ONE call — indices renumber after each chamfer feature

```python
# ❌ Wrong — second call uses stale indices
inv.chamfer(2, edge_indices=[5,8])
inv.chamfer(2, edge_indices=[11,14])   # these are no longer the edges you wanted!

# ✅ Right — single call with all edges
inv.chamfer(2, edge_indices=[5,8,11,14,17,20])
```

### 5. UTF-8 console + unique save filenames

```bash
python -X utf8 my_script.py    # required if script prints Cyrillic / × symbols
```

Saving over an open .ipt fails with `E_INVALIDARG (-2147024809)`. Either delete first, or use a fresh filename (`HexNut_M16_v2.ipt`).

## Common workflows — cookbook

### Stepped shaft (revolve join)

```python
inv.create_sketch("XY")
inv.draw_closed_profile([[0,0],[30,0],[30,8],[15,8],[15,60],[0,60]])   # 6-pt profile
inv.revolve(axis="Y", operation="join")
```

### Circumferential groove (revolve cut)

```python
inv.create_sketch("XY")
inv.draw_closed_profile([[8,26],[15,26],[15,34],[8,34]])    # groove cross-section
inv.revolve(axis="Y", operation="cut")
```

### Tapped hole (M-thread, standard coarse pitch auto-picked)

```python
inv.hole(x=0, y=0, diameter=16, depth=0, tapped=True)
# → M16 × 2.0 (coarse), 6H, through-all
```

For non-standard pitch: pass `pitch=1.5` explicitly (fine M16).

### Bolt-hole circle (one hole + circular pattern, NOT 8 separate holes)

```python
inv.hole(x=120, y=0, diameter=16, depth=0, tapped=True)   # one M16 at PCD 240
features = inv.list_features()
hole_idx = features[-1]["index"]
inv.circular_pattern(feature_index=hole_idx, count=8, angle=360, axis="Z")
```

Any repeated hole set that is symmetric about an axis (two holes at x = ±30 too: count 2,
angle 360) should be one hole plus a pattern: a drawing hole note then prints "2x Ø11 THRU"
by itself, and separate holes never get the count.

### DIN 934 chamfer — done by revolve cut, NOT `chamfer()`

The `Chamfer` feature in Inventor knocks the same width off each of the 12 edges of a hex prism — creating 12 small flat facets. The real DIN 934 chamfer is a **conical** surface. Use `revolve(axis="Z", operation="cut")` with a triangle profile on the XZ plane. See sibling skill `inventor-din-parts` for full templates.

### Sheet Metal parts (PC cases, enclosures, brackets)

When the user mentions "листовий метал", "sheet metal", thickness like "0.8 мм", or wants a bent enclosure:

```python
inv.create_part(template="sheet_metal", name="My_Enclosure")
inv.set_sheet_metal_thickness(0.8)         # mm

# Base panel (the bottom / first flat piece)
inv.create_sketch("XY")
inv.draw_rectangle(0, 0, width=200, height=450)
inv.sheet_metal_face()                      # creates Sheet Metal Face1

# Add a wall — REAL Sheet Metal Flange (with bend radius, supports Flat Pattern)
front_edge = inv.find_edge(y=-225, z=0.8)   # find edge of base panel
inv.flange(edge_indices=[front_edge], distance=450, angle=90)
# After each flange, edge indices renumber. Re-find before next flange:
back_edge = inv.find_edge(y=+225, z=0.8)
inv.flange(edge_indices=[back_edge], distance=450, angle=90)
# ...etc for left/right

# Cutouts on a panel — ONE sketch on the panel face, ALL shapes, ONE Sheet Metal Cut
back_face = inv.find_face(y=225, min_area=10000)   # outer back face
inv.create_sketch(face_index=back_face)
inv.draw_circle(x=100, y=130, diameter=120)        # fan hole
inv.draw_rectangle(x=100, y=32.5, width=158, height=45)   # IO panel
inv.draw_rectangle(x=100, y=377, width=150, height=86)    # PSU
inv.sheet_metal_cut()       # cut depth = Thickness automatically (parametric!)
```

**Three rules for sheet metal that prevent rework:**

1. **Cuts must be Sheet Metal Cut, not Extrude cut.** Sheet Metal Cut binds depth to the
   `Thickness` parameter. Changing thickness later updates all cuts automatically.
   Extrude cut uses a fixed depth → cuts become wrong when thickness changes.

2. **Sketch for a Cut goes ON the panel face, not on a work plane.** Sketching on the
   face is what lets Inventor default the cut depth to `Thickness`. Use
   `inv.find_face(y=…, z=…)` to locate the right face, then `create_sketch(face_index=N)`.

3. **All cutouts on the same panel go in ONE sketch.** One sketch with multiple closed
   loops (circles, rectangles) becomes ONE `Cut1` feature with all holes. This is the
   Inventor convention — multiple separate Cut features add visual clutter and slower
   rebuild.

**Coordinates on a panel face** are NOT centered. The sketch origin is at one corner
of the face, and axes may flip relative to world. To convert:
```python
pt3d = sketch.SketchToModelSpace(tg.CreatePoint2d(sx_cm, sy_cm))
# Returns world position in cm
```
For a typical back face at Y=+225 (outer normal +Y), the mapping is often
`sketch_X = world_X + half_width`, `sketch_Y = top_world_Z - world_Z` (flipped).
Confirm via `SketchToModelSpace` for the actual face.

**Flange API quirks** (found on 2026; the wrapper's workarounds pass the 2027 audit):
- `CreateFlangeDefinition(Edges, AngleRadians, DistanceIgnored)` — second arg must be
  RADIANS (`math.radians(90)` → 1.5708), not degrees. Pass `90` and Inventor stores 5156°.
- The Distance argument is silently IGNORED — the flange always defaults to 25mm height.
- Real distance set via `feat.Definition.HeightExtent.Distance.Expression = "450 mm"`.
- `inv.flange()` already handles all of the above — just pass `distance` in mm.
- HeightDatumType=75521 ("From Outer Intersection") is the default. With this datum,
  Distance equals the visible perpendicular height (thickness not subtracted).

**Flat Pattern test** — the proof that a sheet metal model is truly parametric:
Right-click the body → "Create Flat Pattern". If the model unfolds into a 2D layout
with all cuts visible, the geometry is real sheet metal. If it fails, you have
solid extrusions in a sheet metal document (visually identical but not usable).

### Parametric sketch discipline (required for maintainable models)

Every sketch must end up **Fully Constrained**. The pattern:

```python
sketch = comp.Sketches.Add(comp.WorkPlanes.Item(3))
# 1. Project the origin point — dimensions will reference it
proj = sketch.AddByProjectingEntity(comp.WorkPoints.Item(1))
try: proj_o = proj.Item(1)
except: proj_o = proj
# 2. Project axes as construction lines (for symmetry / coincident constraints)
r = sketch.AddByProjectingEntity(comp.WorkAxes.Item(1))
proj_x = r.Item(1); proj_x.Construction = True

# 3. Base sketch of a symmetric part → SYMMETRY about projected axes
gc = sketch.GeometricConstraints
gc.AddSymmetry(left_line, right_line, proj_y_axis)   # part stays centered on origin

# 4. Circle center on an axis → coincident, NOT a zero dimension
gc.AddCoincident(circle.CenterSketchPoint, proj_x)

# 5. Dimensions from the projected origin (works with projected points!)
dc = sketch.DimensionConstraints
dc.AddTwoPointDistance(proj_o, circle.CenterSketchPoint, 19201, text_pt)  # horizontal
```

Why: change one dimension → the whole part rebuilds correctly.

**Rename features and sketches immediately** (`feat.Name = 'Bore20'`,
`sketch.Name = 'sk_bore20'`): Inventor numbers Sketch/Extrusion globally and never
reuses deleted numbers, so auto-names like "Sketch4" are unreliable references.

### Hole placement: Linear (edge-referenced) — preferred for fastener holes

`inv.hole_linear()` places a hole at distances from two edges of a face — fully
parametric (survives part resizing). Discovered signature (gencache):

```python
placement = hf.CreateLinearPlacementDefinition(
    face, edge1, dist1_cm, edge2, dist2_cm,
    bias_point)   # ← Point3d REQUIRED via dynamic dispatch; approximate hole location
# bias disambiguates among 4 possible positions (distance can go either side of edge)
```

**Drill direction is unpredictable** — kPositive vs kNegative depends on face
orientation. Pattern: create → `doc.Update()` → check `MassProperties.Volume`
dropped → if not, delete feature and retry with the other direction.
`inv.hole_linear()` does this automatically.

### Counterbore + split-clamp screw pattern (ISO 4762)

```python
# AddCBoreByDistanceExtent(placement, HoleDiaOrTapInfo, Depth, Direction, CBoreDia, CBoreDepth)
hf.AddCBoreByDistanceExtent(pl, 0.55, 1.125, 20993, 1.0, 0.55)  # all cm
```

M5 socket head cap screw (ISO 4762, DIN, Normal fit): clearance Ø5.5, cbore Ø10×5.5.

Split clamp (розрізний хомут) screw = TWO hole features:
- Near ear: clearance + counterbore, depth = ear thickness (to the slot)
- Far ear: tapped M5 (TapInfo works with `AddDrilledByDistanceExtent` too), depth = ear

Via the wrapper: `inv.hole_linear(..., diameter=5.5, depth=11.25, cbore_diameter=10, cbore_depth=5.5)`
then `inv.hole_linear(...opposite face..., diameter=5, depth=11.25, tapped=True)`.

### Offset work planes — features at a height

```python
inv.create_sketch(plane="XY", offset=16)   # hidden work plane 16mm above XY
# Raw API: comp.WorkPlanes.AddByPlaneAndOffset(basePlane, offset_cm); wp.Visible=False
# Offset direction = plane normal (XY→+Z, XZ→+Y, YZ→+X)
# Always verify with sketch.SketchToModelSpace(tg.CreatePoint2d(0,0))
```
Offset planes from XY have DIRECT axis mapping (x→X, y→Y), unlike base XZ.

### Fillets shift adjacent edges (topology trap)

After a fillet, adjacent edges get extended/shortened — their midpoints move.
(Verified: R20 fillet extended neighbouring slope edges from Y 17..33 to Y −3..33.)
Re-find edges with `list_edges`/`find_edge` AFTER every fillet; never reuse
pre-fillet coordinates.

### Feature order vs cuts

Material added AFTER a cut (bore/hole) will FILL the cut where they overlap.
When adding a rib/boss under an already-bored hub, stop the new feature below
the bore bottom (e.g., rib top Z=65 when bore bottom is Z=70), or reorder features.

### Reading technical drawings — practical conventions

1. Dimensions that look horizontal/vertical ARE exactly that unless noted.
2. Symmetric parts: a dimension may be shown on one side only — mirror it.
3. Unspecified fillet radii: estimate by comparing against known drawing elements,
   round to a multiple of 5.
4. "Extend the face line virtually" — a slanted face's extension often passes
   through a part corner (gives the tangent anchor point).
5. Typical bearing-bracket construction: triangular gusset plate at the back
   + stiffening rib at the front under the boss, both the same thickness.
6. When a dimension is unclear (e.g. "14" between centers) — ASK the user,
   never guess. Humans read drawings better than models do.

### Sketch axis mapping on standard work planes

| Plane | sketch X | sketch Y |
|---|---|---|
| XY (Item 3) | world +X | world +Y |
| XZ (Item 2) | **world −X (mirrored!)** | world +Z |
| YZ (Item 1) | world +Y | world +Z |

Verify with `sketch.SketchToModelSpace(tg.CreatePoint2d(1,0))` when unsure.

### SaveAs vs Save

`doc.SaveAs(path)` fails with E_INVALIDARG when the file is already open under that
name. Re-saves go through `doc.Save()` (wrapper: `inv.save_document()` with no path).

### Reading the type library for API discovery

When dynamic dispatch returns `Type mismatch`, or you need an enum value or a method's
argument names, read the type library directly. It needs no Inventor connection and,
unlike `gencache.EnsureDispatch`, leaves no `gen_py` cache that breaks `GetActiveObject`.

```python
import pythoncom
tlb = pythoncom.LoadTypeLib(r"<Inventor install>\Bin\RxInventor.tlb")
for i in range(tlb.GetTypeInfoCount()):
    if tlb.GetDocumentation(i)[0] != "PartsLists":
        continue
    ti = tlb.GetTypeInfo(i)
    for f in range(ti.GetTypeAttr().cFuncs):
        fd = ti.GetFuncDesc(f)
        print(ti.GetNames(fd.memid), ti.GetDocumentation(fd.memid)[1])
```

Enums are `TKIND_ENUM` type infos; `ti.GetVarDesc(v).value` gives each value. If a
`gen_py` cache ever appears, delete `%LOCALAPPDATA%\Temp\gen_py`.

## Diagnostic patterns — verify the build did what you intended

Don't trust "feature created successfully" — sometimes the feature is created but doesn't remove material (the through-hole problem above). Verify geometry:

```python
import win32com.client
app = win32com.client.GetActiveObject("Inventor.Application")
body = app.ActiveDocument.ComponentDefinition.SurfaceBodies.Item(1)
mp   = app.ActiveDocument.ComponentDefinition.MassProperties

print(f"Volume = {mp.Volume*1000:.0f} mm³")     # cm³ → mm³
print(f"Faces = {body.Faces.Count}")
print(f"Edges = {body.Edges.Count}")
rb = body.RangeBox
print(f"Z: {rb.MinPoint.Z*10:.2f} .. {rb.MaxPoint.Z*10:.2f} mm")
```

**Face SurfaceType decoder** (2027 type library):
| Code | Meaning |
|---|---|
| 5890 | Plane |
| 5891 | Cylinder |
| 5892 | Elliptical cylinder |
| 5893 | Cone |
| 5894 | Elliptical cone |
| 5895 | Torus |
| 5896 | Sphere |
| 5897 | B-spline |

Finding the chamfer in `Face types: {'Plane': 8, 'Cylinder': 1, 'Cone': 2}` confirms revolve-cut produced real conical surfaces.

**Finding edges by Z coordinate** (e.g. shaft tip):
```python
for i in range(1, body.Edges.Count + 1):
    e = body.Edges.Item(i)
    z_mid = (e.StartVertex.Point.Z + e.StopVertex.Point.Z) / 2.0 * 10
    if abs(z_mid - target_z) < 1:
        print(f"Edge {i} at Z={z_mid:.1f}mm")
```

## Inventor 2026/2027 API gotchas (vs older docs)

These differ from the official documentation and older Inventor versions; all still hold in 2027.

| | Old / docs | Inventor 2026/2027 actually wants |
|---|---|---|
| DocumentType | varies | `12290` for parts |
| Direction enum | varies | `20993/20994/20995` (pos/neg/sym) |
| Operation enum | varies | `20481/20482/20483/20484/20485` (join/cut/intersect/surface/new) |
| Dimension orientation | `40706/40707/40708` (docs) | `19201/19202/19203` (horiz/vert/aligned) |
| Chamfer API | `CreateChamferDefinition` + `Add` | `ChamferFeatures.AddUsingDistance(EdgeCollection, d)` — note `EdgeCollection`, not `ObjectCollection` |
| Revolve API | `CreateRevolveDefinition` | `RevolveFeatures.AddFull(profile, axis, op)` |
| Hole API | `CreateSimpleHoleDef` | `HoleFeatures.CreateSketchPlacementDefinition(ObjectCollection of SketchPoints)` |
| AddTwoPointDistance | any SketchPoint | **only** line endpoints — `line.StartSketchPoint` / `line.EndSketchPoint`. Standalone `SketchPoints.Add()` gives E_UNEXPECTED |

## Sketch dimension cookbook

Sketches without dimensions are "underdefined" (yellow status in Inventor). To get fully-defined sketches:

```python
# AddDiameter — built into draw_circle() already
inv.draw_circle(0, 0, 50)   # adds diameter dim automatically

# Position dimension on a SketchPoint — needs a separate sketch with a construction line
# (because HoleFeature consumes its placement sketch — adding lines there breaks it)
```

`hole()` already calls `_add_hole_position_dims` to add X/Y position dims via a separate dimension sketch — no extra work needed.

## TapInfo for threaded holes

Standard coarse-pitch table (auto-applied when `pitch` is omitted):

| Thread | Pitch | Thread | Pitch |
|---|---|---|---|
| M6  | 1.0  | M16 | 2.0  |
| M8  | 1.25 | M20 | 2.5  |
| M10 | 1.5  | M24 | 3.0  |
| M12 | 1.75 | M30 | 3.5  |
| M14 | 2.0  | M36 | 4.0  |

Designation format: **integer pitches drop the decimal** — `M16x2` not `M16x2.0`. The `hole()` wrapper handles this. ThreadType string must be **exactly** `"ISO Metric profile"` (from `C:\Users\Public\Documents\Autodesk\Inventor 2027\Design Data\XLS\en-US\thread.xlsx`).

## File locations

| | Path |
|---|---|
| MCP server | `src/server.py` |
| API wrapper | `src/inventor_api.py` |

| Templates | `app.FileLocations.TemplatesPath` (auto-resolved) |
| Thread DB | `C:\Users\Public\Documents\Autodesk\Inventor 2027\Design Data\XLS\en-US\thread.xlsx` |
| 2027 field notes | `docs/inventor-2027-notes.md` |


## When user reports "feature didn't work"

1. **First** verify with the diagnostic block above — is the volume / face count what you'd expect?
2. **If hole didn't cut**: check the extrude direction. Was it `"negative"`? Rebuild with `"positive"`.
3. **If chamfer failed**: was `CreateChamferDefinition` used somewhere? Replace with `AddUsingDistance(EdgeCollection, d)`.
4. **If revolve cut had no effect**: profile was probably in air (wrong Z side). Flip the sign of Y coords in the profile.
5. **If second chamfer destroyed first**: you passed two separate `chamfer()` calls. Combine into one with all edge indices.

## After editing the server code

- Changes to `inventor_api.py`: call `reload_api()`; the tools use the new code at once.
- Changes to `server.py` (new tools, new parameters, docstrings): the MCP client must
  restart the server before the tool list changes. Until then, call new wrapper methods
  through `execute_python` (`inv.method(...)`), or run a script with
  `python -X utf8 script.py` that imports `src.server`.

## See also

- Sibling skill `inventor-din-parts` — ready-to-use parametric templates for DIN 934 nuts, DIN 933 bolts, DIN 125 washers, DIN 2573 flanges. In an assembly, Content Center parts (`place_content_center`) are usually the better choice.
- Sibling skills `inventor-drawing` (drawings, PDF) and `inventor-assembly` (assemblies, BOM, exploded copies).
- `docs/inventor-api-notes.md` (2026) and `docs/inventor-2027-notes.md` — the "discovered the hard way" context.
