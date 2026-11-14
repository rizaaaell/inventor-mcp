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
| `centerline_overshoot_mm` | how far `add_centerlines` runs each cylinder axis past the outline |

Label texts use Inventor's tokens: `<DrawingViewName/>`, `<DrawingViewScale/>`,
`<DrawingViewSheetName/>`, `<DrawingViewSheetIndex/>`, `<DrawingViewSheetZone/>`
and the `Parent...` variants. The Inventor ISO defaults append
`/ <sheet><index>.<zone>`, which prints as "A / .A6" on an unnamed sheet; the default
profile leaves that part out.

The profile changes styles inside the new drawing only; the template and the style
library are not touched.

The Arjuna dimension style (`references/templates/Arjuna Fix.styxml`: one decimal,
comma, no trailing zeros, Tahoma 3.5 mm) has no import call in the Inventor API. The
profile reproduces its number format; for the exact style, import the `.styxml` once
into the migrated template through the Style and Standard Editor and save the template.
