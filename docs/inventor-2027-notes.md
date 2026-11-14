# Inventor 2027 — Field Notes

What was observed while driving Inventor 2027.1 through `pywin32` late binding.
Companion to `inventor-api-notes.md` (written for 2026). Everything here was seen
working or failing in a live session, or read from the 2027 type library.

`tests/audit_tools.py` exercises every MCP tool; rerun it after an Inventor update.

## Enum values

Checked against `D:\Inventor 2027\Bin\RxInventor.tlb`. The library was read with
`pythoncom.LoadTypeLib`, which needs no Inventor connection and leaves no `gen_py`
cache behind (unlike the gencache probe in the 2026 notes).

All constants in `src/inventor_api.py` match, except the surface type table:

| Value | 2027 type library | Old wrapper and 2026 notes |
|---|---|---|
| 5890 | `kPlaneSurface` | plane |
| 5891 | `kCylinderSurface` | cylinder |
| 5892 | `kEllipticalCylinderSurface` | cone |
| 5893 | `kConeSurface` | cone / sphere |
| 5894 | `kEllipticalConeSurface` | sphere / torus |
| 5895 | `kTorusSurface` | torus |
| 5896 | `kSphereSurface` | missing |
| 5897 | `kBSplineSurface` | missing |

`list_faces` and `find_face` are fixed. `skills/inventor-modeling/SKILL.md` and
`docs/inventor-api-notes.md` still carry the old table; the skill is updated in phase 6.

Other values confirmed in the library:

| Value | Name |
|---|---|
| 12290 / 12291 / 12292 / 12293 | `kPart` / `kAssembly` / `kDrawing` / `kPresentationDocumentObject` |
| 20993 / 20994 / 20995 | positive / negative / symmetric extent direction |
| 20481 – 20485 | join, cut, intersect, surface, new body |
| 19201 / 19202 / 19203 | horizontal / vertical / aligned dimension |
| 13059 | `kFileBrowseIOMechanism` |
| 47363 | `kOptimizedCompute` |
| 75521 | `kHeightDatumOuter` (flange height datum) |
| 5124 | `kCircleCurve` (5123 line, 5125 arc) |
| 11778 | `kUpToDateHealth` |
| 11269 / 11272 | `kMillimeterLengthUnits` / `kInchLengthUnits` |

## Dialogs that block automation

- Creating a document from `Metric\Standard (mm).ipt` can open a modal **Style
  Conflict** dialog: the template's `Dimension: Default - mm (ANSI) - 3DA` style
  differs from the style library. Every COM call waits until someone clicks OK; the
  MCP request times out and the server reports "Not connected to Inventor". In the
  audit it showed up on the first document of a fresh Inventor session.
  Fixed: `create_part` sets `Application.SilentOperation = True` around
  `Documents.Add`, which accepts the dialog's default. Verified on a freshly
  started Inventor: the audit's first `create_part` ran with no dialog.
- The call that timed out still completes inside Inventor afterwards. That left an
  extra unnamed `PartN` document open more than once.
- `connect()` starts a new Inventor when none is running. That instance once sat at
  "Not Responding" for over five minutes; most likely a startup dialog waiting.
- A template saved by an older Inventor release opens a modal "needs to be migrated"
  dialog even with `SilentOperation` on, and `Documents.Add` then fails with
  `E_INVALIDARG`. Every `.idw` in the project's Templates folder does this. Open and
  save such a template once in 2027 before using it.

## Translators

Display names changed in 2027 to `Translator: STEP`, `Translator: IGES`,
`Translator: SAT`, `Translator: STL Export`, so the old name match found nothing and
`export_document` failed for every format. Look add-ins up by ClassId with
`ApplicationAddIns.ItemById`:

| Format | ClassId |
|---|---|
| STEP | `{90AF7F40-0C01-11D5-8E83-0010B541CD80}` |
| IGES | `{90AF7F44-0C01-11D5-8E83-0010B541CD80}` |
| SAT | `{89162634-02B6-11D5-8E80-0010B541CD80}` |
| STL | `{533E9A98-FC3B-11D4-8E7E-0010B541CD80}` |
| PDF | `{0AC6FD96-2F4D-42CE-8BE0-8AEA580399E4}` |
| DWG / DXF | `{C24E3AC2-122E-11D5-8E91-0010B541CD80}` / `{C24E3AC4-...}` |

The translators report `Activated = False` until used; call `Activate()` first.
`HasSaveCopyAsOptions(doc, context, options)` fills `options` with the defaults.

