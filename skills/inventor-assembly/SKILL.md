---
name: inventor-assembly
description: Build Inventor assemblies (.iam) through the inventor-mcp server - place parts and Content Center fasteners, constrain them (mate, flush, insert, angle, tangent), pattern bolt sets, check degrees of freedom, BOM and interference, and make exploded copies for drawings. Use whenever the user asks to assemble parts, rakit, perakitan, assembly, constraint, pasang baut/mur/ring, BOM, cek interferensi, DOF, Content Center, or exploded view, and whenever the mcp__inventor__ assembly tools (create_assembly, place_component, add_constraint, get_dof, ...) are involved.
---

# Inventor assemblies through MCP

## Workflow

```text
connect
(build and save every part first; Occurrences.Add needs files on disk)
create_assembly()
place_component(first_part, grounded=True)          # the base part, fixed in space
place_component(other_part, x, y, z, rx=180)         # rough start pose; constraints do the rest
add_constraint(...) x2-3 per component until its DOF is 0
pattern_component(...) for repeated sets
get_dof() -> "fully_constrained": true
get_bom("parts")                                     # quantities as expected?
analyze_interference()                               # only expected overlaps?
save_document("C:/.../name.iam")                     # also writes name.constraints.json
```

Wrap the build in `transaction("begin")` ... `transaction("commit")`, `"abort"` on error.

## Picking geometry: selectors

Constraints take a component name (`"Flens:1"`) and a **selector in that component's own
part coordinates, in mm**. Selectors do not change when the component moves, so you can
write them from the part's design.

| Selector | Picks |
|---|---|
| `plane:XY`, `plane:XZ`, `plane:YZ` | origin work plane |
| `axis:X`, `axis:Y`, `axis:Z` | origin work axis |
| `circle:x,y,z,r` | circular edge with that centre and radius (0.05 mm tolerance) |
| `face:x,y,z` | face nearest the point (must be within 1 mm) |
| `cylinder:x,y,z` | cylindrical or conical face nearest the point |
| `edge:x,y,z` | edge nearest the point |

The component name `"assembly"` means the assembly's own origin planes and axes.
Don't know the numbers? `list_occurrence_geometry("Flens:1")` lists every circle as a
ready selector, `kind="planes"` the planar faces.

## Constraints that work

- **insert** (circle to circle): coaxial and face to face in one go. The usual way to seat a
  bolt, washer, nut, pin or shaft. `opposed=True` (default) is "bolt into hole": the two
  axes point against each other. `offset` in mm; with opposed axes a **negative** offset
  pushes the second component **into** the first (a shaft 40 mm into a hub:
  `offset=-40` from the hub's outer edge circle).
- **flush / mate** between origin planes: stops the spin an insert leaves free. Pick a
  plane that **contains the rotation axis** on both components: for a hole on the X axis
  of a flange modelled about Z, `plane:XZ`; for a hole on the Y axis, `plane:YZ`.
- **mate** between two cylindrical faces makes their axes coincide; between planar faces
  it puts them face to face.
- **angle** between planes (degrees), **tangent** between cylinders.
- The **second** component moves to the first. Constrain new components to ones already
  fixed, outward from the grounded part.
- Each result reports health and the new pose. "health ..." other than healthy, or a pose
  that jumped somewhere odd, means the wrong edge or direction; `transaction("abort")`
  or delete and retry with the other circle / `opposed=False`.

Rotate a component at placement (`rx=180`) when it must face the other way (the second
flange of a coupling). The start pose only needs to be roughly right.

## Content Center fasteners

```text
list_content_center("Fasteners/Bolts/Hex Head", contains="DIN")       # families
list_content_center("Fasteners/Bolts/Hex Head", "DIN 933", "M10")      # sizes
place_content_center("Fasteners/Bolts/Hex Head", "DIN 933", "M10 x 60", x, y, z)
place_content_center("Fasteners/Nuts/Hex", "DIN 934", "M10", ...)
place_content_center("Fasteners/Washers/Plain", "DIN 125-1 A", "A 10.5", ...)
```

- Family names may carry a replacement notice ("DIN 933 - replaced by DIN EN 24017");
  a unique start such as "DIN 933" is enough. Size spacing and decimal mark do not matter.
- The part file is generated into the active project's Content Center folder (outside the
  test folder). Tell the user before the first use in a project.
