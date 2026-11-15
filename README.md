# inventor-mcp

**MCP server for Autodesk Inventor: parts, assemblies and 2D drawings driven by Claude (or any MCP client) in natural language.**

This is a fork of [NeonGlay/inventor-mcp](https://github.com/NeonGlay/inventor-mcp), extended for
**Inventor 2027** with assemblies, Content Center fasteners, engineering drawings (views,
sections, dimensions, GD&T, title block, parts list, balloons, exploded views) and PDF output.

```
You:    "Rakit kopling flens dari Flens.ipt dan Poros.ipt, baut DIN 933 M10 dari Content Center,
         lalu buat gambar kerja A3 dengan parts list dan balon."
Claude: places and constrains 20 components (DOF 0), checks BOM and interference,
        then lays out views, section, parts list and balloons, and exports the PDF.
```

## Tested with

| | Version |
|---|---|
| Autodesk Inventor | 2027.1 (Professional, Windows 11) |
| Python | 3.13 (3.12+ required) |
| `mcp` | 1.30 (pinned `>=1.0.0,<2`) |
| `pywin32` | 312 |

Older Inventor releases (2026) worked with the upstream tools; enum differences are noted
in `docs/inventor-api-notes.md` and `docs/inventor-2027-notes.md`.

## Installation

1. Clone:
   ```
   git clone https://github.com/rizaaaell/inventor-mcp.git
   cd inventor-mcp
   ```
2. Install the dependencies. **Keep `mcp` below 2**: the server is written against the
   1.x `mcp.server.fastmcp` API, and the pin in `pyproject.toml` stops an upgrade from
   changing it underneath you.
   ```
   pip install -e .
   ```
   or by hand: `pip install "mcp[cli]>=1.0.0,<2" "pywin32>=306"`.
3. Register the server with your MCP client. For Claude Code, a `.mcp.json` in the
   project root (copy `.mcp.json.example`; the real file is git-ignored):
   ```json
   {
     "mcpServers": {
       "inventor": {
         "command": "python",
         "args": ["-m", "src.server"],
         "cwd": "C:/path/to/inventor-mcp"
       }
     }
   }
   ```
4. Start Inventor yourself and let it finish loading, then ask the assistant to connect.
   `connect` can start Inventor, but a freshly started instance may wait on a startup
   dialog.

**Dialogs block automation.** Any modal Inventor dialog (template migration, errors)
stops every COM call until someone clicks it. The tools avoid the known ones (the Style
Conflict dialog on new documents); for the rest, the user has to click.

Do not use `win32com.client.gencache.EnsureDispatch` against the same Python install; its
`gen_py` cache breaks `GetActiveObject`. Read `RxInventor.tlb` with
`pythoncom.LoadTypeLib` instead (see the modeling skill).

## Tools (73)

All lengths in mm, angles in degrees.

**Power tools**: `execute_python` (Python against the live connection, persistent
namespace), `reload_api` (hot-reload the wrapper), `inspect`, `list_edges`, `list_faces`,
`transaction` (begin / commit / abort as one undo step).

**Connection and documents**: `connect`, `status`, `create_part`, `save_document`,
`export_document` (STEP, IGES, SAT, STL, PDF).

**Sketches**: `create_sketch` (work plane, body face or offset plane), `draw_rectangle`,
`draw_circle`, `draw_line`, `draw_polygon`, `draw_closed_profile`.

**Features**: `extrude`, `revolve`, `fillet`, `chamfer`, `hole` (drilled, tapped,
through or blind), `hole_linear` (placed from two edges, counterbore), `circular_pattern`.

**Parameters and features**: `get_parameters`, `set_parameter`, `add_parameter`,
`list_features`, `delete_feature`, `suppress_feature`, `find_edge`, `find_face`.

**Sheet metal**: `set_sheet_metal_thickness`, `sheet_metal_face`, `flange`,
`sheet_metal_cut`.

**Assemblies**: `create_assembly`, `place_component`, `list_occurrences`,
`list_occurrence_geometry`, `add_constraint` (mate, flush, insert, angle, tangent; geometry
picked by selectors such as `circle:45,0,20,5.5` in part coordinates), `get_dof`, `get_bom`,
`analyze_interference` (flags bolt-in-tapped-hole overlaps as thread artifacts),
`pattern_component`, `list_content_center`, `place_content_center`. Saving an assembly
also writes its constraint order to `<name>.constraints.json`.

**Exploded views**: `create_exploded_copy`, `explode_components`, `add_explode_trails`.
Inventor 2027's presentation API cannot add tweaks, so exploded drawings come from a
constraint-free copy of the assembly.

**Drawings**: `create_drawing` (from a drawing profile), `add_base_view` (parts and
assemblies, design view, turned iso camera), `add_projected_view`, `add_section_view`
(unhatched shafts), `add_detail_view`, `add_centerlines`, `retrieve_dimensions`,
`add_dimension` (linear, diameter, radius, PCD, angle), `list_dimensions`,
`delete_dimension`, `move_dimension`, `set_tolerance` (symmetric, deviation, limits, ISO
fits, basic), `add_hole_note`, `add_chamfer_note`, `add_gdt`, `add_datum`,
`add_surface_finish`, `set_title_block`, `add_parts_list`, `add_balloons`, `list_views`
(layout checker), `export_sheet_png`, `export_pdf`.

## Drawing profiles

`drawing_profiles/*.json` set template, sheet size, projection angle, units, decimal mark,
precision, view labels, general tolerances, title block defaults and parts list layout
(`docs/drawing-profiles.md`). `default` uses a team template that is not in this
repository (`references/` is git-ignored); `iso` uses Inventor's own ISO template and
works on any machine: `create_drawing(profile="iso")`.

## Skills

`skills/` holds four [Agent Skills](https://code.claude.com/docs/en/skills) that teach the
workflow and the API traps:

- **inventor-modeling**: parts, sketches, holes, sheet metal, Inventor 2027 differences.
- **inventor-assembly**: placing, constraining, Content Center, DOF, BOM, interference,
  exploded copies.
- **inventor-drawing**: view choice, dimension strategy, annotations, layout checks,
  parts lists, balloons, exploded drawings, PDF.
- **inventor-din-parts**: parametric DIN/ISO nuts, bolts, washers and flanges built as parts.

Install by copying them into your skills directory:
```
cp -r skills/* ~/.claude/skills/
```

## Tests

With Inventor running:

```
python -X utf8 -u tests/smoke.py        # 8 regression cases, volumes and drawing layout
python -X utf8 -u tests/audit_tools.py  # every tool, 105 checks
```

Test output goes to `C:\inventor-test\`. `experiments/` holds the full scripts behind the
acceptance results (flange drawing, coupling assembly, assembly and exploded drawings).

## Layout

```
src/server.py          FastMCP server: tool definitions (stdio)
src/inventor_api.py    InventorConnection: COM wrapper, all geometry logic (mm)
drawing_profiles/      drawing standards as JSON
skills/                Agent Skills
docs/                  API field notes (2026 and 2027), profile and reference docs
tests/                 smoke test and full tool audit
experiments/           acceptance scripts
tools/                 PDF to PNG renderer, template preparation
```

## License

MIT, see [LICENSE](LICENSE). Upstream work by NeonGlay.