## Edge geometry

- `edge.Evaluator.GetParamExtents()` returns `(min, max)`.
- `GetLengthAtParam(min, max)` returns the length along the curve in cm.
- `GetPointAtParam([t], [0.0, 0.0, 0.0])` returns `((t,), (x, y, z))`.
- A full circle has one vertex, so start and end coincide. Measuring between the
  vertices gave length 0 and a "midpoint" on the seam; `list_edges` and `find_edge`
  now use the evaluator and match full circles by their center.

## Part modeling behaviour

- Positive extent direction follows the sketch normal. On a sketch placed on a body
  face the normal points out of the body: a positive cut removes nothing, silently.
  Cut with `direction="negative"`.
- `AddByThroughAllExtent` cuts on the chosen side only; symmetric cuts both sides.
- A sketch on a body face of a centered block had its origin at the world origin
  projected onto the face; check with `SketchToModelSpace` rather than assuming.
- A chamfer on one line of a loop that is tangent to fillets runs around the whole
  tangent chain.
- `hole()` drills from the XY plane in the negative direction and still cuts a body
  that sits above the plane, for through-all and for blind tapped holes.
- A blind tapped hole from `hole()` removed exactly the minor-diameter cylinder:
  no drill point in the volume.
- Tapped holes are cut at the minor diameter (M8x1.25: 6.647 mm, M10x1.5: 8.376 mm).
- `set_sheet_metal_thickness` works on an en-US locale: the Thickness parameter
  reads back the requested value.
- A join extrude that does not touch the existing body is fine once a later
  feature connects the pieces. An extrude with operation `new` makes a second body,
  and later cuts and `inspect` only see body 1.
- Sketches on the XZ plane are mirrored (sketch X is world -X).

## Drawings

- Template: `C:\Users\Public\Documents\Autodesk\Inventor 2027\Templates\en-US\Metric\ISO.idw`
  gives A3 landscape, `Default Standard (ISO)`, first angle projection. Its border
  spans x 10–410, y 10–287 mm and its title block x 240–410, y 10–40 mm.
- Sheet coordinates are cm from the bottom-left corner. `DrawingView.Left`, `Top`,
  `Width`, `Height` give the view box; `Top` is the upper edge.
- `kFrontViewOrientation` (10764) looks along the part's -Z axis, so a flange modeled
  on XY shows its circular face in the front view.
- A deleted view keeps its name in use: after a rejected `VIEW1` the next view is
  `VIEW2`. Read view names from tool results instead of guessing.
- `AddSectionView` needs a `DrawingSketch` on the parent view:
  `view.Sketches.Add()`, `Edit()`, a line between `SheetToSketchSpace` points, `ExitEdit()`.
- `AddDetailView(parent, position, style, True, fenceCenter, fenceRadius_cm, None, scale, True, label)`
  for a circular fence; the fence center and radius are in sheet space.
- `GeneralDimensions.GetRetrievableDimensions(view)` then `Retrieve(view, collection)`;
  the new dimensions are appended at the end of `GeneralDimensions`. A section view
  of the flange had none to retrieve.
- `DrawingDimensions.Arrange(ObjectCollection)` spaces linear dimensions but leaves
  diameter dimensions in place. `retrieve_dimensions` pushes overlapping texts apart
  itself, using `DimensionText.RangeBox`; view labels have a `RangeBox` as well.
- The "A / .A6" labels at the section line ends and the label above a detail circle
  expose no extent. The wrapper estimates boxes from `SectionLineSketch` line ends
  and `FenceCenter` / `FenceRadius`, and keeps dimension texts off them.
- `view.DrawingCurves` is a property. Calling it, `view.DrawingCurves()`, fails with
  "Invalid number of parameters".
- Drawing curve segments carry 2D geometry in sheet cm: circles and arcs have `Center`
  and `Radius`, lines `StartPoint` and `EndPoint`.
- `GetAutomatedCenterlineSettings()` returns the settings object (the out parameter
  becomes the result); set the `ApplyTo...` flags and pass it back.
- The ISO title block reads the drawing's iProperties: `<TITLE>`, `<PART NUMBER>`,
  `<COMPANY>`, `<AUTHOR>` (printed under "Designed by"), `<CHECKED BY>`,
  `<ENG APPROVED BY>`, `<REVISION NUMBER>`. It has no description or material field.
  `TitleBlock.GetResultText(textBox)` returns what is printed.
- `NameValueMap.Value(name) = x` has no syntax under late binding; the wrapper puts
  it through `Invoke` with `DISPATCH_PROPERTYPUT`.
