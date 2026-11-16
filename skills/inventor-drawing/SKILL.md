---
name: inventor-drawing
description: Make 2D engineering drawings (.idw) of Inventor parts and assemblies through the inventor-mcp server - views, sections, details, centerlines, dimensions, hole and chamfer notes, tolerances, GD&T, datums, surface finish, title block, parts list, balloons, exploded views, PDF export. Use whenever the user asks for a drawing, gambar teknik, gamtek, drawing kerja, technical drawing, section view, potongan, parts list, balon, BOM on a drawing, or a PDF of a part or assembly, and whenever the mcp__inventor__ drawing tools (create_drawing, add_base_view, add_dimension, list_views, ...) are involved.
---

# Inventor drawings through MCP

The drawing tools build a whole sheet from a saved model: views, annotations, title block,
then PDF. The judgement calls (which views, which dimensions, where things go) are yours;
the tools place things where you say and tell you when something collides.

## Before you start

- Inventor must be running; call `connect`. If a call hangs, Inventor is probably showing a
  dialog. Ask the user to click it; you cannot. Do not start a second Inventor.
- The model must be saved (`save_document("C:/.../part.ipt")`). Views reference files.
- Work only in the user's test or project folders. Do not delete or overwrite other files.

## Two coordinate frames (the most common source of mistakes)

| Used by | Frame |
|---|---|
| `add_base_view`, `add_projected_view`, `add_section_view` (its `x, y`), `add_detail_view` (its `x, y`), `add_parts_list` | **sheet mm** from the sheet's bottom-left corner |
| everything that points at geometry inside a view: section line ends, detail centre, `add_dimension`, notes, GD&T, datums, surface finish, `move_dimension` | **model mm from the view centre**, x right and y up on the sheet |

Inside a view, a point (x, y) means "x model-mm right of the view centre", whatever the
scale. For a flange of Ø120 in a 1:2 view, its rim is at y = ±60, not ±30.

A3 landscape: sheet 420 x 297, border 10..410 x 10..287. The Arjuna title block covers
about x 128..410, y 10..40; a parts list goes on top of it at the right. Read the exact
boxes from `list_views` (`border_mm`, `title_block_mm`).

## Profiles

`create_drawing(profile="default")` sets the template and the drawing standard:

- `default`: Arjuna A3 template, **third angle**, mm, one decimal with a comma and no
  trailing zeros, labels like `A-A ( 1 : 1 )`, letter-only section marks, chain-line
  centerlines, general tolerances in the title block, DOCUMENT TYPE and APPROVED BY
  filled on the first view, Arjuna parts list layout. Needs the migrated template in
  `references/templates/2027/` (not in git).
- `iso`: Inventor's own ISO.idw with the same settings, for machines without team files.

Profiles are JSON in `drawing_profiles/`, documented in `docs/drawing-profiles.md`.
Third angle: a projected view placed **above** the parent is the top view, to the
**right** the right-side view.

## Choosing views

1. **Front view = the most informative view.** `orientation="front"` looks along the
   model's -Z axis. A turned part or flange modelled about Z shows its circular face.
2. **Fewest views that define the part.** Usually front + one projected or section view.
   A plain (not sectioned) orthographic view of a part with bores or holes gets
   `style="hidden"`, so the bore shows as dashed lines even when a section also shows it
   (a hollow shaft's side view, a flange's edge view). Section views stay without hidden
   lines (ISO 128); the iso view stays `visible`.
3. **Section** when there are internal features (bores, counterbores, through holes).
   Draw the section line across the whole part (extend past the outline), through the
   features you want cut. A section through two opposite bolt holes shows them cut.
4. **Detail view** for small features (grooves, small chamfers) at 2:1 or more.
5. **Isometric** in a free corner at a smaller scale, as Arjuna drawings have one.
6. Scale: standard ratios only (1:1, 1:2, 1:5, 2:1). Small parts (under ~100 mm) on A3
   read better at 2:1. Leave 25-35 mm around each view for dimensions. Fix a view later
   with `move_view(view, x, y, scale)` (projected views follow; a spot outside the border
   or on something else is refused) or `delete_view(view)` (its child views go too).
   Move views before dimensioning; annotations do not follow a rescale well. `add_base_view` refuses a view that leaves the border or overlaps the
   title block, another view or the parts list, and says where it would sit; move it or
   change the scale.
7. View names come back in tool results (`VIEW1`, `A`, ...). A rejected view still uses up
   its name, so read the name from the result.

## Annotating

Run `add_centerlines(view)` on every view that shows holes, cylinders or revolved
features. It draws axes over the full feature length and center marks that run past
each circle, in chain line.

