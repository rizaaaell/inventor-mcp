---
name: inventor-weld
description: Build welded assemblies (weldments) in Inventor through the inventor-mcp server and draw them - create a weldment, place and constrain plates and tubes, add cosmetic welds, and put ISO 2553 welding symbols (fillet, butt, plug, spot ...) on the drawing with the assembled views, parts list and balloons. Use whenever the user asks for a weldment, las, pengelasan, welded frame, rangka las, weld symbol, simbol las, fillet weld, butt weld, or a drawing of a welded part, and whenever the mcp__inventor__ weld tools (create_weldment, add_cosmetic_weld, add_weld_symbol) are involved.
---

# Weldments through MCP

Read `inventor-assembly` (placing, selectors, constraints) and `inventor-drawing` (views,
layout, title block) first; this skill adds what is different for welded work.

## What the API can and cannot do (Inventor 2027)

| Can | Cannot |
|---|---|
| create a weldment document (`create_weldment`) | create weld beads (solid fillet or groove welds): `WeldBeads` has no Add |
| cosmetic welds along edges (`add_cosmetic_weld`), counted in mass when a leg is given | weld preparations or machining features through these tools |
| welding symbols on drawings (`add_weld_symbol`) | model welding symbols (they need weld beads) |
| show a drawing view in the welds, preparations, machining or assembly state | |

So a weld is specified the way most shop drawings do it: the **welding symbol on the
drawing** carries the weld, the cosmetic weld marks the joint in the model.

## Assembled view for welded work, exploded for the rest

- **Welded assembly (weldment)**: draw it **assembled**, the way it is welded and
  delivered: front and side views of the joints, an iso view, welding symbols on the
  joints, overall dimensions, parts list, balloons. An exploded view would separate parts
  that are welded together.
- **Bolted or loose assembly**: exploded view only (see `inventor-drawing`).
- An assembly that is partly welded: the welded sub-assembly gets its own assembled
  drawing; the top-level drawing is exploded and shows that sub-assembly as one item.

An assembly that was not built as a weldment can still be drawn as a welded assembly:
`add_weld_symbol` works on any assembly view. Model the welds as a weldment only when the
cosmetic welds (or the weld mass) are wanted in the model.

## Workflow

```text
create_part / sketch / extrude for each plate or tube; save_document(...)
set_properties(part, '{"Part Number": "WB-001", "Description": "Base plate 100x60x10", "MATERIAL": "Steel"}')
create_weldment()                                      # ISO weldment template
place_component(base, grounded=True)
place_component(upright, 0, 0, 60, rx=90)              # rough pose
add_constraint("mate",  "Base_Plate:1", "face:0,0,10", "Upright_Plate:1", "face:0,-30,5")
add_constraint("flush", "Base_Plate:1", "plane:YZ",    "Upright_Plate:1", "plane:XY")
add_constraint("flush", "Base_Plate:1", "plane:XZ",    "Upright_Plate:1", "plane:YZ")
get_dof()                                              # fully constrained
add_cosmetic_weld("Upright_Plate:1", "edge:0,-30,0; edge:0,-30,10", leg=6)
analyze_interference()                                 # [] for plates that only touch
save_document("C:/.../Bracket_Weldment.iam")
```

- Weld joints are edges where two parts meet. Pick them on one component with edge
  selectors in its part coordinates, several separated by `;`. `leg` (mm) gives the
  cosmetic weld its cross-section (leg² / 2) for mass.
- The weldment template keeps the welds in an unnamed component without a file; the
  assembly tools leave it out of occurrence lists, BOM and interference.

## Drawing a weldment

```text
create_drawing()
add_base_view(iam, 120, 180, 1)           # weldment views open in the "welds" state
add_projected_view("VIEW1", 240, 180)
add_base_view(iam, 340, 230, 0.5, "iso_top_right")
add_weld_symbol("VIEW1", 0, -24, -45, 25, "fillet", "a4", sides="both", tail="135")
add_dimension(...)                        # overall sizes and positions of the parts
add_parts_list("VIEW1"); add_balloons("VIEW1")
set_title_block(...); list_views(); export_sheet_png(...); save_document(...); export_pdf(...)
```

### Welding symbols (ISO 2553, system A)

`add_weld_symbol(view, x, y, text_x, text_y, kind, size, length, sides, all_around, field, tail)`

- `(x, y)`: a point on the joint line in the view (model mm from the view centre); the
  arrow lands on the nearest curve there. `(text_x, text_y)`: where the reference line
  starts; keep it outside the part, clear of dimensions.
- `kind`: `fillet`, `square` (I butt), `v`, `bevel`, `u`, `j`, `flare_v`, `flare_bevel`,
  `plug`, `slot`, `spot`, `seam`, `back`, `surfacing`, `scarf`, `stud`.
- `size`: fillets `"a4"` (throat) or `"z6"` (leg); butt welds `"s8"` (penetration);
  spot welds `"d5"`. The tool puts it in the field that kind uses.
- `length`: `"60"`, or `"3x50(100)"` for 3 welds of 50 at a pitch of 100.
- `sides`: `arrow` (weld on the side the arrow touches: symbol on the full reference
  line, dashed identification line underneath), `other` (far side: symbol on the dashed
  line), `both` (symmetrical, e.g. fillets on both sides of a plate; no dashed line).
- `all_around=True`: circle at the knee, weld all around a profile.
  `field=True`: flag, weld made on site. `tail`: process number (ISO 4063: 111 MMA,
  135 MAG, 141 TIG) or a note.
- Fillet size rule of thumb: throat a ≈ 0.7 x thinner plate thickness, at least 3 mm.
  Say that sizes are proposals unless the user gave them.

### Checks

- One symbol per joint (or per group of identical joints with a note), pointing at the
  joint line, not at a face far from it.
- `list_views()` problems empty, PNG checked: symbols clear of dimensions and balloons.
- MATERIAL states itself: one material for all plates, a statement if they differ.

## Pitfalls

- Two constraints between the same pair of components used to clash on their default
  name; the tool now numbers them (`Flush_A_B`, `Flush_A_B_2`).
- Drawing views of a weldment contain weld curves whose geometry the API refuses
  (E_NOTIMPL); the drawing tools skip them. If you script against `DrawingCurves`
  yourself, wrap segment access in try/except.
- Cosmetic welds are not drawn as beads in the views; the symbol is what tells the welder.

Full script: `experiments/weldment_bracket.py`.
