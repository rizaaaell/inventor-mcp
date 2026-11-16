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
- Automated center marks stop inside the hole. `Centermark.ExtensionPointOne..Four` move the
  ends of the extension lines (+X, +Y, -X, -Y); they read `None` until set. Marks that belong
  to a hole pattern refuse the X legs; hide them (`Visible = False`) and add a plain mark with
  `Centermarks.Add(sheet.CreateGeometryIntent(circle, 57860), True)` instead.
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

Verified while building the phase 3 tools (2027.1):

- Picking geometry on `occurrence.Definition` (part space) and wrapping it with
  `CreateGeometryProxy` works the same for edges, faces and work features, so one
  selector code path covers them all. `Face.GetClosestPointTo(Point)` and
  `Edge.GetClosestPointTo(Point)` work on the native objects.
- `AddTangentConstraint(face1, face2, InsideTangency, offset)` between two cylinders
  puts them side by side with `InsideTangency=False`.
- `AddAngleConstraint(plane1, plane2, radians)` takes no solution type argument and
  came out healthy between two origin planes.
- `OccurrencePatterns.AddCircularPattern(ParentComponents, AxisEntity, Natural,
  AngleOffset, Count)`: AngleOffset is the step between instances in radians, Count
  includes the original. The new instances show up in `Occurrences` as `Name:n` and
  count in the BOM like placed components.
- BOM views exist only after `BOM.StructuredViewEnabled` / `PartsOnlyViewEnabled` is
  set to True; `BOMViews` names them "Structured" and "Parts Only". A row's document is
  `row.ComponentDefinitions.Item(1).Document`.
- `AnalyzeInterference` leaves out parts that only touch (tangent pins, mated faces).
  A DIN 933 bolt in a DIN 934 nut whose tapped hole is cut at the minor diameter
  overlaps by 187.51 mm³ per pair.

## Content Center

- `app.ContentCenter.TreeViewTopNode` walks the category tree by `ChildNodes` and
  `DisplayName` ("Fasteners" > "Bolts" > "Hex Head"). A node's `Families` holds the
  families; reading every `DisplayName` the first time takes about 10 s per category,
  later reads take about 1 s.
- DIN families are listed by their replacement notice: "DIN 933 - replaced by DIN EN
  24017", "DIN 934 - replaced by DIN EN 24032/28673/28674". Plain washers are
  "DIN 125-1 A" / "DIN 125-1 B" with sizes "A 10,5".
- `TableColumns` give `InternalName`s; `SIZE` and `DESIGNATION` hold the size text in the
  locale's decimal mark and with doubled spaces ("M10  x 60", "A 10,5").
  `row.Item(column index).Value` reads a cell.
- `family.CreateMember(row)` returns `(path, failure code, message)` under pywin32 and
  writes the part into the active project's Content Center folder (here
  `<project>\Libraries\Content Center Files\en-US\DIN 933\DIN 933 - M10  x 60.ipt`).
  Full signature: `CreateMember(Row, FailureReason, FailureMessage, Refresh, Custom,
  FileName, CustomInput, Options)`.
- Content Center fasteners run along their X axis. The bolt's head bearing face, the
  nut's face and the washer's face lie on x = 0: bolt head edge r 7.7, nut face edge
  r 7.65, washer bore r 5.25 at x = 0 and x = 2.
- The DIN 934 nut has a tapped `HoleFeature` at the minor diameter; the DIN 933 bolt
  has a `ThreadFeature` on a full-diameter shank. A pair overlaps by 176.85 mm³ when
  seated on a washer, 128.75 mm³ when both sit on the same origin.
- Occurrence names are the family name plus the size: "DIN 933 - replaced by DIN EN
  24017 M10  x 60:1", "DIN 125-1 A A 10,5:1". They contain commas and doubled spaces,
  so the wrapper matches names with collapsed whitespace and splits name lists on ":n".

## Assembly drawings

- `DrawingViews.AddBaseView(model, point, scale, orientation, style, ModelViewName,
  ArbitraryCamera, AdditionalOptions)`: a design view or positional representation goes in
  AdditionalOptions as `"DesignViewRepresentation"` / `"PositionalRepresentation"`
  (a NameValueMap); pass `""` and `None` for the two before it.
- `view.DrawingCurves(occurrence)` gives one component's curves, but late binding raises
  "Type mismatch" on the call. Invoke the property get with the occurrence as argument
  (`_oleobj_.Invoke(dispid, 0, DISPATCH_PROPERTYGET, True, occ)`). Pattern instances
  have curves like placed components.
- Section views of an assembly hatch each component with its own angle (45°, 135°, 60°,
  120°, ...). Content Center parts are left unhatched by default
  (`StandardPartsSectionBehavior` = `kObeyBrowserSettingsSectionStandardParts` 66563;
  `kNever...` 66562, `kAlways...` 66561).
- The API has no per-component section participation. `view.HatchRegions` items have
  `SurfaceBody.ContainingOccurrence` and a settable `Visible`; hiding the hatch of a
  shaft cut along its axis draws it the same as an unsectioned shaft.