### Dimension strategy

1. `retrieve_dimensions(view)` on the view where the model's sketch dimensions read best
   (often a side or top view). It arranges them and pushes overlapping texts apart.
2. `list_dimensions()` then `delete_dimension("i,j")` for duplicates and dimensions that
   belong elsewhere. Every size appears once.
3. Add what is missing with `add_dimension`:
   - turned parts: diameters as `vertical` (or `horizontal`) dimensions with `prefix="Ø"`
     in the section or side view, stacked outside the outline, smallest nearest;
   - `diameter` / `radius` for circles seen as circles;
   - `angle` for hole spacing (vertex on the bore circle).
4. Text positions go **outside the part**. Never dimension to a hidden line. The text
   lands a few mm from where you ask (the dimension line snaps); check the result.
5. Section and detail labels ("A-A ( 1 : 1 )") sit **above** their view. Keep dimensions
   on the other sides of a section, or leave a clear band above the label; the checker
   catches text on text, not a label sitting between extension lines.
6. Decimals follow the model: a length of 121,42 prints with two decimals even though the
   profile shows one; more than two is rounded (more would tighten the general
   tolerance). Check that the design value and `ModelValue` agree.
7. Distance between hole centres: use `horizontal` / `vertical` with points **on the two
   circles** (e.g. their tops, (-30, 5.5) and (30, 5.5)); it measures centre to centre.
   Points exactly at the centres hit no curve and fail with a COM error.
8. Holes on a bolt circle: **one note, no separate PCD dimension.**
   `add_dimension(view, "diameter", <point on one hole, outer side>, tx, ty, prefix="4x ",
   suffix=" THRU
ON PCD 76, EQ SP")` reads "4x Ø8 THRU / ON PCD 76, EQ SP"; it works for
   holes cut in one sketch as well as for patterned ones. `add_hole_note(...,
   second_line="ON PCD 76, EQ SP")` does the same for `hole()` features (count by itself
   only for one patterned feature, else `count=4`); a frame under a hole note is placed by
   hand with `leader=False`, so prefer the dimension form. The pitch circle centerline from
   `add_centerlines` stays on the view. A wrong note: `list_notes()`, `delete_note("i")`.
   A diameter leader lands where the line from its text to the centre meets the circle:
   point it at a hole, text outside the part.
   **Orientation:** holes that do not sit on the centerlines (e.g. at 45°) get the angle
   from an axis: `add_dimension(view, "angle", hx, hy, vertex_x=0, vertex_y=0, text_x,
   text_y)` (no x2/y2) measures from the horizontal centerline (right side, 0°) to that hole; pick a hole in
   the upper right quadrant so the angle reads small (45°, not 135°). Holes on the
   centerlines need no angle: EQ SP and the centerlines define them.
9. External threads: `add_hole_note` with the point on the thread line in a side view
   gives the thread note ("M42x1.5 - 6g").
10. Chamfers: `add_chamfer_note` on a view where the chamfer is a slanted line,
   `prefix="2x "` for equal chamfers.

11. Sheet metal parts: the folded part in front and side views (bend radius, flange
   heights, angles) plus the blank: `add_base_view(model, x, y, 1, flat_pattern=True)`,
   then `add_bend_notes(view)` puts "UP 90° R2" / "DOWN 90° R2" on every bend line, and
   overall length and width of the blank go on that view. Label it with a note such as
   "FLAT PATTERN" if the profile has no view label. Holes in the blank are dimensioned
   there, from one edge.

### Tolerances, datums and GD&T: required on every machined part

A part drawing without datums is not finished. The general tolerances in the title block
cover plain sizes only; every functional feature needs its own control. Before export,
each machined part drawing has **all** of these:

1. **Datums.** A: the primary functional face (the face it mounts or seats on) or the
   main bore/axis for a turned part. B: the locating axis or bore (or the second face).
   C only when a third direction matters. A face datum: `add_datum` with the triangle on
   the face line (or its extension line), box beside it outside the part. An axis datum
   (bore, seat): `add_datum(view, 0, 0, "B", 0, 0, dimension=i)` puts the triangle on the
   shoulder of that size dimension (Ø51 H8), never loose inside the bore; in a side or
   section view `attach=False` on the dimension line of the Ø dimension does the same.
2. **Fits** on every mating diameter: `set_tolerance(index, "fit", fit="H7")` for a bore
   on a shaft or bearing, "h6"/"k6"/"m6" for the shaft side, "H8" for a sliding or weld
   locating fit.
