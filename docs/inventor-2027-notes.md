# Inventor 2027 — Field Notes

What was observed while driving Inventor 2027.1 through `pywin32` late binding.
Companion to `inventor-api-notes.md` (written for 2026). Everything here was seen
working or failing in a live session; nothing is taken from documentation.

Enum values below were confirmed by use, not yet checked against the 2027 type
library. That check is a phase 1 task.

## Still valid from the 2026 notes

Used unchanged in 2027.1 and behaved as documented:

- `kPartDocumentObject = 12290`
- Extent directions `20993 / 20994 / 20995`, operations `20481` (join), `20482` (cut), `20485` (new body)
- `ChamferFeatures.AddUsingDistance(EdgeCollection, cm)`
- `RevolveFeatures.AddFull` for full revolves, partial revolves by angle
- Tapped holes through `hole(tapped=True)`: M10x1.5 is cut at the 8.376 mm minor diameter

## Enum values first used in 2027

| Value | Meaning | Where it was used |
|---|---|---|
| `12291` | `kAssemblyDocumentObject` | `Documents.Add` with `Metric\Standard (mm).iam` |
| `5124` | circular curve (`Edge.GeometryType`) | picking circular edges for insert constraints |
| `5891` | cylinder (`Face.SurfaceType`) | picking axle and bore faces for axis mates |
| `11778` | healthy (`HealthStatus` of a constraint or feature) | constraint health check |

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
- A join extrude that does not touch the existing body is fine once a later
  feature connects the pieces. An extrude with operation `new` makes a second
  body, and later cuts and `inspect` only see body 1.

## Wrapper behaviour found in 2027 sessions

- **Tools followed the active tab.** Every wrapper method resolved
  `app.ActiveDocument`, so activating another open document between two calls
  made `save_document` write the wrong part under the requested file name.
  Fixed: `create_part` pins its document, and `active_document()` returns the
  pinned one and re-activates it. A document opened after the pin takes over when
  it becomes active. `inv.release_document()` drops the pin by hand.
- **`list_edges` reports length 0 for closed circular edges**, so any
  `min_length` filter hides them. Open.
- **`execute_python` captures stdout only.** `traceback.print_exc()` is lost;
  use `print(traceback.format_exc())`. Open.
- **Sketches on the XZ plane are mirrored** (sketch X is world -X), as the 2026
  notes say. Confirmed in 2027.

## Stalls and popups

- A modal dialog in Inventor blocks every COM call until someone clicks it. The
  MCP request then times out and the server reports "Not connected to Inventor".
  The dialog has to be answered by hand.
- The call that timed out usually still completes inside Inventor. After a
  timeout on `create_part` there can be an extra unnamed `PartN` document open.
- `connect()` starts a new Inventor when none is running. That instance sat at
  "Not Responding" for over five minutes once, with `tests/smoke.py` waiting on it.
- One `Documents.Add` took 19.8 s right after a timed-out call; the same call
  took 0.1 s a minute later. Cause not found.
