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
   Add a top view with `style="hidden"` only when hidden lines explain holes or bores.
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
   - `pcd` for a bolt circle (needs `add_centerlines` first), `angle` for hole spacing
     (vertex on the bore circle).
4. Text positions go **outside the part**. Never dimension to a hidden line. The text
   lands a few mm from where you ask (the dimension line snaps); check the result.
5. Section and detail labels ("A-A ( 1 : 1 )") sit **above** their view. Keep dimensions
   on the other sides of a section, or leave a clear band above the label; the checker
   catches text on text, not a label sitting between extension lines.
6. Distance between hole centres: use `horizontal` / `vertical` with points **on the two
   circles** (e.g. their tops, (-30, 5.5) and (30, 5.5)); it measures centre to centre.
   Points exactly at the centres hit no curve and fail with a COM error.
7. Holes: `add_hole_note(view, x, y, tx, ty, second_line="EQ SP ON PCD Ø90")` gives
   "4x Ø11 THRU" with the bolt circle under it; prefer that to a separate PCD dimension.
   The count only appears by itself when the holes are **one patterned feature**: a
   `hole()` plus `circular_pattern` (two holes at x = ±30 are a pattern of 2 over 360°
   about Z). For holes made as separate features pass `count=2`. A wrong note:
   `list_notes()`, `delete_note("i")`, place it again.
8. Chamfers: `add_chamfer_note` on a view where the chamfer is a slanted line,
   `prefix="2x "` for equal chamfers.

### Tolerances and GD&T

- `set_tolerance(index, "fit", fit="H7")` for a bore on a shaft, `"symmetric"` /
  `"deviation"` / `"basic"` as needed. General tolerances are already in the title block.
- `add_datum` on the functional faces/axes; `attach=False` puts the triangle exactly on a
  point such as the extension line of a Ø dimension (datum = that axis).
- `add_gdt`: flatness on a mating face, perpendicularity to a datum, position with
  `diameter_zone=True` for bolt holes. `leader=False` puts a bare frame right under a
  hole note.
- `add_surface_finish` with "Ra 1,6" on fits, "Ra 3,2" on machined faces; the general
  finish goes in the title block field SURFACE FINISH.
- Tolerance and roughness values you pick are proposals; say so to the user.

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

An assembly drawing is an **exploded isometric view with a parts list and balloons**,
as in the Arjuna assembly drawings. Draw the assembled state (with a section) only when
the user asks for it, e.g. to show fits.

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
add_hole_note("VIEW1", 0, -50.5, -55, -74, second_line="EQ SP ON PCD Ø90")
add_chamfer_note("A", 24.6, 59.6, 25, 45, 32, 72, prefix="2x ")
set_tolerance(<Ø30 index>, "fit", fit="H7")
add_gdt("VIEW1", 0, 0, -50, -80, "position", 0.2, "A,B", diameter_zone=True, leader=False)
add_datum("A", 25, 40, "A", 45, 40); add_datum("A", -31, -15, "B", -31, -23, attach=False)
add_surface_finish("A", -24.5, 15, -31, 16, "Ra 1,6")
set_title_block(...); list_views(); export_sheet_png(...); save_document(...); export_pdf(...)
```

Full scripts: `experiments/drawing_flange.py`, `experiments/drawing_coupling.py`,
`experiments/drawing_coupling_exploded.py`. API details behind the tools:
`docs/inventor-2027-notes.md`.