- `PartsLists.Add(view, point, Level)`: the point becomes the parts list's top right
  corner (`Position`). Level `kPartsOnly` 46594, `kStructured` 46593, `kStructuredAllLevels`
  46595. `HeadingPlacement` 46337 top, 46338 bottom; the instance came out at the top
  although the ISO style says bottom, so it is set on the instance. Column `Width` is
  settable (cm). The Arjuna template uses `Parts List (ISO)`.
- `Balloons.Add(LeaderPoints)`: item 1 is the balloon centre (Point2d), the last item a
  GeometryIntent. As with leaders, the intent needs the point on the curve or the arrow
  lands at the curve start. Item numbers follow the BOM, so add the parts list first.
- Balloons have no `RangeBox`. With `ScaleToTextHeight` the circle measures 3x the text
  height (10.5 mm for 3.5 mm text), not `BalloonDiameter` (5.25 in `Balloon (ISO)`).
- `balloon.Leader.ArrowheadType` sets the leader end (`kFilledArrowheadType` 71941,
  `kSmallDotArrowheadType` 71949, `kNoneArrowheadType` 71948).
- Curve segments of a component seen edge-on can be neither lines nor arcs (chamfer
  ellipses); they have no `StartPoint` under late binding.

## Presentations and exploded views

- `Documents.Add(12293, template)` creates an `.ipn` (template "Standard (mm).ipn"). Its
  one scene is empty; `ipn.InsertModel(ipn.Scenes.Item(1), path)` loads an assembly, and
  `scene.TopSceneComponent.SubComponents` then lists the components.
- Tweaks cannot be added. `PresentationTweaks` and `PresentationScenes` have only
  Count/Item; `PresentationExplodedView` (one exists per document) has no tweak methods.
  The newer path, `ipn.Publications(Context)` / `ActivePublication(Context)` to reach
  `Storyboard.Tweaks.CreateTweakDefinition` + `Add`, rejects every Context tried (None,
  "", 0, 1, a NameValueMap, the scene, its name, its top component, the document) with
  E_INVALIDARG. `PresentationSnapshotViews` has no Add either, so a drawing cannot be
  pointed at an exploded state of an `.ipn` built by the API.
- Exploded views therefore come from a copy of the assembly: `doc.SaveAs(path, True)`
  writes the copy (same part files), then in the copy each pattern element after the
  first is set `Independent = True`, the pattern deleted (the components stay), all
  constraints deleted, and components moved by setting `occ.Transformation`.
- `DrawingView.ModelToSheetSpace(Point)` maps assembly points (cm) onto the sheet; used
  for the trail lines. Sketch lines in a view take `LineType` (37644 chain) and
  `LineWeight` (cm).
- In the four standard iso orientations the bolt lines of a flange with holes at
  0/90/180/270 degrees overlap in pairs. `TransientObjects.CreateCamera()` with Eye,
  Target and UpVector turned about the flange axis, passed as `ArbitraryCamera` with
  orientation `kArbitraryViewOrientation` 10763, separates them. The camera of a standard
  orientation is read from a throwaway view (`view.Camera`), which takes the next view
  name, so the new view is renamed after it.

## Title block and drawing edits (phase 6 follow-up)

- The Arjuna MATERIAL field read the model's Material iProperty, which is read-only (it
  follows `ActiveMaterial`) and empty for an assembly, so it could not say NONE or a
  statement. `tools/prepare_arjuna_templates.py` turns it into a `<Prompt>` in the migrated
  templates (the portrait templates have no MATERIAL field); the wrapper fills it.
- A title block text box can be re-justified inside `TitleBlockDefinition.Edit()`:
  `HorizontalJustification` 19969 (centre), `VerticalJustification` 25601 (middle), and
  `Origin` then is the text centre. The cell comes from the sketch lines around the label.
- `DrawingView.Center` and `Scale` are settable; `ScaleFromBase = False` first for a
  projected view. `DrawingView.Delete()` takes the views made from it along.
- `HoleThreadNote.Delete()` and `ChamferNote.Delete()` remove notes; a literal "2x " in
  front of `FormattedHoleThreadNote` counts holes made as separate features.
- `AllReferencedDocuments` of an assembly lists every part file once; their
  `ActiveMaterial.DisplayName` ("Generic" when unassigned, "Steel, Mild" for Content Center
  fasteners) gives the materials for the MATERIAL statement.
- `Face.Evaluator.GetNormalAtPoint([x, y, z], [0, 0, 0])` returns `(points, normals)`, and
  the normal points out of the solid: what `auto_explode` uses to tell which side of a
  seat face a component sits on. The middle of the parent part is not enough: a washer on
  the back of a flange disk sits below the middle of the flange when the hub is long.

## Weldments