3. **GD&T on what makes the part work:**
   - mating faces: flatness, or perpendicularity to the axis datum;
   - bolt or stud hole patterns: position Ø, `diameter_zone=True`, to A and B, directly
     under the hole note: `add_gdt(view, 0, 0, 0, 0, "position", 0.2, "A,B",
     diameter_zone=True, dimension=i)` with i the note's index;
   - clearance holes for bolts: position at MMC, `modifier="mmc"` (Ø0,2Ⓜ), so the
     tolerance grows as the hole comes out larger and a gauge pin can check it; press
     fits and locating pins stay without a modifier. A datum that is a size feature (a
     bore) may be referenced at MMC too: `datums="A,B(M)"`;
   - a frame for a size feature (bore, seat) goes under its dimension the same way; a
     frame for a surface gets a leader to that surface or its extension line;
   - turned seats and faces that run: circular runout (or total runout) to the axis datum;
   - coaxial steps: runout rather than concentricity.
4. **Surface finish:** "Ra 1,6" on fits and bearing seats, "Ra 3,2" on machined mating
   faces, the general finish (e.g. "Ra 6,3") in the title block field SURFACE FINISH.

Every frame refers only to datums that exist on the sheet. Values you choose are
proposals unless the user gave them; say so in the report. Exceptions: flame or laser cut
plates that are not machined still get datum A/B and hole position, but no fit or Ra;
standard (Content Center) parts get no drawing. An assembly or weldment drawing carries the
controls that only exist after joining (e.g. runout of a welded flange face to the shaft
axis) with datums on the assembly view.

### Title block

`set_title_block('{"TITLE": "...", "PART NUMBER": "...", "ENGINEER": "...",
"REVISION NUMBER": "1"}')`. Unknown names make it list the fields the block has. Some
fields live in the model, so `save_document` on the drawing saves the model too: in the
Arjuna template TITLE, ENGINEER, CHECKED BY and REVISION NUMBER are model iProperties,
while PART NUMBER, SURFACE FINISH and MATERIAL are prompts on the sheet. The tool result's
`model_changed` lists what went to the model.

**MATERIAL is always stated.** The first view fills it: the part's material; for an
assembly the one material all its parts share, or the statement "VARIOUS, SEE PART
DRAWINGS" when they differ; "NONE" when nothing is assigned (Generic). Pass a library
material name ("Aluminum 6061") to give a part that material and print it, any other text
("NONE", "AS PER PARTS LIST") to print just that, or "auto" to work it out again after
changing materials. The statements are profile keys `material_mixed` / `material_none`.

The parts list prints each part's Part Number and Description iProperties (Part Number is
the file name until set). Fill them before drawing:
`set_properties("C:/.../Flens.ipt", '{"Part Number": "KF-001", "Description": "Coupling flange"}')`.

## Verify, every time

0. Checklist for a part drawing, all yes before export: views define every feature;
   each size appears once, outside the part; datums A (and B) shown; every mating
   diameter has a fit; hole patterns have position to the datums; mating or running faces
   have flatness, perpendicularity or runout; Ra on fits and in the SURFACE FINISH field;
   title block complete (MATERIAL stated, PART NUMBER, TITLE).
1. `list_views()` must report `"problems": []` (views outside the border, overlaps,
   texts on texts, texts outside the border).
2. `export_sheet_png(path)` and **open the PNG with Read**. Look for dimensions inside
   the part, leaders pointing at the wrong thing, crowded corners, missing centerlines.
   The checker cannot see these.
3. Fix with `move_dimension`, `delete_dimension` and new placements, then check again.
4. `save_document("C:/.../name.idw")`, then `export_pdf(path)`.
5. For a close look at the PDF: `powershell -File tools\pdf2png.ps1 -Pdf <pdf> -OutDir <dir>`
   renders pages with Windows' own PDF engine.

## Assembly drawings: exploded view by default

An assembly drawing of a **bolted or loose assembly** is an **exploded isometric view
with a parts list and balloons**, as in the Arjuna assembly drawings. A **welded assembly
(weldment)** is drawn **assembled** instead, with welding symbols: see the
`inventor-weld` skill. Draw a non-welded assembly in its assembled state (with a section)
only when the user asks for it, e.g. to show fits.

Inventor 2027's presentation API cannot add tweaks or snapshot views, so the exploded
view comes from a free copy of the assembly:

```text
set_properties(each part, '{"Part Number": "...", "Description": "..."}')   # what the parts list prints
create_exploded_copy("C:/.../Kopling.iam", "C:/.../Kopling_exploded.iam")
auto_explode(spacing=20, axis="Z")       # from the source's constraint log
save_document("")
create_drawing()
add_base_view("C:/.../Kopling_exploded.iam", 160, 165, 0.5, "iso_top_right", spin=30)
add_explode_trails("VIEW1")              # chain lines back to the assembled position
add_parts_list("VIEW1")                  # before balloons, so item numbers match
add_balloons("VIEW1")
set_title_block(...); list_views(); export_sheet_png(...); save_document(...); export_pdf(...)
```