- PDF options: `Sheet_Range` 14082 all sheets, 14081 active sheet (the default);
  `All_Color_AS_Black`; `Vector_Resolution`. An A3 sheet comes out as one page with
  `MediaBox` 1191 x 842 pt.
- `ActiveView.Fit()` then `SaveAsBitmap(path, w, h)` captures the whole sheet.
- Drawing standard settings live on `StylesManager.ActiveStandardStyle`:
  `FirstAngleProjection`, `LinearUnits`, `DecimalMarkerType`, and
  `GetViewLabelDefaults` / `SetViewLabelDefaults(viewType, prefix, visible, text,
  constrainToBorder, placeBelowView)` for view titles. Section line and detail circle
  letters use `SetViewAnnotationDefaults(viewType, text)`; base and projected views
  have no annotation and raise `E_INVALIDARG`. The defaults apply to views created
  afterwards. Dimension format is on `ActiveObjectDefaults.Linear/Diameter/
  RadialDimensionStyle`: `LinearPrecision` (41729 + decimal places) and
  `TrailingZeroDisplay`.
- `DrawingNotes.HoleThreadNotes.Add(position, holeEdgeCurve)` makes a hole note
  ("Ø11,00 THRU"). The pattern count is not shown by default: prefix
  `FormattedHoleThreadNote` with `<QuantityNote/>`; `FormattedQuantityNote`
  (`<Quantity/>x`) sets its text.
- A title block field shows either a `<Prompt>` (fill with
  `TitleBlock.SetPromptResultText(textBox, value)`) or a `<Property Document='model'|'drawing'
  PropertySet=... Property=... FormatID=... PropertyID=...>` tag. The Arjuna template
  reads TITLE, REVISION NUMBER, CREATION DATE, ENGINEER, CHECKED BY and MATERIAL from the
  model, PART NUMBER and SURFACE FINISH are prompts. `PropertySets.Item(FormatID)` and
  `ItemByPropId(id)` find the property in the right document.
- The Material iProperty is read-only (`E_FAIL`). Set the part's
  `ActiveMaterial` to an asset of `MaterialAssets`, copying it from
  `Application.ActiveMaterialLibrary.MaterialAssets` with `CopyTo(part)` first.
- Saving a drawing with `SaveAs` also saved the model whose iProperties had changed.
- Setting `Centerline.StartPoint` / `EndPoint` so the line would run the other way is
  ignored without an error. Keep the line's direction; then the new ends hold through
  `Update` and save.
- Automated centerlines often cover one feature only: the flange's axis stopped at the
  hub in the section and at the disk in the side view. A drawing curve's
  `ModelGeometry` is the cylindrical or conical face (`Geometry.BasePoint`,
  `AxisVector`), and `DrawingView.ModelToSheetSpace` projects the axis onto the sheet.
- `AttributeSets.Add(name)` / `AttributeSet.Add(name, 14595, value)` tag a dimension
  with its view; a retrieved dimension's `Intent.Geometry` is `None`, so the view
  cannot be read back from the dimension itself.
- `.styxml` style exports have no import call in the API (no `Import` on the styles
  managers); import them through the Style and Standard Editor. The editor's library
  is read-only here, so imports land in the document's local styles.
- `Documents.Add` fails with `E_INVALIDARG` when the template file is open in Inventor.
- With the project's style library in use, a new document takes the library's version
  of every style name the library has; the template's edits to those styles are
  dropped (the "Style Conflict" dialog says so). Styles under new names survive. Hence
  "Arjuna Standard" / "Arjuna Object Defaults" / "Arjuna Leader" / "Arjuna Note Text".
- Retrieved dimensions in a side view of a turned part also bring the sketch diameters,
  placed wherever there is room, which can be outside the border. Diameters of turned
  parts read better as Ø-prefixed linear dimensions in the section or side view.
- `TextBox.FormattedText` takes the decimal mark the document uses
  (`FontSize='0,2'` here); the other mark is refused with `E_INVALIDARG`.
- Tolerances: `GeneralDimension.Tolerance.SetToSymmetric / SetToDeviation /
  SetToLimits / SetToFits(type, hole, shaft)`, values in cm. `SetToShowFits` raises
  `E_NOTIMPL`. Fit type 31242 (`kLimitsFitsLinearTolerance`) prints "Ø30 H7"; 31243
  adds the size limits "(30,021/30,000)".