- **Content Center parts run along their X axis**, seating face at x = 0:
  bolt head bearing edge `circle:0,0,0,7.7` (M10), nut face `circle:0,0,0,7.65`,
  washer bore `circle:0,0,0,5.25` and `circle:2,0,0,5.25` (other side, 2 mm thick).
  Their `plane:XY` contains the axis; flush it to the flange plane that contains the hole
  axis to stop the spin.
- Pose reports give the component's Z axis, but a Content Center part runs along its X,
  so they do not show which way a bolt points. Check the seating instead: the bolt's
  insert result origin should sit on the washer face, and `analyze_interference` should
  show the bolt/nut thread artifact where the nut is.
- Names contain spaces and commas ("DIN 125-1 A A 10,5:1"). Copy them from tool results;
  lists of names are split on the ":n" endings, so the commas inside are fine.

## Patterns

Constrain one complete set (washer, bolt, washer, nut) in one hole, then
`pattern_component("ring:1, bolt:1, ring:2, nut:1", "Flens:1", "axis:Z", 4)`.
`angle=360` spreads them evenly. Pattern instances are named `Name:2..` and count in the
BOM.

## Checking

- `get_dof()`: every component `[0, 0]`, `"fully_constrained": true`. Pattern instances
  report 0 as well.
- `get_bom("parts")` gives quantity per file; `"structured"` the top level.
- `analyze_interference()` lists overlapping pairs with volume and cause:
  - `thread artifact`: a tapped hole (modelled at the minor diameter) against a part with
    a thread feature, e.g. bolt in nut. Expected; report it as a modelling artifact.
  - `likely thread artifact`: tapped hole, but the other part has no thread feature
    (a self-modelled plain bolt). Usually the same thing; say so.
  - `real overlap`: a genuine clash. Fix the constraint or the part.
  Parts that only touch are not listed.

## Exploded copies (for drawings)

`create_exploded_copy(assembly, new_path)` makes a constraint-free copy;
`explode_components(names, dx, dy, dz)` moves components; `save_document("")`. Details and
the drawing side are in the `inventor-drawing` skill.

## Pitfalls

- `place_component` needs the file on disk; a part that was built but never saved fails
  with `E_INVALIDARG`. Save parts under their final names first.
- `save_document` refuses a path that is open in Inventor. Close it or use another name.
- Never close a part an open assembly or drawing still uses: Inventor shows an "improper
  argument" dialog, ignores later closes and can crash. In scripts use
  `inv.close_documents_in(folder)`; it closes drawings, then assemblies, then parts.
- Popups (Style Conflict, migration, errors) block every call until someone clicks them.
  If a call hangs, ask the user to look at Inventor.

## Example: flange coupling (20 components, DOF 0)

```text
create_assembly()
place_component(Flens.ipt, grounded=True)                         -> Flens:1
place_component(Flens.ipt, 15, 10, -40, rx=180)                   -> Flens:2
add_constraint("insert", "Flens:1", "circle:0,0,0,15", "Flens:2", "circle:0,0,0,15")
add_constraint("mate", "Flens:1", "plane:XZ", "Flens:2", "plane:XZ")
place_component(Poros.ipt, 20, 15, 80)                            -> Poros:1
add_constraint("insert", "Flens:1", "circle:0,0,50,15", "Poros:1", "circle:0,0,0,15", offset=-40)
add_constraint("flush", "Flens:1", "plane:XZ", "Poros:1", "plane:XZ")
(same for Poros:2 on Flens:2, placed with rx=180)
washer under the head: place_content_center(washer, 53, 6, 35)
add_constraint("insert", "Flens:1", "circle:45,0,20,5.5", washer, "circle:0,0,0,5.25")
add_constraint("flush", "Flens:1", "plane:XZ", washer, "plane:XY")
bolt: insert washer "circle:2,0,0,5.25" -> bolt "circle:0,0,0,7.7"; flush Flens:2 XZ / bolt XY
nut-side washer on Flens:2 "circle:45,0,20,5.5" (Flens:2 is flipped: hole (x, y) is (x, -y) in its part space)
nut: insert washer "circle:2,0,0,5.25" -> nut "circle:0,0,0,7.65"; flush Flens:2 XZ / nut XY
pattern_component("<washer>, <bolt>, <washer2>, <nut>", "Flens:1", "axis:Z", 4)
get_dof(); get_bom("parts"); analyze_interference(); save_document(...)
```

Full script: `experiments/assembly_coupling_tools.py`. API details:
`docs/inventor-2027-notes.md` (Assembly API, Content Center).