- `Documents.Add(12291, "Metric/Weldment (ISO).iam")` gives a weldment: an assembly whose
  `ComponentDefinition` is a `WeldmentComponentDefinition` with `Welds`, `Preparations`,
  `Machining`. Its occurrences include the welds as an unnamed occurrence whose
  `ReferencedDocumentDescriptor` is `None`; skip it when reading component files.
- Weld beads cannot be created: `WeldBeads` has only Count/Item. `Welds.Edit()`, then
  `Welds.CosmeticWelds.CreateDefinition(EdgeCollection)` and `Add(definition)`, then
  `Welds.ExitEdit()` make a cosmetic weld. `CosmeticWeldDefinition.Area` is an expression
  string ("0.00 in^2"), set as `"18 mm^2"`, not a Parameter.
- Drawing views of a weldment open in the assembly state; `view.SetWeldmentState(80899)`
  (`kWeldsWeldmentState`; 80897 assembly, 80898 machining, 80900 preparations) shows the
  welds. Their curves raise `E_NOTIMPL` on `Segments`; skip them when scanning curves.
- Welding symbols: `defs = sheet.WeldingSymbols.CreateDefinitions()` starts empty;
  `d = defs.Add(1)`, set `d.WeldSymbolOne` (and `WeldSymbolTwo` for both sides):
  `WeldSymbolType` (fillet 124162, square 124176, V 124178, bevel 124179, U 124181,
  J 124182, plug 124163, spot 124166, seam 124169), then the size. The size field depends
  on the type: fillets take `SizeOrStrength` ("a4"), butt welds `PenetrationDepth` ("s8"),
  spot welds `Diameter`; the other fields raise `E_FAIL`. `Length` takes "50" or
  "3x50(100)". `IdentificationLinePlacement` 122881 none, 122882 above, 122883 below
  puts the ISO dashed line; `AllAroundSymbol`, `FieldWeldingSymbol`, `TailNote`.
  `sheet.WeldingSymbols.Add(leaderPoints, defs)` places it (leader points as for notes).
- Two constraints with the same name raise `E_INVALIDARG` on `Name`; the second flush
  between one pair of components needs its own name.

## Drawing details found on the wheel hub drawings

- `GeneralDimension.Precision` is settable per dimension. The profile's one decimal turned
  121.42 into "121,4"; `add_dimension` and `retrieve_dimensions` now raise the precision to
  what `ModelValue` needs, up to two decimals (three would tighten the general tolerance).
  `ModelValue` showed 68.835 where the design said 68.84.
- `HoleThreadNotes.Add(position, curve)` also takes the line of a cosmetic thread seen from
  the side and prints "M42x1.5 - 6g"; setting `FormattedQuantityNote` on such a note fails.
- Holes cut in one sketch get no bolt circle from automated centerlines.
  `Centerlines.AddCenteredPattern(centerIntent, ObjectCollection of hole intents, None, None,
  True)` with `kCenterPointIntent` (57860) intents draws it.
- A diameter dimension's leader runs from the text towards the circle centre; where it meets
  the circle is decided by the text position, not by the intent point. Put the text on the
  angle the arrow should land on (e.g. between two bolt holes).
- `DrawingView.SetVisibility(occurrence, False)` hides a component in one view only; the
  view box shrinks to what is left. Occurrences hidden in the assembly's design view can
  still show in a drawing view.
- `PartsListRow.Visible = False` leaves a row out; `PartsList.Renumber()` closes the gap.
- `DrawingWeldingSymbol` has no `RangeBox`; `Position` is the knee of the reference line.
- A weld symbol needs no weldment: `Sheet.WeldingSymbols.Add` works on any assembly view.

- **No drawing datum identifier in the API.** The ribbon's Datum Identifier Symbol has no
  collection on `Sheet` (the typelib only has `ModelDatum*` for 3D annotations).
  `add_datum` draws the same shape with a sketched symbol: triangle
  (`kDatum60FilledArrowheadType`) on the dimension shoulder, square leader to the box.
- **`AddAngular` refuses a point intent at 180° on a circle** (the one at 0° works), so an
  angle from the axis is measured from the right side.

## Closing documents

- `Document.Close` on a part an open assembly or drawing still uses shows an
  "Encountered an improper argument" dialog. While it is up, further `Close` calls return
  without error and do nothing, so the documents stay open hidden; closing more referenced
  files then crashed Inventor (access violation c0000005). Close drawings and assemblies
  first: `inv.close_documents_in(folder)` closes the documents of a folder whose
  `ReferencingDocuments` is empty, repeats, and raises if a `Close` was ignored.

## Wrapper fixes in phase 1

- **Tools followed the active tab.** Activating another document between two calls
  made `save_document` write the wrong part. `create_part` now pins its document;
  a document opened after the pin takes over once it is active.
  `inv.release_document()` drops the pin by hand.
- **`execute_python` lost stderr.** It now captures stdout and stderr.
- **`export_document`** found no translator (see above) and fell back to
  `doc.SaveAs` for add-ins without `SaveCopyAs`, which would have written an `.ipt`
  under the export name. The fallback is gone; a missing output file raises.