- Feature control frames: `FeatureControlFrames.CreateFeatureControlFrameRows()`,
  `rows.Add(characteristic, tolerance, lower, datum1, datum2, datum3)`, then
  `FeatureControlFrames.Add(leaderPoints, rows)`. The tolerance string is printed as
  is: "n0,2" shows "n0,2", so put the Ø character itself in it.
- There is no datum identifier collection in the drawing API. A sketched symbol (box
  plus a `<Prompt>` letter) placed with `SketchedSymbols.AddWithLeader` and
  `Leader.ArrowheadType = 71955` (`kDatum60FilledArrowheadType`) does the job.
  `PromptStrings` must be a typed string array
  (`VARIANT(VT_ARRAY | VT_BSTR, [...])`); a tuple gives `E_INVALIDARG`.
- `SurfaceTextureSymbols.Add(leaderPoints, type, forceTail, majority, allAround, maxRoughness)`.
- `Sheet.CreateGeometryIntent(curve)` without a point attaches a leader to the curve's
  start; pass a sheet `Point2d` on the curve as the second argument to land elsewhere.
- The ISO centerline layer draws a circular centerline (a bolt circle) as plain dashes, which reads
  as a hidden line. Setting the layer's `LineType` to 37644 (`kChainLineType`) gives the long dash,
  short dash chain that ISO 128 asks for, on straight and circular centerlines alike.
- `DrawingNotes.ChamferNotes.Add(position, chamferCurve, adjacentCurve)` gives "1 X 45°"; its
  default format carries a zero symmetric tolerance ("1 ± 0 X 45° ± 0°"), strip the Tolerance
  attributes from `FormattedChamferNote`. A chamfer note's `Text` is a plain string.
- Text appended to `FormattedHoleThreadNote` after the last `</StyleOverride>` falls back to a
  large default font; put extra lines inside that run.
- Automated centerlines include the bolt circle of a circular pattern. A circular
  `Centerline` has `Geometry.Center` / `Radius` in sheet cm, and
  `GeneralDimensions.AddDiameter(textPos, sheet.CreateGeometryIntent(centerline))`
  dimensions it (PCD).
- The ISO view labels add sheet name and zone, e.g. `A-A ( 1 : 1 ) / .C5`; with an
  unnamed sheet that leaves a bare "/ .C5". Dimensions print two decimals with a comma
  (`Ø120,00`) from the ISO dimension style.

## Assembly API

- `occurrence.SurfaceBodies` returns proxies. Its edges and faces go straight
  into `Add*Constraint`. `proxy.NativeObject` gives the part-space geometry, which
  does not move with the occurrence and is the stable way to pick an edge.
- `occurrence.CreateGeometryProxy(native)` returns the proxy as its result.
  It is needed for work planes and axes, which have no occurrence-level collection.
- Assembly origin planes are `ComponentDefinition.WorkPlanes.Item(1..3)` (YZ, XZ, XY)
  and are used directly, without a proxy.
- `AddInsertConstraint(edge1, edge2, axesOpposed, offset)`: offset is in cm. With
  opposed axes a negative offset pushes the second part into the first.
- `AddFlushConstraint(plane1, plane2, offset)`: positive offset moves the second
  part along the first plane's normal.
- `AddMateConstraint` between two cylindrical faces makes their axes coincident.
- `AddAngleConstraint(plane1, plane2, radians)` picked the opposite sense on the
  first try. Check the resulting transform and negate `constraint.Angle.Value` if needed.
- `occurrence.GetDegreesOfFreedom()` returns a tuple:
  `(translation count, translation vectors, rotation count, rotation vectors, center)`.
- `ComponentDefinition.AnalyzeInterference(ObjectCollection)` returns results with
  `OccurrenceOne`, `OccurrenceTwo`, `Volume` (cm3) and `Centroid`.
- `MeasureTools.GetMinimumDistance(a, b)` returns a tuple; the distance in cm is item 0.
- `Occurrences.Add` fails with `E_INVALIDARG (-2147024809)` when the file does not
  exist on disk, which includes a part that was built but never saved.

## Wrapper fixes in phase 1

- **Tools followed the active tab.** Activating another document between two calls
  made `save_document` write the wrong part. `create_part` now pins its document;
  a document opened after the pin takes over once it is active.
  `inv.release_document()` drops the pin by hand.
- **`execute_python` lost stderr.** It now captures stdout and stderr.
- **`export_document`** found no translator (see above) and fell back to
  `doc.SaveAs` for add-ins without `SaveCopyAs`, which would have written an `.ipt`
  under the export name. The fallback is gone; a missing output file raises.
