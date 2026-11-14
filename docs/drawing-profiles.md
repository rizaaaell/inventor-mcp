# Drawing profiles

A profile holds the drawing standard that `create_drawing` applies to every new
drawing: template, sheet, projection, units, dimension format and label formats.
Profiles live in `drawing_profiles/<name>.json`; `create_drawing(profile="name")`
picks one, and `default` is used when none is named. Edit the JSON to change the
standard; no code change or server restart is needed.

| Profile | Template |
|---|---|
| `default` | Arjuna A3 landscape, the migrated copy in `references/templates/2027/` (not in git) |
| `iso` | Inventor's own ISO template, same settings; for machines without the team files |

| Key | Meaning |
|---|---|
| `template` | `builtin:Metric/ISO.idw` for a template shipped with the installed Inventor, or a path to an `.idw` (absolute, or relative to the repo root, e.g. `references/templates/A3.idw`). A template from an older Inventor release must be opened and saved once in the current one first. |
| `sheet_size` | `A0` … `A4`. Leave empty to keep the template's sheet. |
| `projection` | `third` or `first` angle. Decides where a projected view lands: in third angle a view placed above the front view is the top view. |
| `units` | `mm` |
| `decimal_marker` | `comma`, `period` or `default` |
| `dimension_precision` | decimal places, 0 to 8 |
| `trailing_zeros` | `false` prints `120` and `8,5` instead of `120,00` and `8,50` |
| `labels.section_view`, `labels.detail_view`, `labels.auxiliary_view` | title above the view |
| `labels.section_line`, `labels.detail_fence` | letter at the section line ends and at the detail circle |
| `hole_note_quantity` | prefix of hole notes on patterned holes; `<Quantity/>` is the hole count |
| `centerline_line_type` | `chain` (long dash, short dash, as ISO 128 wants for axes and pitch circles), `dashed` or `continuous`; the ISO centerline layer otherwise draws bolt circles as plain dashes that look like hidden lines |
| `centerline_overshoot_mm` | how far `add_centerlines` runs each cylinder axis past the outline |
| `title_block_aliases` | names people use for a field the title block calls otherwise, e.g. `"APPROVED BY": "CHECKED BY"` in the Arjuna block |
| `title_block_defaults` | values filled into empty fields when the first view is placed, e.g. `"DOCUMENT TYPE": "ENGINEERING DRAWING"` |
| `general_tolerances` | values written after each "=±" of the title block's TOLERANCES OTHERWISE NOTED text, e.g. `{".X": "0,2", ".XX": "0,1", ".XXX": "0,05", "ANGULAR": "1°"}` |

Label texts use Inventor's tokens: `<DrawingViewName/>`, `<DrawingViewScale/>`,
`<DrawingViewSheetName/>`, `<DrawingViewSheetIndex/>`, `<DrawingViewSheetZone/>`
and the `Parent...` variants. The Inventor ISO defaults append
`/ <sheet><index>.<zone>`, which prints as "A / .A6" on an unnamed sheet; the default
profile leaves that part out.

The profile changes styles inside the new drawing only; the template and the style
library are not touched.

## Preparing the Arjuna templates

1. `python -X utf8 -u tools/prepare_arjuna_templates.py` copies every template from
   `references/templates/` to `references/templates/2027/`, saves it once in this
   Inventor, adds a DOCUMENT TYPE prompt under its label, and sets the name fields to
   2 mm so "Rachmadi Norcahyo" fits the APPROVED BY box. Rerunning it keeps existing
   copies (and their imported styles); `--force` starts over from the originals.
2. The Arjuna styles (`Arjuna Fix.styxml`: dimension style "Arjuna", one decimal,
   comma, no trailing zeros, Tahoma 3.5 mm text, leader; `Mini Center Mark` and
   `Super Mini Center Mark`) have no import call in the Inventor API. Open the copy,
   Manage → Styles Editor → Import each `.styxml`, Save and Close, close the template,
   and run the script again: it copies the imported leader and text styles to
   "Arjuna Leader" and "Arjuna Note Text" and makes "Arjuna Standard" active with
   "Arjuna Object Defaults" pointing at them. Done for
   `Template Landscape Arjuna FIX A3.idw` on 2026-11-14; the other four still need it.

   The copies matter: with the project's style library on, a new drawing replaces every
   style whose name the library also has (`Object Defaults (ISO)`, `General (ISO)`,
   `Note Text (ISO)`) with the library version, so imported settings under those names
   are lost.
3. Close the template in Inventor before making drawings: `Documents.Add` refuses a
   template that is open.

Until a template has the styles, the profile's number format settings still give the
Arjuna look for dimensions.