- `auto_explode` needs the source assembly built with `add_constraint` and saved with
  `save_document` (that writes `<name>.constraints.json`). Each part moves off the face it
  was inserted or mated onto, clear of it plus `spacing`, in assembly order: washer, then
  the bolt beyond it; flange, its washer, the nut further still; a shaft out of its hub.
  The grounded part stays. It handles stacks along one axis; move anything else (radial
  parts, a second axis) with `explode_components(names, dx, dy, dz)` on the same copy.
- Pick the axis the parts were assembled along, and a scale that fits the longer exploded
  length (often half the assembled scale).
- `spin=30` (about that axis) stops bolts at 0/90/180/270 degrees from hiding each other
  in pairs, which happens in every standard iso orientation.
- `add_parts_list` with no x, y stacks on the title block against the right border
  (ITEM, QTY, PART NUMBER, DESCRIPTION, heading at the bottom).
- `add_balloons(view)`: one balloon per parts-list item visible in the view, rows above
  and below it, leaders not crossing, each on an edge no other component shares. Check
  the PNG.
- The copy does not follow later changes to the original; make it again.

### Variant and reference parts

An assembly may hold parts that are not delivered (an alternative shaft, a reference
body). Hide them in each view with `set_component_visibility(view, "Name:1", False)` and
leave them out of the parts list with `add_parts_list(view, hide="part number or file")`;
the other items are renumbered. Nothing in the assembly changes.

### Assembled section (when asked)

Base view of the `.iam` (`design_view=` / `positional=` pick a representation), then a
section through the main axis. Content Center fasteners stay unhatched by themselves;
pass shafts cut along their axis in `no_hatch="Poros:1, Poros:2"`. Parts list and balloons
as above.

## Pitfalls

- A template saved by an older Inventor shows a "needs to be migrated" dialog and fails;
  open and save it once in 2027. A template that is open in Inventor cannot be used.
- Closing a part that an open drawing or assembly still uses raises an "improper argument"
  dialog; after that Inventor ignores further closes and may crash. In scripts, close a
  folder's documents with `inv.close_documents_in(folder)` (drawings, then assemblies,
  then parts). Never close all documents; the user may have work open.
- Decimal marks: profile `default` prints commas. Text you pass (roughness, notes) should
  use the same mark ("Ra 3,2").
- `add_dimension` and notes snap to the nearest visible curve; if a result says
  "within 4.8 mm", the point was off and another curve may have been picked.
- Retrieved dimensions can land outside the border; `list_views` reports it.

## Example: part drawing (flange, A3, approved by the team)

```text
create_drawing()
add_base_view(MODEL, 115, 150, 1)                     -> VIEW1 (circular face)
add_projected_view("VIEW1", 115, 255, style="hidden") -> VIEW2 (top, holes hidden)
add_section_view("VIEW1", 0, -70, 0, 70, 255, 150, "A")  # through two bolt holes
add_base_view(MODEL, 350, 220, 0.5, "iso_top_right")
add_centerlines on VIEW1, VIEW2, A
retrieve_dimensions("VIEW2"); keep the lengths, delete the rest
add_dimension("A", "vertical", -15, 15, -15, -15, text_x=-37, text_y=0, prefix="Ø")  # Ø30 bore, and Ø60, Ø120 further out
add_dimension("VIEW1", "diameter", 0, -50.5, -55, -74, prefix="4x ", suffix=" THRU
ON PCD 90, EQ SP")  -> index n
add_chamfer_note("A", 24.6, 59.6, 25, 45, 32, 72, prefix="2x ")
set_tolerance(<Ø30 index>, "fit", fit="H7")
add_gdt("VIEW1", 0, 0, 0, 0, "position", 0.2, "A,B", diameter_zone=True, dimension=n)  # under the note
add_datum("A", 25, 40, "A", 45, 40); add_datum("A", -31, -15, "B", -31, -23, attach=False)
add_surface_finish("A", -24.5, 15, -31, 16, "Ra 1,6")
set_title_block(...); list_views(); export_sheet_png(...); save_document(...); export_pdf(...)
```

Full scripts: `experiments/drawing_flange.py`, `experiments/drawing_coupling.py`,
`experiments/drawing_coupling_exploded.py`. API details behind the tools:
`docs/inventor-2027-notes.md`.
