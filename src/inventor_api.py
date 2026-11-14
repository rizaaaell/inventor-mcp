"""Wrapper around Autodesk Inventor COM API."""

import json
import os
import win32com.client
import pythoncom


# Inventor 2026 enum constants (from type library)
# PartFeatureExtentDirectionEnum
kPositiveExtentDirection = 20993
kNegativeExtentDirection = 20994
kSymmetricExtentDirection = 20995

# PartFeatureOperationEnum
kJoinOperation = 20481
kCutOperation = 20482
kIntersectOperation = 20483
kSurfaceOperation = 20484
kNewBodyOperation = 20485

# DocumentTypeEnum
kPartDocumentObject = 12290

# DimensionOrientationEnum (from Inventor 2026 type library — NOT 40706/40707/40708!)
kHorizontalDim = 19201
kVerticalDim   = 19202
kAlignedDim    = 19203


class InventorConnection:
    def __init__(self):
        self._app = None
        self._pinned = None
        self._pinned_known: set[str] = set()

    @property
    def app(self):
        if self._app is None:
            raise RuntimeError(
                "Not connected to Inventor. Call connect() first."
            )
        return self._app

    def connect(self, visible: bool = True) -> str:
        pythoncom.CoInitialize()
        try:
            self._app = win32com.client.GetActiveObject("Inventor.Application")
            return f"Connected to running Inventor {self._app.SoftwareVersion.DisplayVersion}"
        except Exception:
            pass
        try:
            self._app = win32com.client.Dispatch("Inventor.Application")
            self._app.Visible = visible
            return f"Started Inventor {self._app.SoftwareVersion.DisplayVersion}"
        except Exception as e:
            raise RuntimeError(f"Cannot connect to Inventor: {e}")

    def is_connected(self) -> bool:
        if self._app is None:
            return False
        try:
            _ = self._app.SoftwareVersion
            return True
        except Exception:
            self._app = None
            return False

    # ---------- Document management ----------

    def create_part(self, name: str | None = None, template: str = "metric") -> str:
        import glob

        templates_path = self.app.FileLocations.TemplatesPath

        if template.lower() in ("sheet_metal", "sheetmetal", "sm"):
            # Sheet Metal template (metric mm)
            candidates_patterns = [
                os.path.join(templates_path, "Metric", "Sheet Metal (mm).ipt"),
                os.path.join(templates_path, "**", "Sheet Metal (mm).ipt"),
                os.path.join(templates_path, "Sheet Metal.ipt"),
            ]
            template_file = None
            for pattern in candidates_patterns:
                if "*" in pattern:
                    found = glob.glob(pattern, recursive=True)
                    if found:
                        template_file = found[0]
                        break
                elif os.path.exists(pattern):
                    template_file = pattern
                    break
            if template_file is None:
                raise RuntimeError(f"Cannot find Sheet Metal template in {templates_path}")
        elif template.lower() == "metric":
            # Search for metric template (mm)
            candidates_patterns = [
                os.path.join(templates_path, "Metric", "Standard (mm).ipt"),
                os.path.join(templates_path, "Metric", "Standard.ipt"),
                os.path.join(templates_path, "**", "Standard (mm).ipt"),
            ]
            template_file = None
            for pattern in candidates_patterns:
                if "*" in pattern:
                    found = glob.glob(pattern, recursive=True)
                    if found:
                        template_file = found[0]
                        break
                elif os.path.exists(pattern):
                    template_file = pattern
                    break
            if template_file is None:
                # Fallback: any .ipt template
                fallback = glob.glob(os.path.join(templates_path, "**", "*.ipt"), recursive=True)
                if fallback:
                    template_file = fallback[0]
                else:
                    raise RuntimeError(f"Cannot find metric template in {templates_path}")
        elif template.lower() == "english":
            candidates_patterns = [
                os.path.join(templates_path, "en-US", "Standard.ipt"),
                os.path.join(templates_path, "Standard.ipt"),
                os.path.join(templates_path, "**", "Standard.ipt"),
            ]
            template_file = None
            for pattern in candidates_patterns:
                if "*" in pattern:
                    found = glob.glob(pattern, recursive=True)
                    if found:
                        template_file = found[0]
                        break
                elif os.path.exists(pattern):
                    template_file = pattern
                    break
            if template_file is None:
                raise RuntimeError(f"Cannot find English template in {templates_path}")
        else:
            # template is a direct file path
            template_file = template
            if not os.path.exists(template_file):
                raise RuntimeError(f"Template not found: {template_file}")

        doc = self._add_document(12290, template_file)
        if name:
            try:
                doc.DisplayName = name
            except Exception:
                pass  # DisplayName may be read-only before first save
        self.pin_document(doc)
        return f"Part created: {doc.DisplayName}"

    def _add_document(self, doc_type: int, template_file: str):
        """Documents.Add with dialogs suppressed.
        A template whose styles differ from the style library otherwise opens a
        modal "Style Conflict" dialog that blocks every COM call until clicked."""
        previous = self.app.SilentOperation
        self.app.SilentOperation = True
        try:
            return self.app.Documents.Add(doc_type, template_file, True)
        finally:
            self.app.SilentOperation = previous

    def pin_document(self, doc) -> None:
        """Make doc the target of every tool until a newer document replaces it."""
        self._pinned = doc
        self._pinned_known = {d.InternalName for d in self.app.Documents}

    def release_document(self) -> None:
        """Drop the pin so tools follow Inventor's active document again."""
        self._pinned = None
        self._pinned_known = set()

    def active_document(self):
        """Document the tools act on: the pinned one, even if another tab was clicked.
        A document opened after the pin takes over once it becomes active."""
        doc = self.app.ActiveDocument
        pinned = self._pinned
        if pinned is not None:
            try:
                pinned_id = pinned.InternalName
            except Exception:
                # A closed document raises on any property access.
                self.release_document()
                pinned = None
        if pinned is not None and (doc is None or doc.InternalName != pinned_id):
            if doc is not None and doc.InternalName not in self._pinned_known:
                self.release_document()
            else:
                pinned.Activate()
                doc = pinned
        if doc is None:
            raise RuntimeError("No active document open in Inventor.")
        return doc

    def active_part(self):
        doc = self.active_document()
        if doc.DocumentType != 12290:  # kPartDocumentObject
            raise RuntimeError(
                f"Active document is not a part (type={doc.DocumentType})."
            )
        return doc.ComponentDefinition

    def save_document(self, path: str | None = None) -> str:
        doc = self.active_document()
        if path:
            path = os.path.abspath(path)
            # SaveAs onto a file another open document holds fails with a bare E_INVALIDARG.
            for i in range(1, self.app.Documents.Count + 1):
                other = self.app.Documents.Item(i)
                if (other.InternalName != doc.InternalName and other.FullFileName
                        and os.path.normcase(other.FullFileName) == os.path.normcase(path)):
                    raise RuntimeError(
                        f"{path} is open in Inventor as '{other.DisplayName}'. Close it first "
                        "or save under another name.")
            doc.SaveAs(path, False)
            return f"Saved as: {path}"
        doc.Save()
        return f"Saved: {doc.FullFileName}"

    # Translator add-ins by ClassId; display names changed in 2027 ("Translator: STEP").
    _TRANSLATORS = {
        "STEP": "{90AF7F40-0C01-11D5-8E83-0010B541CD80}",
        "IGES": "{90AF7F44-0C01-11D5-8E83-0010B541CD80}",
        "SAT": "{89162634-02B6-11D5-8E80-0010B541CD80}",
        "STL": "{533E9A98-FC3B-11D4-8E7E-0010B541CD80}",
        "PDF": "{0AC6FD96-2F4D-42CE-8BE0-8AEA580399E4}",
    }

    def _translate(self, doc, format_upper: str, path: str, overrides: dict | None = None) -> None:
        translator = self.app.ApplicationAddIns.ItemById(self._TRANSLATORS[format_upper])
        if not translator.Activated:
            translator.Activate()
        context = self.app.TransientObjects.CreateTranslationContext()
        context.Type = 13059  # kFileBrowseIOMechanism
        options = self.app.TransientObjects.CreateNameValueMap()
        data_medium = self.app.TransientObjects.CreateDataMedium()
        data_medium.FileName = path
        translator.HasSaveCopyAsOptions(doc, context, options)  # fills in the defaults
        for key, value in (overrides or {}).items():
            self._put_indexed(options, "Value", key, value)
        translator.SaveCopyAs(doc, context, options, data_medium)
        if not os.path.exists(path):
            raise RuntimeError(f"{format_upper} translator wrote no file at {path}")

    @staticmethod
    def _put_indexed(obj, prop: str, index, value) -> None:
        """obj.prop(index) = value. Late binding has no syntax for an indexed property put."""
        dispid = obj._oleobj_.GetIDsOfNames(prop)
        obj._oleobj_.Invoke(dispid, 0, pythoncom.DISPATCH_PROPERTYPUT, 0, index, value)

    def export_document(self, path: str, format: str = "STEP") -> str:
        doc = self.active_document()
        path = os.path.abspath(path)
        format_upper = format.upper()
        if format_upper not in ("STEP", "STL", "SAT", "IGES"):
            raise ValueError(f"Unsupported format: {format}. Use STEP, STL, SAT, or IGES.")
        self._translate(doc, format_upper, path)
        return f"Exported to: {path} ({format_upper})"

    # ---------- Sketches ----------

    def create_sketch(
        self,
        plane: str = "XY",
        face_index: int | None = None,
        offset: float = 0,
    ) -> str:
        """Create a sketch on a work plane, a body face, or an OFFSET work plane.

        offset (mm): creates a hidden work plane parallel to 'plane' at this
        distance and sketches on it. Offset direction: positive = along the
        plane's normal (XY→+Z, XZ→+Y, YZ→+X). Essential for features that
        don't start at the origin planes (ribs, bosses at a height).
        """
        comp = self.active_part()

        if face_index is not None:
            # Create sketch on a body face
            body = comp.SurfaceBodies.Item(1)
            if face_index < 1 or face_index > body.Faces.Count:
                raise ValueError(
                    f"face_index={face_index} out of range. Body has {body.Faces.Count} faces."
                )
            face = body.Faces.Item(face_index)
            sketch = comp.Sketches.Add(face)
            return f"Sketch created on face {face_index} (Sketch{comp.Sketches.Count})"

        planes = {
            "XY": comp.WorkPlanes.Item(3),  # XY plane
            "XZ": comp.WorkPlanes.Item(2),  # XZ plane
            "YZ": comp.WorkPlanes.Item(1),  # YZ plane
        }
        wp = planes.get(plane.upper())
        if wp is None:
            raise ValueError(f"Unknown plane: {plane}. Use XY, XZ, or YZ.")

        if offset:
            wp = comp.WorkPlanes.AddByPlaneAndOffset(wp, offset / 10.0)
            wp.Visible = False
            sketch = comp.Sketches.Add(wp)
            return (f"Sketch created on {plane.upper()}{offset:+g}mm offset plane "
                    f"(Sketch{comp.Sketches.Count})")

        sketch = comp.Sketches.Add(wp)
        return f"Sketch created on {plane.upper()} plane (Sketch{comp.Sketches.Count})"

    def _get_sketch(self, sketch_index: int | None = None):
        comp = self.active_part()
        if sketch_index is not None:
            return comp.Sketches.Item(sketch_index)
        return comp.Sketches.Item(comp.Sketches.Count)

    def _tg(self):
        return self.app.TransientGeometry

    def draw_rectangle(
        self,
        x: float = 0, y: float = 0,
        width: float = 100, height: float = 50,
        sketch_index: int | None = None,
    ) -> str:
        sketch = self._get_sketch(sketch_index)
        tg = self._tg()
        # All dimensions in cm (Inventor internal units)
        w = width / 10.0
        h = height / 10.0
        cx = x / 10.0
        cy = y / 10.0
        sketch.SketchLines.AddAsTwoPointRectangle(
            tg.CreatePoint2d(cx - w / 2, cy - h / 2),
            tg.CreatePoint2d(cx + w / 2, cy + h / 2),
        )
        return f"Rectangle {width}x{height}mm at ({x},{y})"

    def draw_circle(
        self,
        x: float = 0, y: float = 0,
        diameter: float = 50,
        sketch_index: int | None = None,
        construction: bool = False,
    ) -> str:
        """Draw a circle with an automatic diameter dimension constraint.
        construction=True draws a reference (non-profile) circle, e.g. bolt PCD.
        """
        sketch = self._get_sketch(sketch_index)
        tg = self._tg()
        r = (diameter / 10.0) / 2.0
        cx = x / 10.0
        cy = y / 10.0
        circle = sketch.SketchCircles.AddByCenterRadius(
            tg.CreatePoint2d(cx, cy), r
        )
        if construction:
            circle.Construction = True

        # Add diameter dimension — text placed just outside the circle
        text_x = cx + r * 0.8
        text_y = cy + r * 0.6
        try:
            sketch.DimensionConstraints.AddDiameter(
                circle, tg.CreatePoint2d(text_x, text_y)
            )
        except Exception:
            pass  # dimension already exists or sketch is consumed

        suffix = " [construction]" if construction else ""
        return f"Circle D={diameter}mm at ({x},{y}){suffix}"

    def draw_line(
        self,
        x1: float = 0, y1: float = 0,
        x2: float = 100, y2: float = 0,
        sketch_index: int | None = None,
        construction: bool = False,
    ) -> str:
        sketch = self._get_sketch(sketch_index)
        tg = self._tg()
        line = sketch.SketchLines.AddByTwoPoints(
            tg.CreatePoint2d(x1 / 10.0, y1 / 10.0),
            tg.CreatePoint2d(x2 / 10.0, y2 / 10.0),
        )
        if construction:
            line.Construction = True
        suffix = " [construction]" if construction else ""
        return f"Line from ({x1},{y1}) to ({x2},{y2})mm{suffix}"

    def draw_polygon(
        self,
        x: float = 0, y: float = 0,
        radius: float = 25,
        sides: int = 6,
        sketch_index: int | None = None,
    ) -> str:
        import math
        sketch = self._get_sketch(sketch_index)
        tg = self._tg()
        r = radius / 10.0
        cx = x / 10.0
        cy = y / 10.0
        points = []
        for i in range(sides):
            angle = 2 * math.pi * i / sides - math.pi / 2
            px = cx + r * math.cos(angle)
            py = cy + r * math.sin(angle)
            points.append(tg.CreatePoint2d(px, py))
        # Draw connected lines — share endpoints for proper profile
        first_line = sketch.SketchLines.AddByTwoPoints(points[0], points[1])
        prev_line = first_line
        for i in range(2, sides):
            prev_line = sketch.SketchLines.AddByTwoPoints(
                prev_line.EndSketchPoint, points[i]
            )
        # Close the polygon
        sketch.SketchLines.AddByTwoPoints(
            prev_line.EndSketchPoint, first_line.StartSketchPoint
        )
        return f"Polygon {sides} sides, R={radius}mm at ({x},{y})"

    def draw_closed_profile(
        self,
        points: list[list[float]],
        sketch_index: int | None = None,
    ) -> str:
        """Draw a closed profile from a list of [x,y] points (mm).
        Lines share endpoints for proper profile recognition by Inventor."""
        sketch = self._get_sketch(sketch_index)
        tg = self._tg()

        if len(points) < 3:
            raise ValueError("Need at least 3 points for a closed profile")

        # First line
        pt1 = tg.CreatePoint2d(points[0][0] / 10.0, points[0][1] / 10.0)
        pt2 = tg.CreatePoint2d(points[1][0] / 10.0, points[1][1] / 10.0)
        first_line = sketch.SketchLines.AddByTwoPoints(pt1, pt2)

        # Subsequent lines — connect to previous endpoint
        prev_line = first_line
        for i in range(2, len(points)):
            next_pt = tg.CreatePoint2d(points[i][0] / 10.0, points[i][1] / 10.0)
            prev_line = sketch.SketchLines.AddByTwoPoints(
                prev_line.EndSketchPoint, next_pt
            )

        # Close the loop — connect last endpoint to first startpoint
        sketch.SketchLines.AddByTwoPoints(
            prev_line.EndSketchPoint, first_line.StartSketchPoint
        )

        return f"Closed profile with {len(points)} points ({len(points)} lines)"

    # ---------- Features ----------

    def extrude(
        self,
        distance: float = 10,
        direction: str = "positive",
        operation: str = "join",
        sketch_index: int | None = None,
        profile_index: int = 1,
        extent_type: str = "distance",
    ) -> str:
        comp = self.active_part()
        sketch = self._get_sketch(sketch_index)
        profile = sketch.Profiles.AddForSolid()

        dir_map = {
            "positive": kPositiveExtentDirection,
            "negative": kNegativeExtentDirection,
            "symmetric": kSymmetricExtentDirection,
        }
        op_map = {
            "join": kJoinOperation,
            "cut": kCutOperation,
            "intersect": kIntersectOperation,
            "surface": kSurfaceOperation,
            "new": kNewBodyOperation,
        }

        direction_enum = dir_map.get(direction.lower(), kPositiveExtentDirection)
        operation_enum = op_map.get(operation.lower(), kJoinOperation)
        before = self._vol_state()

        if extent_type.lower() == "all":
            feature = comp.Features.ExtrudeFeatures.AddByThroughAllExtent(
                profile, direction_enum, operation_enum
            )
            return f"Extrude through-all {direction} ({operation}): {feature.Name}{self._fmt_delta(before)}"
        else:
            dist_cm = distance / 10.0
            feature = comp.Features.ExtrudeFeatures.AddByDistanceExtent(
                profile, dist_cm, direction_enum, operation_enum
            )
            return f"Extrude {distance}mm {direction} ({operation}): {feature.Name}{self._fmt_delta(before)}"

    def revolve(
        self,
        angle: float = 360,
        sketch_index: int | None = None,
        axis: str = "Y",
        operation: str = "join",
        axis_line_index: int | None = None,
    ) -> str:
        """Revolve a sketch profile around an axis.

        axis: "X" / "Y" / "Z"  — use a named WorkAxis (preferred, no construction line needed)
        axis_line_index: sketch line index (legacy); overrides axis when provided.
        """
        import math
        comp = self.active_part()
        sketch = self._get_sketch(sketch_index)
        profile = sketch.Profiles.AddForSolid()

        # Resolve axis entity: named WorkAxis (preferred) or sketch line (legacy)
        _work_axis_map = {"X": 1, "Y": 2, "Z": 3}
        if axis_line_index is not None:
            # Explicit keyword: legacy sketch-line mode
            axis_entity = sketch.SketchLines.Item(axis_line_index)
            axis_label = f"sketch line {axis_line_index}"
        elif isinstance(axis, str) and axis.upper() in _work_axis_map:
            # Named work axis — preferred, no construction line needed
            axis_entity = comp.WorkAxes.Item(_work_axis_map[axis.upper()])
            axis_label = f"{axis.upper()} work axis"
        elif isinstance(axis, int):
            # Backward compat: integer passed positionally from old server.py
            axis_entity = sketch.SketchLines.Item(axis)
            axis_label = f"sketch line {axis}"
        else:
            axis_entity = sketch.SketchLines.Item(1)
            axis_label = "sketch line 1"

        op_map = {
            "join": kJoinOperation,
            "cut": kCutOperation,
            "intersect": kIntersectOperation,
            "new": kNewBodyOperation,
        }
        operation_enum = op_map.get(operation.lower(), kJoinOperation)

        revolve_features = comp.Features.RevolveFeatures
        before = self._vol_state()

        if angle >= 360:
            revolve_features.AddFull(profile, axis_entity, operation_enum)
        else:
            angle_rad = math.radians(angle)
            revolve_features.AddByAngle(
                profile, axis_entity, angle_rad,
                kPositiveExtentDirection, operation_enum
            )

        return f"Revolve {angle}° around {axis_label} ({operation}){self._fmt_delta(before)}"

    def fillet(self, radius: float = 2, edge_indices: list[int] | None = None) -> str:
        comp = self.active_part()
        r_cm = radius / 10.0

        edges_collection = self.app.TransientObjects.CreateEdgeCollection()
        body = comp.SurfaceBodies.Item(1)

        if edge_indices:
            for idx in edge_indices:
                edges_collection.Add(body.Edges.Item(idx))
        else:
            edges_collection.Add(body.Edges.Item(1))

        before = self._vol_state()
        fillet_def = comp.Features.FilletFeatures.CreateFilletDefinition()
        fillet_def.AddConstantRadiusEdgeSet(edges_collection, r_cm)
        comp.Features.FilletFeatures.Add(fillet_def)
        return f"Fillet R={radius}mm on {edges_collection.Count} edge(s){self._fmt_delta(before)}"

    def chamfer(self, distance: float = 2, edge_indices: list[int] | None = None) -> str:
        """Add equal-distance chamfer to edges.
        Inventor 2026 API: ChamferFeatures.AddUsingDistance(EdgeCollection, dist_cm)
        NOT CreateChamferDefinition (removed in 2026).
        Requires EdgeCollection (not ObjectCollection).
        """
        comp = self.active_part()
        d_cm = distance / 10.0

        ec = self.app.TransientObjects.CreateEdgeCollection()
        body = comp.SurfaceBodies.Item(1)

        if edge_indices:
            for idx in edge_indices:
                ec.Add(body.Edges.Item(idx))
        else:
            ec.Add(body.Edges.Item(1))

        before = self._vol_state()
        comp.Features.ChamferFeatures.AddUsingDistance(ec, d_cm)
        return f"Chamfer {distance}mm on {ec.Count} edge(s){self._fmt_delta(before)}"

    # Standard ISO metric coarse thread pitches (mm)
    _METRIC_COARSE_PITCH = {
        1: 0.25, 1.2: 0.25, 1.4: 0.3, 1.6: 0.35, 2: 0.4, 2.5: 0.45,
        3: 0.5, 3.5: 0.6, 4: 0.7, 5: 0.8, 6: 1.0, 8: 1.25, 10: 1.5,
        12: 1.75, 14: 2.0, 16: 2.0, 18: 2.5, 20: 2.5, 22: 2.5, 24: 3.0,
        27: 3.0, 30: 3.5, 33: 3.5, 36: 4.0, 39: 4.0, 42: 4.5, 45: 4.5,
        48: 5.0, 52: 5.0, 56: 5.5, 60: 5.5, 64: 6.0,
    }

    def hole(
        self,
        x: float = 0, y: float = 0,
        diameter: float = 10,
        depth: float = 0,
        tapped: bool = False,
        pitch: float | None = None,
    ) -> str:
        """Create a proper Inventor HoleFeature using native HoleFeatures API.
        depth=0 means through-all (default).
        tapped=True creates a tapped (threaded) hole with ISO Metric profile.
        pitch: thread pitch in mm (auto-selected from standard coarse series if None).
        Uses CreateSketchPlacementDefinition(ObjectCollection_of_SketchPoints) API.
        """
        comp = self.active_part()
        tg = self._tg()
        hf = comp.Features.HoleFeatures
        before = self._vol_state()

        # Create sketch on XY work plane for hole center point
        wp = comp.WorkPlanes.Item(3)  # XY plane
        sketch = comp.Sketches.Add(wp)
        pt = sketch.SketchPoints.Add(tg.CreatePoint2d(x / 10.0, y / 10.0))

        # Create ObjectCollection with the SketchPoint (required by API)
        col = self.app.TransientObjects.CreateObjectCollection()
        col.Add(pt)

        # Create sketch-based placement definition
        placement = hf.CreateSketchPlacementDefinition(col)

        diameter_cm = diameter / 10.0

        # Build second argument: TapInfo for tapped holes, float diameter for drilled holes
        if tapped:
            # Determine pitch (standard coarse if not given)
            if pitch is None:
                dia_int = int(round(diameter))
                pitch = self._METRIC_COARSE_PITCH.get(dia_int)
                if pitch is None:
                    raise ValueError(
                        f"No standard coarse pitch for M{dia_int}. "
                        "Pass pitch= explicitly."
                    )
            # Format designation: "M16x2" (not "M16x2.0")
            dia_int = int(round(diameter))
            pitch_str = str(int(pitch)) if pitch == int(pitch) else str(pitch)
            designation = f"M{dia_int}x{pitch_str}"
            tap_info = hf.CreateTapInfo(
                True,                   # RightHanded
                "ISO Metric profile",   # ThreadType (exact string from thread.xlsx)
                designation,            # ThreadDesignation e.g. "M16x2"
                "6H",                   # Class (standard internal metric)
                True,                   # FullTapDepth
            )
            hole_arg = tap_info
            type_str = f"M{dia_int} tapped (pitch {pitch}mm, 6H)"
        else:
            hole_arg = diameter_cm
            type_str = f"drilled D={diameter}mm"

        if depth <= 0:
            feature = hf.AddDrilledByThroughAllExtent(
                placement, hole_arg, kNegativeExtentDirection
            )
            extent_str = "through-all"
        else:
            depth_cm = depth / 10.0
            feature = hf.AddDrilledByDistanceExtent(
                placement, hole_arg, depth_cm, kNegativeExtentDirection
            )
            extent_str = f"{depth}mm deep"

        # --- Add position dimensions in a separate sketch (after hole creation) ---
        # HoleFeature placement sketch must have ONLY SketchPoints — construction lines
        # cannot be in the same sketch. So we create a dedicated dimension sketch.
        self._add_hole_position_dims(comp, x, y)

        return f"Hole {type_str} {extent_str} at ({x},{y}): {feature.Name}{self._fmt_delta(before)}"

    def _add_hole_position_dims(self, comp, x: float, y: float) -> None:
        """Add a dimension sketch showing the hole center position from origin.
        Uses a separate sketch with construction line(s) to allow AddTwoPointDistance.
        Only adds dimensions if hole is not at origin.
        """
        tg = self._tg()
        x_cm = x / 10.0
        y_cm = y / 10.0

        if abs(x) < 0.01 and abs(y) < 0.01:
            return  # hole at origin — nothing to dimension

        wp = comp.WorkPlanes.Item(3)  # XY plane
        dim_sketch = comp.Sketches.Add(wp)
        dc = dim_sketch.DimensionConstraints

        if abs(y) < 0.01:
            # Hole on X axis — one horizontal construction line
            line = dim_sketch.SketchLines.AddByTwoPoints(
                tg.CreatePoint2d(0.0, 0.0),
                tg.CreatePoint2d(x_cm, 0.0)
            )
            line.Construction = True
            text_pt = tg.CreatePoint2d(x_cm / 2, -1.5)
            dc.AddTwoPointDistance(line.StartSketchPoint, line.EndSketchPoint,
                                   kHorizontalDim, text_pt)
        elif abs(x) < 0.01:
            # Hole on Y axis — one vertical construction line
            line = dim_sketch.SketchLines.AddByTwoPoints(
                tg.CreatePoint2d(0.0, 0.0),
                tg.CreatePoint2d(0.0, y_cm)
            )
            line.Construction = True
            text_pt = tg.CreatePoint2d(-1.5, y_cm / 2)
            dc.AddTwoPointDistance(line.StartSketchPoint, line.EndSketchPoint,
                                   kVerticalDim, text_pt)
        else:
            # Hole at (x, y) — two construction lines: H and V legs
            h_line = dim_sketch.SketchLines.AddByTwoPoints(
                tg.CreatePoint2d(0.0, 0.0),
                tg.CreatePoint2d(x_cm, 0.0)
            )
            h_line.Construction = True
            v_line = dim_sketch.SketchLines.AddByTwoPoints(
                tg.CreatePoint2d(x_cm, 0.0),
                tg.CreatePoint2d(x_cm, y_cm)
            )
            v_line.Construction = True
            # Horizontal dim (X distance from center)
            dc.AddTwoPointDistance(h_line.StartSketchPoint, h_line.EndSketchPoint,
                                   kHorizontalDim, tg.CreatePoint2d(x_cm / 2, -1.5))
            # Vertical dim (Y distance)
            dc.AddTwoPointDistance(v_line.StartSketchPoint, v_line.EndSketchPoint,
                                   kVerticalDim, tg.CreatePoint2d(x_cm + 1.5, y_cm / 2))

    # ---------- Diagnostics / token-saving helpers ----------

    def _vol_state(self):
        """(volume_mm3, faces, edges) of body 1, or None if no body."""
        try:
            comp = self.active_part()
            mp = comp.MassProperties
            body = comp.SurfaceBodies.Item(1)
            return (mp.Volume * 1000, body.Faces.Count, body.Edges.Count)
        except Exception:
            return None

    def _fmt_delta(self, before):
        """Compact ' | V 35271 (−7854) | F7 E16' suffix comparing to 'before' state."""
        after = self._vol_state()
        if not after:
            return ""
        if not before:
            # first feature — no 'before' body existed
            return f" | V {after[0]:.0f} mm³ | F{after[1]} E{after[2]}"
        dv = after[0] - before[0]
        return f" | V {after[0]:.0f} ({dv:+.0f} mm³) | F{after[1]} E{after[2]}"

    def inspect(self) -> dict:
        """Compact one-call snapshot of the active part."""
        doc = self.active_document()
        comp = doc.ComponentDefinition
        info: dict = {"document": doc.DisplayName}
        try:
            body = comp.SurfaceBodies.Item(1)
            rb = body.RangeBox
            mp = comp.MassProperties
            info["volume_mm3"] = round(mp.Volume * 1000)
            info["bbox_mm"] = {
                "x": [round(rb.MinPoint.X * 10, 2), round(rb.MaxPoint.X * 10, 2)],
                "y": [round(rb.MinPoint.Y * 10, 2), round(rb.MaxPoint.Y * 10, 2)],
                "z": [round(rb.MinPoint.Z * 10, 2), round(rb.MaxPoint.Z * 10, 2)],
            }
            info["faces"] = body.Faces.Count
            info["edges"] = body.Edges.Count
        except Exception:
            info["body"] = "none"
        feats = []
        for i in range(1, comp.Features.Count + 1):
            f = comp.Features.Item(i)
            nm = f.Name
            if getattr(f, "Suppressed", False):
                nm += " [suppressed]"
            feats.append(f"[{i}] {nm}")
        info["features"] = feats
        info["sketches"] = [comp.Sketches.Item(i).Name for i in range(1, comp.Sketches.Count + 1)]
        try:
            info["sheet_metal_thickness"] = str(comp.ActiveSheetMetalStyle.Thickness)
        except Exception:
            pass
        return info

    @staticmethod
    def _edge_geometry(edge):
        """(length_mm, (x, y, z) mm, circle_radius_mm or None), length along the curve.
        The point is the curve midpoint, or the center of a full circle."""
        ev = edge.Evaluator
        lo, hi = ev.GetParamExtents()
        length = ev.GetLengthAtParam(lo, hi) * 10
        if edge.GeometryType == 5124:  # kCircleCurve
            g = edge.Geometry
            return length, (g.Center.X * 10, g.Center.Y * 10, g.Center.Z * 10), g.Radius * 10
        _, pt = ev.GetPointAtParam([(lo + hi) / 2], [0.0, 0.0, 0.0])
        return length, tuple(v * 10 for v in pt), None

    def list_edges(self, body_index: int = 1, min_length: float = 0, max_count: int = 60) -> str:
        """Compact edge table, one per line: '[i] L=200.0 mid=(0.0,-225.0,0.8)'
        or, for a full circle, '[i] circle R=20.0 c=(0.0,0.0,10.0) L=125.7'.
        min_length filters out short edges (mm, measured along the curve)."""
        body = self.active_part().SurfaceBodies.Item(body_index)
        lines = []
        for i in range(1, body.Edges.Count + 1):
            try:
                L, (x, y, z), radius = self._edge_geometry(body.Edges.Item(i))
                if L < min_length:
                    continue
                if radius is None:
                    lines.append(f"[{i}] L={L:.1f} mid=({x:.1f},{y:.1f},{z:.1f})")
                else:
                    lines.append(f"[{i}] circle R={radius:.1f} c=({x:.1f},{y:.1f},{z:.1f}) L={L:.1f}")
            except Exception:
                lines.append(f"[{i}] ?")
            if len(lines) >= max_count:
                lines.append(f"... truncated at {max_count}")
                break
        return "\n".join(lines) if lines else "(no edges match)"

    def list_faces(self, body_index: int = 1, min_area: float = 0, max_count: int = 60) -> str:
        """Compact face table: '[i] Plane A=90000 c=(0.0,225.0,12.5)' one per line.
        min_area in mm²."""
        type_names = {5890: "Plane", 5891: "Cyl", 5892: "EllCyl", 5893: "Cone",
                      5894: "EllCone", 5895: "Torus", 5896: "Sphere", 5897: "BSpline"}
        body = self.active_part().SurfaceBodies.Item(body_index)
        lines = []
        for i in range(1, body.Faces.Count + 1):
            try:
                f = body.Faces.Item(i)
                a = f.Evaluator.Area * 100
                if a < min_area:
                    continue
                xs, ys, zs = [], [], []
                for v in range(1, f.Vertices.Count + 1):
                    p = f.Vertices.Item(v).Point
                    xs.append(p.X * 10); ys.append(p.Y * 10); zs.append(p.Z * 10)
                t = type_names.get(f.SurfaceType, str(f.SurfaceType))
                if xs:
                    c = f"c=({sum(xs)/len(xs):.1f},{sum(ys)/len(ys):.1f},{sum(zs)/len(zs):.1f})"
                else:
                    c = "c=(closed)"
                lines.append(f"[{i}] {t} A={a:.0f} {c}")
            except Exception:
                lines.append(f"[{i}] ?")
            if len(lines) >= max_count:
                lines.append(f"... truncated at {max_count}")
                break
        return "\n".join(lines) if lines else "(no faces match)"

    # ---------- Transactions (rollback support) ----------

    def transaction(self, action: str = "begin", name: str = "MCP batch") -> str:
        """begin: start an undo-transaction wrapping subsequent operations.
        commit: finalize. abort: roll back EVERYTHING since begin (one undo unit)."""
        action = action.lower()
        if action == "begin":
            if getattr(self, "_txn", None) is not None:
                return "Transaction already open — commit or abort it first"
            self._txn = self.app.TransactionManager.StartTransaction(
                self.active_document(), name)
            return f"Transaction '{name}' started"
        if action == "commit":
            if getattr(self, "_txn", None) is None:
                return "No open transaction"
            self._txn.End()
            self._txn = None
            return "Transaction committed"
        if action == "abort":
            if getattr(self, "_txn", None) is None:
                return "No open transaction"
            self._txn.Abort()
            self._txn = None
            return "Transaction aborted — all changes since 'begin' rolled back"
        return f"Unknown action '{action}'. Use begin / commit / abort."

    def _plane_face(self, axis: str, value: float, body_index: int = 1, tol: float = 0.1):
        """Largest planar face whose vertices ALL lie at <axis>==value (mm).
        Re-resolve after every feature — face objects/indices go stale."""
        body = self.active_part().SurfaceBodies.Item(body_index)
        best_f, best_a = None, 0
        for i in range(1, body.Faces.Count + 1):
            f = body.Faces.Item(i)
            if f.SurfaceType != 5890:  # plane
                continue
            ok = True
            for v in range(1, f.Vertices.Count + 1):
                p = f.Vertices.Item(v).Point
                c = {"x": p.X, "y": p.Y, "z": p.Z}[axis.lower()] * 10
                if abs(c - value) > tol:
                    ok = False
                    break
            if ok:
                a = f.Evaluator.Area
                if a > best_a:
                    best_a, best_f = a, f
        if best_f is None:
            raise ValueError(f"No planar face at {axis}={value}mm")
        return best_f

    def _face_edge(self, face, axis: str, value: float, tol: float = 0.1):
        """Edge of a face whose BOTH vertices lie at <axis>==value (mm)."""
        for i in range(1, face.Edges.Count + 1):
            e = face.Edges.Item(i)
            sv, ev = e.StartVertex.Point, e.StopVertex.Point
            cs = {"x": sv.X, "y": sv.Y, "z": sv.Z}[axis.lower()] * 10
            ce = {"x": ev.X, "y": ev.Y, "z": ev.Z}[axis.lower()] * 10
            if abs(cs - value) < tol and abs(ce - value) < tol:
                return e
        raise ValueError(f"No edge of face at {axis}={value}mm")

    def hole_linear(
        self,
        face_axis: str, face_value: float,
        ref1_axis: str, ref1_value: float, dist1: float,
        ref2_axis: str, ref2_value: float, dist2: float,
        diameter: float = 5.5,
        depth: float = 0,
        tapped: bool = False,
        pitch: float | None = None,
        cbore_diameter: float = 0,
        cbore_depth: float = 0,
    ) -> str:
        """Hole placed parametrically from two face edges (Linear placement).

        The hole stays attached to the edges — change the part length and the
        hole keeps its 8mm-from-edge distance. This is the preferred way to
        place fastener holes (vs sketch-point placement with absolute coords).

        face_axis/face_value: the planar face to drill into, e.g. ("z", 25) = top.
        ref1/ref2: two edges OF THAT FACE by their constant coordinate,
                   e.g. ("x", -34.5, 8) = 8mm from the left edge.
        depth: 0 = through-all, otherwise mm.
        tapped: ISO metric thread (uses standard coarse pitch unless pitch given).
        cbore_diameter/cbore_depth: >0 adds a counterbore (e.g. 10 and 5.5 for
                   an M5 ISO 4762 socket head cap screw seat).

        Direction is resolved automatically: try positive, check that material
        was actually removed (volume), flip to negative if not.
        """
        comp = self.active_part()
        tg = self._tg()
        hf = comp.Features.HoleFeatures
        doc = self.active_document()

        # Build the hole argument (diameter or TapInfo)
        if tapped:
            if pitch is None:
                dia_int = int(round(diameter))
                pitch = self._METRIC_COARSE_PITCH.get(dia_int)
                if pitch is None:
                    raise ValueError(f"No standard coarse pitch for M{dia_int}")
            dia_int = int(round(diameter))
            pitch_str = str(int(pitch)) if pitch == int(pitch) else str(pitch)
            hole_arg = hf.CreateTapInfo(
                True, "ISO Metric profile", f"M{dia_int}x{pitch_str}", "6H", True)
            type_str = f"M{dia_int} tapped"
        else:
            hole_arg = diameter / 10.0
            type_str = f"D={diameter}mm"

        v0 = comp.MassProperties.Volume * 1000

        for direction in (kPositiveExtentDirection, kNegativeExtentDirection):
            # Re-resolve topology fresh each attempt
            face = self._plane_face(face_axis, face_value)
            e1 = self._face_edge(face, ref1_axis, ref1_value)
            e2 = self._face_edge(face, ref2_axis, ref2_value)

            # BiasPoint: 3D point near the intended hole location. Compute by
            # stepping from each reference edge toward the face centroid.
            xs, ys, zs = [], [], []
            for v in range(1, face.Vertices.Count + 1):
                p = face.Vertices.Item(v).Point
                xs.append(p.X * 10); ys.append(p.Y * 10); zs.append(p.Z * 10)
            centroid = {"x": sum(xs)/len(xs), "y": sum(ys)/len(ys), "z": sum(zs)/len(zs)}
            coords = dict(centroid)
            coords[face_axis.lower()] = face_value
            sgn1 = 1 if centroid[ref1_axis.lower()] >= ref1_value else -1
            coords[ref1_axis.lower()] = ref1_value + sgn1 * dist1
            sgn2 = 1 if centroid[ref2_axis.lower()] >= ref2_value else -1
            coords[ref2_axis.lower()] = ref2_value + sgn2 * dist2
            bias = tg.CreatePoint(coords["x"] / 10, coords["y"] / 10, coords["z"] / 10)

            placement = hf.CreateLinearPlacementDefinition(
                face, e1, dist1 / 10.0, e2, dist2 / 10.0, bias)

            if cbore_diameter > 0:
                d_cm = depth / 10.0 if depth > 0 else 10.0  # cbore needs finite depth
                feature = hf.AddCBoreByDistanceExtent(
                    placement, hole_arg, d_cm, direction,
                    cbore_diameter / 10.0, cbore_depth / 10.0)
                extent_str = f"{depth}mm deep, cbore Ø{cbore_diameter}x{cbore_depth}"
            elif depth > 0:
                feature = hf.AddDrilledByDistanceExtent(
                    placement, hole_arg, depth / 10.0, direction)
                extent_str = f"{depth}mm deep"
            else:
                feature = hf.AddDrilledByThroughAllExtent(
                    placement, hole_arg, direction)
                extent_str = "through-all"

            doc.Update()
            v1 = comp.MassProperties.Volume * 1000
            if v1 < v0 - 1:  # material removed — direction correct
                return (f"Hole {type_str} {extent_str} on {face_axis}={face_value} "
                        f"({dist1}mm from {ref1_axis}={ref1_value}, "
                        f"{dist2}mm from {ref2_axis}={ref2_value}): {feature.Name}"
                        f" | V {v1:.0f} ({v1-v0:+.0f} mm³)")
            feature.Delete()
            doc.Update()

        raise RuntimeError("Hole removed no material in either direction — check placement")

    def circular_pattern(
        self,
        feature_index: int,
        count: int = 8,
        angle: float = 360,
        axis: str = "Z",
    ) -> str:
        """Create a circular pattern of a feature around a work axis.
        Distributes 'count' instances evenly within 'angle' degrees.
        """
        import math
        comp = self.active_part()
        cpf = comp.Features.CircularPatternFeatures

        # Get the feature to pattern
        feature = comp.Features.Item(feature_index)

        feat_col = self.app.TransientObjects.CreateObjectCollection()
        feat_col.Add(feature)

        # Work axis selection (X=1, Y=2, Z=3)
        axis_map = {"X": 1, "Y": 2, "Z": 3}
        axis_index = axis_map.get(axis.upper(), 3)
        axis_obj = comp.WorkAxes.Item(axis_index)

        angle_rad = math.radians(angle)

        pattern = cpf.Add(
            feat_col,    # ParentFeatures — ObjectCollection
            axis_obj,    # AxisEntity — WorkAxis
            True,        # NaturalAxisDirection
            count,       # Count
            angle_rad,   # Angle (radians, total span)
            True,        # FitWithinAngle — distribute evenly within angle
            47363,       # ComputeType = kOptimizedCompute (default)
        )

        return (
            f"Circular pattern: {count}x '{feature.Name}' "
            f"around {axis.upper()}-axis, {angle} deg: {pattern.Name}"
        )

    # ---------- Parameters ----------

    def get_parameters(self) -> list[dict]:
        doc = self.active_document()
        params = doc.ComponentDefinition.Parameters
        result = []
        for i in range(1, params.Count + 1):
            p = params.Item(i)
            try:
                result.append({
                    "name": p.Name,
                    "value": p.Value,
                    "expression": p.Expression,
                    "unit": p.Units if hasattr(p, "Units") else "",
                })
            except Exception:
                pass
        return result

    def set_parameter(self, name: str, expression: str) -> str:
        doc = self.active_document()
        params = doc.ComponentDefinition.Parameters
        for i in range(1, params.Count + 1):
            p = params.Item(i)
            if p.Name.lower() == name.lower():
                p.Expression = expression
                doc.Update()
                return f"Parameter '{name}' set to '{expression}' (value={p.Value})"
        raise ValueError(f"Parameter '{name}' not found.")

    def add_parameter(self, name: str, expression: str, units: str = "mm") -> str:
        doc = self.active_document()
        params = doc.ComponentDefinition.Parameters.UserParameters
        params.AddByExpression(name, expression, units)
        doc.Update()
        return f"User parameter '{name}' = '{expression}' ({units}) added"

    # ---------- Query ----------

    def get_document_info(self) -> dict:
        doc = self.active_document()
        comp = doc.ComponentDefinition
        info = {
            "name": doc.DisplayName,
            "full_path": doc.FullFileName,
            "type": str(doc.DocumentType),
            "sketches_count": comp.Sketches.Count,
            "features_count": comp.Features.Count if hasattr(comp.Features, "Count") else 0,
            "bodies_count": comp.SurfaceBodies.Count,
        }
        if comp.SurfaceBodies.Count > 0:
            body = comp.SurfaceBodies.Item(1)
            info["edges_count"] = body.Edges.Count
            info["faces_count"] = body.Faces.Count
        return info

    def list_features(self) -> list[dict]:
        comp = self.active_part()
        result = []
        for i in range(1, comp.Features.Count + 1):
            f = comp.Features.Item(i)
            result.append({
                "index": i,
                "name": f.Name,
                "type": str(f.Type),
                "suppressed": f.Suppressed if hasattr(f, "Suppressed") else False,
            })
        return result

    def delete_feature(self, indices: list[int]) -> str:
        """Delete features by index. Always deletes in reverse order to avoid index shifting."""
        comp = self.active_part()
        total = comp.Features.Count
        for idx in sorted(indices, reverse=True):
            if idx < 1 or idx > total:
                raise ValueError(f"Feature index {idx} out of range (1–{total})")
            name = comp.Features.Item(idx).Name
            comp.Features.Item(idx).Delete()
            total -= 1
        deleted = sorted(indices)
        return f"Deleted {len(indices)} feature(s): indices {deleted}"

    def suppress_feature(self, indices: list[int], suppressed: bool = True) -> str:
        """Suppress or unsuppress features by index."""
        comp = self.active_part()
        names = []
        for idx in indices:
            f = comp.Features.Item(idx)
            f.Suppressed = suppressed
            names.append(f.Name)
        state = "Suppressed" if suppressed else "Unsuppressed"
        return f"{state}: {', '.join(names)}"

    # ---------- Sheet Metal Features ----------

    def set_sheet_metal_thickness(self, thickness_mm: float) -> str:
        """Set the thickness of the active sheet metal style. Inventor 2026.
        Uses local decimal (comma) — required by Inventor for European locales.
        """
        comp = self.active_part()
        style = comp.ActiveSheetMetalStyle
        # Try comma decimal first (European), fall back to dot
        try:
            style.Thickness = f"{thickness_mm:.3f}".replace(".", ",") + " mm"
        except Exception:
            style.Thickness = f"{thickness_mm:.3f} mm"
        return f"Sheet metal thickness set to {thickness_mm}mm (style: {style.Name})"

    def sheet_metal_face(self, sketch_index: int | None = None) -> str:
        """Create a base sheet-metal Face from a closed sketch profile.
        Equivalent of the 'Face' command in Inventor Sheet Metal UI.
        Uses the active sheet metal style's thickness automatically.
        """
        comp = self.active_part()
        sketch = self._get_sketch(sketch_index)
        profile = sketch.Profiles.AddForSolid()
        ff = comp.Features.FaceFeatures
        before = self._vol_state()
        fdef = ff.CreateFaceFeatureDefinition(profile)
        feat = ff.Add(fdef)
        return f"Sheet metal face: {feat.Name}{self._fmt_delta(before)}"

    def flange(
        self,
        edge_indices: list[int],
        distance: float = 25,
        angle: float = 90,
        body_index: int = 1,
    ) -> str:
        """Add a Sheet Metal Flange to one or more edges. Inventor 2026.

        distance: flange height in mm (default 25mm = Inventor's own default)
        angle: bend angle in degrees, default 90° (perpendicular)
        edge_indices: 1-based indices into the body's Edges collection

        IMPORTANT (Inventor 2026 sheet metal quirk):
          - CreateFlangeDefinition(Edges, AngleRad, Distance) ignores the Distance arg.
          - The resulting flange always defaults to height 25mm regardless of what you pass.
          - We work around by editing the resulting feature's parameter:
              feat.Definition.HeightExtent.Distance.Expression = "<distance> mm"
          - The Distance is a Parameter (d15-ish name) — changing its Expression
            re-evaluates the feature correctly.
          - Angle must be in RADIANS (Inventor multiplies by 180/π for display).
            Passing 90 → 5156°. Always convert via math.radians().

        Measurement default = "From Outer Intersection" (HeightDatumType=75521).
        With this datum the Distance value EQUALS the visible perpendicular height
        of the flange — material thickness is NOT subtracted. So distance=450 gives
        a body that reaches Z=450 (when the flange goes upward from a Z=0 dno).
        """
        import math
        comp = self.active_part()
        body = comp.SurfaceBodies.Item(body_index)
        ec = self.app.TransientObjects.CreateEdgeCollection()
        for idx in edge_indices:
            ec.Add(body.Edges.Item(idx))

        flf = comp.Features.FlangeFeatures
        angle_rad = math.radians(angle)
        before = self._vol_state()
        # Distance arg is ignored by Inventor — we set it explicitly after Add
        fdef = flf.CreateFlangeDefinition(ec, angle_rad, 2.5)
        feat = flf.Add(fdef)
        # Set actual distance via the Parameter
        feat.Definition.HeightExtent.Distance.Expression = f"{distance} mm"
        # Update so subsequent feature/edge operations see correct geometry
        self.active_document().Update()
        return f"Flange {distance}mm @ {angle}° on {ec.Count} edge(s): {feat.Name}{self._fmt_delta(before)}"

    def sheet_metal_cut(
        self,
        sketch_index: int | None = None,
        cut_across_bends: bool = False,
    ) -> str:
        """Cut through the sheet using a sketch profile. Sheet Metal Cut.
        Default: cut perpendicular to the face (through thickness).
        cut_across_bends: if True, cut wraps around bends (unfolds first).
        """
        comp = self.active_part()
        sketch = self._get_sketch(sketch_index)
        profile = sketch.Profiles.AddForSolid()

        cf = comp.Features.CutFeatures
        before = self._vol_state()
        cdef = cf.CreateCutDefinition(profile)
        # Default extent = through thickness (kThroughAllExtent style)
        feat = cf.Add(cdef)
        return f"Sheet metal cut: {feat.Name}{self._fmt_delta(before)}"

    def find_edge(
        self,
        body_index: int = 1,
        x: float | None = None,
        y: float | None = None,
        z: float | None = None,
        tolerance: float = 0.1,
    ) -> int:
        """Locate a body edge by its midpoint coordinates (mm). Returns 1-based index.
        Pass any subset of x/y/z — None values are not constrained.
        The midpoint is taken along the curve; a full circle matches by its center.
        """
        comp = self.active_part()
        body = comp.SurfaceBodies.Item(body_index)
        for i in range(1, body.Edges.Count + 1):
            _, (mx, my, mz), _ = self._edge_geometry(body.Edges.Item(i))
            if x is not None and abs(mx - x) > tolerance: continue
            if y is not None and abs(my - y) > tolerance: continue
            if z is not None and abs(mz - z) > tolerance: continue
            return i
        criteria = ", ".join(
            f"{k}={v}" for k, v in [("x", x), ("y", y), ("z", z)] if v is not None
        )
        raise ValueError(f"No edge found matching midpoint ({criteria}) tol={tolerance}mm")

    def find_face(
        self,
        body_index: int = 1,
        x: float | None = None,
        y: float | None = None,
        z: float | None = None,
        min_area: float = 100,
        surface_type: int = 5890,
        tolerance: float = 0.5,
    ) -> int:
        """Locate a body face by its centroid coordinates (mm). Returns 1-based index.

        Useful for: finding a panel face to sketch on for sheet metal Cut.
        Centroid is computed as the average of the face's vertices.

        surface_type: 5890=Plane (default), 5891=Cylinder, 5893=Cone, 5895=Torus, 5896=Sphere
        min_area: filter out small auxiliary faces (mm²)
        tolerance: how close the centroid must be (mm)
        """
        comp = self.active_part()
        body = comp.SurfaceBodies.Item(body_index)
        for i in range(1, body.Faces.Count + 1):
            f = body.Faces.Item(i)
            if surface_type is not None and f.SurfaceType != surface_type: continue
            try:
                xs, ys, zs = [], [], []
                for vi in range(1, f.Vertices.Count + 1):
                    v = f.Vertices.Item(vi)
                    xs.append(v.Point.X * 10)
                    ys.append(v.Point.Y * 10)
                    zs.append(v.Point.Z * 10)
                if not xs: continue
                cx = sum(xs) / len(xs)
                cy = sum(ys) / len(ys)
                cz = sum(zs) / len(zs)
                area_mm2 = f.Evaluator.Area * 100
                if area_mm2 < min_area: continue
                if x is not None and abs(cx - x) > tolerance: continue
                if y is not None and abs(cy - y) > tolerance: continue
                if z is not None and abs(cz - z) > tolerance: continue
                return i
            except Exception:
                continue
        criteria = ", ".join(
            f"{k}={v}" for k, v in [("x", x), ("y", y), ("z", z)] if v is not None
        )
        raise ValueError(f"No face matching centroid ({criteria}) area≥{min_area} tol={tolerance}mm")

    # ---------- Drawings ----------
    # Sheet coordinates are mm from the sheet's bottom-left corner. Points inside a
    # view are mm in model units from the view center, x right and y up on the sheet.

    # Inventor's own ISO template. Project templates from older releases make
    # Documents.Add fail until they are opened and saved once in 2027.
    DRAWING_TEMPLATE = (r"C:\Users\Public\Documents\Autodesk\Inventor {year}"
                        r"\Templates\en-US\Metric\ISO.idw")
    _SHEET_SIZES = {"A0": 9993, "A1": 9994, "A2": 9995, "A3": 9996, "A4": 9997}
    _VIEW_ORIENTATIONS = {
        "front": 10764, "top": 10754, "right": 10755, "back": 10756, "bottom": 10757,
        "left": 10758, "iso_top_right": 10759, "iso_top_left": 10760,
        "iso_bottom_right": 10761, "iso_bottom_left": 10762,
    }
    _VIEW_STYLES = {"hidden": 32257, "visible": 32258, "shaded": 32259,
                    "from_base": 32260, "shaded_hidden": 32261}
    _TITLE_FIELDS = {
        "title": ("Summary Information", "Title"),
        "subject": ("Summary Information", "Subject"),
        "author": ("Summary Information", "Author"),
        "revision": ("Summary Information", "Revision Number"),
        "company": ("Document Summary Information", "Company"),
        "part_number": ("Design Tracking Properties", "Part Number"),
        "description": ("Design Tracking Properties", "Description"),
        "designer": ("Design Tracking Properties", "Designer"),
        "checked_by": ("Design Tracking Properties", "Checked By"),
        "approved_by": ("Design Tracking Properties", "Engr Approved By"),
    }

    def active_drawing(self):
        doc = self.active_document()
        if doc.DocumentType != 12292:  # kDrawingDocumentObject
            raise RuntimeError(f"Active document is not a drawing (type={doc.DocumentType}).")
        return doc

    def create_drawing(self, template: str = "iso", sheet_size: str = "A3") -> str:
        if template.lower() == "iso":
            year = str(self.app.SoftwareVersion.DisplayVersion).split(".")[0]
            template = self.DRAWING_TEMPLATE.format(year=year)
        if not os.path.exists(template):
            raise RuntimeError(f"Drawing template not found: {template}")
        try:
            doc = self._add_document(12292, template)
        except Exception as exc:
            raise RuntimeError(
                f"Inventor refused template {template} ({exc}). A template from an older "
                "release has to be opened and saved once in this version first.") from exc
        sheet = doc.ActiveSheet
        if sheet_size:
            size = self._SHEET_SIZES.get(sheet_size.upper())
            if size is None:
                raise ValueError(f"Unknown sheet size {sheet_size}. Use {', '.join(self._SHEET_SIZES)}.")
            sheet.Size = size
        self.pin_document(doc)
        std = doc.StylesManager.ActiveStandardStyle
        angle = "first" if std.FirstAngleProjection else "third"
        return (f"Drawing created: {doc.DisplayName}, sheet {sheet.Width * 10:.0f}x"
                f"{sheet.Height * 10:.0f} mm, {std.Name}, {angle} angle projection")

    @staticmethod
    def _rect(obj):
        r = obj.RangeBox
        return (r.MinPoint.X * 10, r.MinPoint.Y * 10, r.MaxPoint.X * 10, r.MaxPoint.Y * 10)

    @staticmethod
    def _view_rect(view):
        return (view.Left * 10, (view.Top - view.Height) * 10,
                (view.Left + view.Width) * 10, view.Top * 10)

    @staticmethod
    def _fmt_rect(r):
        return f"x {r[0]:.1f}..{r[2]:.1f} y {r[1]:.1f}..{r[3]:.1f} mm"

    @staticmethod
    def _overlap(a, b, gap: float = 0.0):
        return a[0] < b[2] + gap and b[0] < a[2] + gap and a[1] < b[3] + gap and b[1] < a[3] + gap

    def _drawing_area(self, sheet):
        try:
            return self._rect(sheet.Border)
        except Exception:
            return (0.0, 0.0, sheet.Width * 10, sheet.Height * 10)

    def _sheet_point(self, x: float, y: float):
        return self._tg().CreatePoint2d(x / 10.0, y / 10.0)

    def _view_point(self, view, x: float, y: float):
        """Sheet point (cm) of a point given in model mm from the view center."""
        c, s = view.Center, view.Scale
        return self._tg().CreatePoint2d(c.X + x * s / 10.0, c.Y + y * s / 10.0)

    def _view(self, name: str):
        views = self.active_drawing().ActiveSheet.DrawingViews
        names = []
        for i in range(1, views.Count + 1):
            v = views.Item(i)
            if v.Name.lower() == name.lower():
                return v
            names.append(v.Name)
        raise ValueError(f"No view named {name!r}. Views on this sheet: {names}")

    def _place_check(self, sheet, view):
        """Delete and reject a new view that leaves the border or overlaps something."""
        rect = self._view_rect(view)
        area = self._drawing_area(sheet)
        problems = []
        if rect[0] < area[0] or rect[1] < area[1] or rect[2] > area[2] or rect[3] > area[3]:
            problems.append(f"outside the border ({self._fmt_rect(area)})")
        if sheet.TitleBlock is not None and self._overlap(rect, self._rect(sheet.TitleBlock)):
            problems.append(f"overlaps the title block ({self._fmt_rect(self._rect(sheet.TitleBlock))})")
        views = sheet.DrawingViews
        for i in range(1, views.Count + 1):
            other = views.Item(i)
            if other.Name != view.Name and self._overlap(rect, self._view_rect(other)):
                problems.append(f"overlaps view {other.Name} ({self._fmt_rect(self._view_rect(other))})")
        if problems:
            view.Delete()
            raise ValueError(f"View would sit at {self._fmt_rect(rect)}: {'; '.join(problems)}. "
                             "Move it or change the scale.")
        return rect

    def _open_model(self, model_path: str):
        path = os.path.abspath(model_path)
        for i in range(1, self.app.Documents.Count + 1):
            d = self.app.Documents.Item(i)
            if d.FullFileName and os.path.normcase(d.FullFileName) == os.path.normcase(path):
                return d
        if not os.path.exists(path):
            raise RuntimeError(f"Model not found: {path}")
        return self.app.Documents.Open(path, False)

    def _style(self, style: str) -> int:
        value = self._VIEW_STYLES.get(style.lower())
        if value is None:
            raise ValueError(f"Unknown view style {style}. Use {', '.join(self._VIEW_STYLES)}.")
        return value

    def add_base_view(self, model_path: str, x: float, y: float, scale: float = 1.0,
                      orientation: str = "front", style: str = "visible") -> str:
        sheet = self.active_drawing().ActiveSheet
        orient = self._VIEW_ORIENTATIONS.get(orientation.lower())
        if orient is None:
            raise ValueError(f"Unknown orientation {orientation}. Use {', '.join(self._VIEW_ORIENTATIONS)}.")
        model = self._open_model(model_path)
        view = sheet.DrawingViews.AddBaseView(
            model, self._sheet_point(x, y), scale, orient, self._style(style))
        rect = self._place_check(sheet, view)
        return f"Base view {view.Name}: {orientation}, scale {scale:g}, {self._fmt_rect(rect)}"

    def add_projected_view(self, parent: str, x: float, y: float, style: str = "from_base") -> str:
        sheet = self.active_drawing().ActiveSheet
        view = sheet.DrawingViews.AddProjectedView(
            self._view(parent), self._sheet_point(x, y), self._style(style))
        rect = self._place_check(sheet, view)
        return f"Projected view {view.Name} from {parent}: {self._fmt_rect(rect)}"

    def add_section_view(self, parent: str, x1: float, y1: float, x2: float, y2: float,
                         x: float, y: float, label: str = "A", style: str = "from_base") -> str:
        """Section line from (x1, y1) to (x2, y2) in the parent view, view placed at (x, y)."""
        sheet = self.active_drawing().ActiveSheet
        parent_view = self._view(parent)
        sketch = parent_view.Sketches.Add()
        sketch.Edit()
        try:
            p1 = sketch.SheetToSketchSpace(self._view_point(parent_view, x1, y1))
            p2 = sketch.SheetToSketchSpace(self._view_point(parent_view, x2, y2))
            sketch.SketchLines.AddByTwoPoints(p1, p2)
        finally:
            sketch.ExitEdit()
        try:
            view = sheet.DrawingViews.AddSectionView(
                parent_view, sketch, self._sheet_point(x, y), self._style(style), None, True, label)
            rect = self._place_check(sheet, view)
        except Exception:
            try:
                sketch.Delete()
            except Exception:
                pass
            raise
        return f"Section view {view.Name} from {parent}: {self._fmt_rect(rect)}"

    def add_detail_view(self, parent: str, cx: float, cy: float, radius: float,
                        x: float, y: float, scale: float = 2.0, label: str = "B",
                        style: str = "from_base") -> str:
        """Circular detail of the parent around (cx, cy) with the given radius (model mm)."""
        sheet = self.active_drawing().ActiveSheet
        parent_view = self._view(parent)
        view = sheet.DrawingViews.AddDetailView(
            parent_view, self._sheet_point(x, y), self._style(style), True,
            self._view_point(parent_view, cx, cy), radius * parent_view.Scale / 10.0,
            None, scale, True, label)
        rect = self._place_check(sheet, view)
        return f"Detail view {view.Name} from {parent}: scale {scale:g}, {self._fmt_rect(rect)}"

    def _annotation_boxes(self, sheet):
        """View labels, plus estimated boxes for section line and detail fence labels.

        The API gives no extent for the "A / .A6" label at each section line end or the
        label above a detail circle, so those are boxes sized from the ISO text height.
        """
        boxes = []
        views = sheet.DrawingViews
        for i in range(1, views.Count + 1):
            v = views.Item(i)
            if v.ShowLabel:
                try:
                    boxes.append((f"label of {v.Name}", self._rect(v.Label)))
                except Exception:
                    pass
            try:
                lines = v.SectionLineSketch.SketchLines  # only section views have one
                sk = v.SectionLineSketch
                for j in range(1, lines.Count + 1):
                    for end in (lines.Item(j).StartSketchPoint, lines.Item(j).EndSketchPoint):
                        p = sk.SketchToSheetSpace(end.Geometry)
                        x, y = p.X * 10, p.Y * 10
                        boxes.append((f"section line label {v.Name}", (x - 5, y - 10, x + 40, y + 10)))
            except Exception:
                pass
            try:
                c, r = v.FenceCenter, v.FenceRadius  # only circular detail views
                x, y, r = c.X * 10, c.Y * 10, r * 10
                boxes.append((f"detail fence label {v.Name}", (x - r - 10, y + r, x + r + 10, y + r + 12)))
            except Exception:
                pass
        return boxes

    def _dimension_boxes(self, sheet):
        boxes = []
        dims = sheet.DrawingDimensions.GeneralDimensions
        for i in range(1, dims.Count + 1):
            d = dims.Item(i)
            try:
                boxes.append((f"dimension {d.Text.Text}", self._rect(d.Text)))
            except Exception:
                pass
        return boxes

    def _text_boxes(self, sheet):
        return self._dimension_boxes(sheet) + self._annotation_boxes(sheet)

    def _clashes(self, boxes):
        # Two estimated boxes of the same section line or fence are one label, not a clash.
        return [(boxes[i][0], boxes[j][0])
                for i in range(len(boxes)) for j in range(i + 1, len(boxes))
                if boxes[i][0] != boxes[j][0] and self._overlap(boxes[i][1], boxes[j][1])]

    def _untangle(self, dims, view, obstacles=(), step_mm: float = 3.0, max_steps: int = 80) -> int:
        """Push dimension texts apart, and off the given obstacle boxes (mm), until they clear.
        A text that hits another dimension moves away from the view center; one that hits
        an obstacle moves away from the obstacle's center."""
        tg = self._tg()
        c = view.Center
        moves = 0
        for _ in range(max_steps):
            target, away = None, None
            for i, d in enumerate(dims):
                r = self._rect(d.Text)
                for box in obstacles:
                    if self._overlap(r, box, gap=1.0):
                        target, away = d, ((box[0] + box[2]) / 20, (box[1] + box[3]) / 20)
                        break
                if target is None:
                    for other in dims[i + 1:]:
                        if self._overlap(r, self._rect(other.Text), gap=1.0):
                            target, away = other, (c.X, c.Y)
                            break
                if target is not None:
                    break
            if target is None:
                return moves
            o = target.Text.Origin
            dx, dy = o.X - away[0], o.Y - away[1]
            n = (dx * dx + dy * dy) ** 0.5 or 1.0
            target.Text.Origin = tg.CreatePoint2d(o.X + step_mm / 10 * dx / n, o.Y + step_mm / 10 * dy / n)
            moves += 1
        return moves

    def retrieve_dimensions(self, view: str) -> str:
        sheet = self.active_drawing().ActiveSheet
        v = self._view(view)
        dims = sheet.DrawingDimensions.GeneralDimensions
        before = dims.Count
        retrievable = dims.GetRetrievableDimensions(v)
        if retrievable is None or retrievable.Count == 0:
            return f"No retrievable model dimensions in view {v.Name}"
        dims.Retrieve(v, retrievable)
        new = [dims.Item(i) for i in range(before + 1, dims.Count + 1)]
        if new:
            col = self.app.TransientObjects.CreateObjectCollection()
            for d in new:
                col.Add(d)
            try:
                sheet.DrawingDimensions.Arrange(col)
            except Exception:
                pass  # Arrange rejects some dimension mixes; _untangle still runs
        obstacles = [box for _, box in self._annotation_boxes(sheet)]
        moved = self._untangle(new, v, obstacles)
        clashes = self._clashes(self._text_boxes(sheet))
        values = ", ".join(d.Text.Text for d in new)
        return (f"Retrieved {len(new)} dimension(s) in {v.Name}: {values}; "
                f"{moved} text move(s) to clear overlaps; remaining text overlaps: {clashes or 'none'}")

    def add_centerlines(self, view: str) -> str:
        sheet = self.active_drawing().ActiveSheet
        v = self._view(view)
        lines, marks = sheet.Centerlines.Count, sheet.Centermarks.Count
        settings = v.GetAutomatedCenterlineSettings()
        for flag in ("ApplyToHoles", "ApplyToCylinders", "ApplyToCircularPatterns",
                     "ApplyToRevolutions", "ProjectionNormalAxis", "ProjectionParallelAxis"):
            setattr(settings, flag, True)
        v.SetAutomatedCenterlineSettings(settings)
        return (f"Automated centerlines on {v.Name}: +{sheet.Centerlines.Count - lines} centerline(s), "
                f"+{sheet.Centermarks.Count - marks} centermark(s)")

    def _nearest_curve(self, view, x: float, y: float, circular: bool = False):
        """Drawing curve of a view closest to a point given in model mm from the view center."""
        p = self._view_point(view, x, y)
        best, best_d = None, None
        curves = view.DrawingCurves  # property get; calling it fails under late binding
        for i in range(1, curves.Count + 1):
            curve = curves.Item(i)
            segments = curve.Segments
            for j in range(1, segments.Count + 1):
                g = segments.Item(j).Geometry
                try:
                    center, radius = g.Center, g.Radius
                    d = abs(((p.X - center.X) ** 2 + (p.Y - center.Y) ** 2) ** 0.5 - radius)
                    is_circle = True
                except Exception:
                    a, b = g.StartPoint, g.EndPoint
                    vx, vy = b.X - a.X, b.Y - a.Y
                    t = max(0.0, min(1.0, ((p.X - a.X) * vx + (p.Y - a.Y) * vy) / ((vx * vx + vy * vy) or 1e-12)))
                    d = ((p.X - a.X - t * vx) ** 2 + (p.Y - a.Y - t * vy) ** 2) ** 0.5
                    is_circle = False
                if circular and not is_circle:
                    continue
                if best_d is None or d < best_d:
                    best, best_d = curve, d
        if best is None:
            raise ValueError(f"No {'circular ' if circular else ''}curve in view {view.Name}")
        return best, best_d * 10 / view.Scale

    def add_dimension(self, view: str, kind: str, x1: float, y1: float,
                      x2: float | None = None, y2: float | None = None,
                      text_x: float = 0, text_y: float = 0) -> str:
        """kind: diameter / radius (curve nearest x1,y1) or horizontal / vertical / aligned
        (between the curves nearest x1,y1 and x2,y2). All points in model mm from the view center."""
        sheet = self.active_drawing().ActiveSheet
        v = self._view(view)
        dims = sheet.DrawingDimensions.GeneralDimensions
        text = self._view_point(v, text_x, text_y)
        kind = kind.lower()
        if kind in ("diameter", "radius"):
            curve, miss = self._nearest_curve(v, x1, y1, circular=True)
            intent = sheet.CreateGeometryIntent(curve)
            dim = dims.AddDiameter(text, intent) if kind == "diameter" else dims.AddRadius(text, intent)
        elif kind in ("horizontal", "vertical", "aligned"):
            if x2 is None or y2 is None:
                raise ValueError(f"A {kind} dimension needs x2 and y2")
            c1, m1 = self._nearest_curve(v, x1, y1)
            c2, m2 = self._nearest_curve(v, x2, y2)
            miss = max(m1, m2)
            dim_type = {"aligned": 60161, "horizontal": 60162, "vertical": 60163}[kind]
            dim = dims.AddLinear(text, sheet.CreateGeometryIntent(c1), sheet.CreateGeometryIntent(c2), dim_type)
        else:
            raise ValueError("kind must be diameter, radius, horizontal, vertical or aligned")
        clashes = [c for c in self._clashes(self._text_boxes(sheet)) if f"dimension {dim.Text.Text}" in c]
        return (f"{kind.capitalize()} dimension {dim.Text.Text} in {v.Name} "
                f"(picked curve{'s' if kind not in ('diameter', 'radius') else ''} within {miss:.1f} mm); "
                f"text overlaps: {clashes or 'none'}")

    def set_title_block(self, fields: dict) -> str:
        """Write iProperties of the drawing and return what the title block now shows."""
        doc = self.active_drawing()
        unknown = [k for k in fields if k.lower() not in self._TITLE_FIELDS]
        if unknown:
            raise ValueError(f"Unknown title block field(s) {unknown}. Use {', '.join(self._TITLE_FIELDS)}.")
        props = doc.PropertySets
        for key, value in fields.items():
            set_name, prop = self._TITLE_FIELDS[key.lower()]
            props.Item(set_name).Item(prop).Value = str(value)
        # The ISO title block prints the author under "Designed by".
        if "designer" in fields and "author" not in fields:
            props.Item("Summary Information").Item("Author").Value = str(fields["designer"])
        tb = doc.ActiveSheet.TitleBlock
        if tb is None:
            return "iProperties set; the sheet has no title block"
        shown = {}
        boxes = tb.Definition.Sketch.TextBoxes
        for i in range(1, boxes.Count + 1):
            t = boxes.Item(i)
            if t.Text.startswith("<") and t.Text.count("<") == 1:
                shown[t.Text.strip("<> ").lower()] = tb.GetResultText(t)
        return json.dumps(shown, ensure_ascii=False)

    def list_views(self) -> dict:
        sheet = self.active_drawing().ActiveSheet
        area = self._drawing_area(sheet)
        views, problems = [], []
        dv = sheet.DrawingViews
        rects = {}
        for i in range(1, dv.Count + 1):
            v = dv.Item(i)
            r = self._view_rect(v)
            rects[v.Name] = r
            views.append({
                "name": v.Name,
                "scale": round(v.Scale, 4),
                "center_mm": [round(v.Center.X * 10, 1), round(v.Center.Y * 10, 1)],
                "box_mm": [round(n, 1) for n in r],
            })
            if r[0] < area[0] or r[1] < area[1] or r[2] > area[2] or r[3] > area[3]:
                problems.append(f"{v.Name} leaves the border")
        names = list(rects)
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                if self._overlap(rects[names[i]], rects[names[j]]):
                    problems.append(f"{names[i]} overlaps {names[j]}")
        if sheet.TitleBlock is not None:
            tb = self._rect(sheet.TitleBlock)
            problems += [f"{n} overlaps the title block" for n, r in rects.items() if self._overlap(r, tb)]
        problems += [f"{a} overlaps {b}" for a, b in self._clashes(self._text_boxes(sheet))]
        return {
            "sheet_mm": [round(sheet.Width * 10, 1), round(sheet.Height * 10, 1)],
            "border_mm": [round(n, 1) for n in area],
            "title_block_mm": [round(n, 1) for n in self._rect(sheet.TitleBlock)] if sheet.TitleBlock else None,
            "views": views,
            "dimensions": sheet.DrawingDimensions.GeneralDimensions.Count,
            "problems": problems,
        }

    def export_sheet_png(self, path: str, width: int = 2000) -> str:
        """Picture of the whole active sheet, for checking the layout by eye."""
        doc = self.active_drawing()
        path = os.path.abspath(path)
        sheet = doc.ActiveSheet
        doc.Activate()
        view = self.app.ActiveView
        view.Fit()
        height = int(round(width * sheet.Height / sheet.Width))
        view.SaveAsBitmap(path, width, height)
        return f"Sheet image: {path} ({width}x{height} px)"

    def export_pdf(self, path: str, all_sheets: bool = True, black_lines: bool = True) -> str:
        doc = self.active_drawing()
        path = os.path.abspath(path)
        self._translate(doc, "PDF", path, {
            "Sheet_Range": 14082 if all_sheets else 14081,  # kPrintAllSheets / kPrintCurrentSheet
            "All_Color_AS_Black": 1 if black_lines else 0,
            "Vector_Resolution": 400,
        })
        return f"PDF: {path} ({os.path.getsize(path)} bytes)"
