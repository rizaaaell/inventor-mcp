"""Wrapper around Autodesk Inventor COM API."""

import json
import os
import re
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
            return f"Saved as: {path}" + self._save_dirty_references(doc) + self._write_constraint_log(doc)
        doc.Save()
        return f"Saved: {doc.FullFileName}" + self._save_dirty_references(doc) + self._write_constraint_log(doc)

    @staticmethod
    def _save_dirty_references(doc) -> str:
        """Save models a drawing changed, e.g. iProperties written by set_title_block."""
        saved = []
        refs = doc.ReferencedDocuments
        for i in range(1, refs.Count + 1):
            ref = refs.Item(i)
            if ref.Dirty and ref.FullFileName:
                ref.Save()
                saved.append(os.path.basename(ref.FullFileName))
        return f" (also saved {', '.join(saved)})" if saved else ""

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

    # Templates shipped with the installed Inventor, for "builtin:" in a profile.
    BUILTIN_TEMPLATES = r"C:\Users\Public\Documents\Autodesk\Inventor {year}\Templates\en-US"
    PROFILE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                               "drawing_profiles")
    _VIEW_TYPES = {"section_view": 10503, "detail_view": 10502, "auxiliary_view": 10499}
    _ANNOTATION_TYPES = {"section_line": 10503, "detail_fence": 10502}
    _SHEET_SIZES = {"A0": 9993, "A1": 9994, "A2": 9995, "A3": 9996, "A4": 9997}
    _VIEW_ORIENTATIONS = {
        "front": 10764, "top": 10754, "right": 10755, "back": 10756, "bottom": 10757,
        "left": 10758, "iso_top_right": 10759, "iso_top_left": 10760,
        "iso_bottom_right": 10761, "iso_bottom_left": 10762,
    }
    _VIEW_STYLES = {"hidden": 32257, "visible": 32258, "shaded": 32259,
                    "from_base": 32260, "shaded_hidden": 32261}
    def active_drawing(self):
        doc = self.active_document()
        if doc.DocumentType != 12292:  # kDrawingDocumentObject
            raise RuntimeError(f"Active document is not a drawing (type={doc.DocumentType}).")
        return doc

    # Team-only settings (names, private templates) live in the private assets checkout
    # under references/; a profile there is laid over the public one of the same name.
    PRIVATE_PROFILE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                       "references", "drawing_profiles")

    @classmethod
    def _merge(cls, base: dict, extra: dict) -> dict:
        out = dict(base)
        for k, v in extra.items():
            out[k] = cls._merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
        return out

    def load_profile(self, name: str = "default") -> dict:
        found = [os.path.join(d, f"{name}.json") for d in (self.PROFILE_DIR, self.PRIVATE_PROFILE_DIR)]
        found = [p for p in found if os.path.exists(p)]
        if not found:
            available = sorted({f[:-5] for d in (self.PROFILE_DIR, self.PRIVATE_PROFILE_DIR)
                                if os.path.isdir(d) for f in os.listdir(d) if f.endswith(".json")})
            raise ValueError(f"No drawing profile {name!r}. Available: {available}")
        profile = {}
        for path in found:
            with open(path, encoding="utf-8") as f:
                profile = self._merge(profile, json.load(f))
        profile["name"] = name
        return profile

    def _resolve_template(self, template: str) -> str:
        if template.startswith("builtin:"):
            year = str(self.app.SoftwareVersion.DisplayVersion).split(".")[0]
            return os.path.join(self.BUILTIN_TEMPLATES.format(year=year),
                                *template[len("builtin:"):].split("/"))
        if not os.path.isabs(template):
            return os.path.join(os.path.dirname(self.PROFILE_DIR), template)
        return template

    def _apply_profile(self, doc, profile: dict) -> None:
        """Set projection, units, dimension format and label formats in this drawing."""
        std = doc.StylesManager.ActiveStandardStyle
        if "projection" in profile:
            std.FirstAngleProjection = profile["projection"].lower() == "first"
        if profile.get("units", "mm") == "mm":
            std.LinearUnits = 11269  # kMillimeterLengthUnits
        marker = {"period": 41473, "comma": 41474, "default": 41475}.get(profile.get("decimal_marker", ""))
        if marker:
            std.DecimalMarkerType = marker
        defaults = std.ActiveObjectDefaults
        for attr in ("LinearDimensionStyle", "DiameterDimensionStyle", "RadialDimensionStyle"):
            style = getattr(defaults, attr)
            if "dimension_precision" in profile:
                style.LinearPrecision = 41729 + int(profile["dimension_precision"])  # kZeroDecimalPlace...
            if "trailing_zeros" in profile:
                style.TrailingZeroDisplay = bool(profile["trailing_zeros"])
        labels = profile.get("labels", {})
        for key, view_type in self._VIEW_TYPES.items():
            if key in labels:
                prefix, visible, _, constrain, below = std.GetViewLabelDefaults(view_type)
                std.SetViewLabelDefaults(view_type, prefix, visible, labels[key], constrain, below)
        for key, view_type in self._ANNOTATION_TYPES.items():
            if key in labels:
                std.SetViewAnnotationDefaults(view_type, labels[key])
        if profile.get("general_tolerances"):
            self._write_general_tolerances(doc, profile["general_tolerances"])
        line_type = {"chain": 37644, "dashed": 37641, "continuous": 37633}.get(
            profile.get("centerline_line_type", ""))
        if line_type:
            # The ISO centerline layer comes out as plain dashes on circles, which reads as a
            # hidden line around a bolt circle; chain is long dash, short dash (ISO 128).
            for attr in ("CenterlineLayer", "CentermarkLayer"):
                getattr(defaults, attr).LineType = line_type

    def _write_general_tolerances(self, doc, values: dict) -> None:
        """Put the profile's general tolerances after each "=±" of the title block's
        "TOLERANCES OTHERWISE NOTED" text, e.g. {".X": "0,2", "ANGULAR": "1°"}."""
        tb = doc.ActiveSheet.TitleBlock
        if tb is None:
            return
        definition = tb.Definition
        boxes = definition.Sketch.TextBoxes
        target = next((boxes.Item(i) for i in range(1, boxes.Count + 1)
                       if boxes.Item(i).Text.upper().startswith("TOLERANCES")), None)
        if target is None:
            return
        text = target.FormattedText
        for key, value in values.items():
            # "=±" up to the end of that line's run; longer keys first keeps ".X" off ".XX".
            text = re.sub(rf"((?<![.\w]){re.escape(key)}\s*=±)[^<]*", lambda m: f"{m.group(1)} {value}", text)
        if text == target.FormattedText:
            return
        sketch = definition.Edit()
        try:
            boxes = sketch.TextBoxes
            box = next(boxes.Item(i) for i in range(1, boxes.Count + 1)
                       if boxes.Item(i).Text.upper().startswith("TOLERANCES"))
            box.FormattedText = text
        finally:
            definition.ExitEdit(True)

    def create_drawing(self, profile: str = "default", template: str = "", sheet_size: str = "") -> str:
        """New drawing set up by a profile from drawing_profiles/; template and sheet_size override it."""
        prof = self.load_profile(profile)
        template = self._resolve_template(template or prof.get("template", "builtin:Metric/ISO.idw"))
        sheet_size = sheet_size or prof.get("sheet_size", "")
        if not os.path.exists(template):
            raise RuntimeError(f"Drawing template not found: {template}")
        template = os.path.normpath(template)
        for i in range(1, self.app.Documents.Count + 1):
            if os.path.normcase(self.app.Documents.Item(i).FullFileName) == os.path.normcase(template):
                raise RuntimeError(f"The template {template} is open in Inventor; close it first, "
                                   "Documents.Add refuses an open template.")
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
        self._apply_profile(doc, prof)
        self._profiles = getattr(self, "_profiles", {})
        self._profiles[doc.InternalName] = prof
        self.pin_document(doc)
        std = doc.StylesManager.ActiveStandardStyle
        angle = "first" if std.FirstAngleProjection else "third"
        return (f"Drawing created: {doc.DisplayName}, profile {profile}, sheet {sheet.Width * 10:.0f}x"
                f"{sheet.Height * 10:.0f} mm, {std.Name}, {angle} angle projection")

    def _profile_of(self, doc) -> dict:
        return getattr(self, "_profiles", {}).get(doc.InternalName) or self.load_profile("default")

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
        for i in range(1, sheet.PartsLists.Count + 1):
            if self._overlap(rect, self._rect(sheet.PartsLists.Item(i))):
                problems.append(f"overlaps the parts list ({self._fmt_rect(self._rect(sheet.PartsLists.Item(i)))})")
        if problems:
            view.Delete()
            raise ValueError(f"View would sit at {self._fmt_rect(rect)}: {'; '.join(problems)}. "
                             "Move it or change the scale.")
        return rect

    def close_documents_in(self, folder: str) -> list[str]:
        """Close every open document saved in folder, drawings and assemblies first.

        Closing a part that an open assembly or drawing still uses makes Inventor show an
        "improper argument" dialog; while it is up, later Close calls are ignored, and
        closing more referenced files can crash Inventor. Unsaved changes are discarded.
        """
        folder = os.path.normcase(os.path.abspath(folder))

        def inside():
            out = []
            for i in range(1, self.app.Documents.Count + 1):
                d = self.app.Documents.Item(i)
                if d.FullFileName and os.path.normcase(os.path.dirname(d.FullFileName)) == folder:
                    out.append(d)
            return out

        closed = []
        while docs := inside():
            top = [d for d in docs if d.ReferencingDocuments.Count == 0]
            if not top:
                users = {d.ReferencingDocuments.Item(i).FullFileName or d.ReferencingDocuments.Item(i).DisplayName
                         for d in docs for i in range(1, d.ReferencingDocuments.Count + 1)}
                raise RuntimeError(f"Documents in {folder} are still used by {sorted(users)}; close those first")
            for d in top:
                name = d.FullFileName
                d.Close(True)
                if any(o.FullFileName == name for o in inside()):
                    raise RuntimeError(f"Inventor did not close {name}; a dialog may be open in Inventor")
                closed.append(os.path.basename(name))
        return closed

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
                      orientation: str = "front", style: str = "visible",
                      design_view: str = "", positional: str = "",
                      spin: float = 0, spin_axis: str = "Z", weldment_state: str = "") -> str:
        """spin turns the camera of the orientation by that many degrees about the model's
        spin_axis, e.g. so the bolts of a flange stop hiding each other in an iso view."""
        sheet = self.active_drawing().ActiveSheet
        orient = self._VIEW_ORIENTATIONS.get(orientation.lower())
        if orient is None:
            raise ValueError(f"Unknown orientation {orientation}. Use {', '.join(self._VIEW_ORIENTATIONS)}.")
        model = self._open_model(model_path)
        options = None
        if design_view or positional:
            if model.DocumentType != 12291:
                raise ValueError("design_view and positional apply to assemblies only")
            reps = model.ComponentDefinition.RepresentationsManager
            options = self.app.TransientObjects.CreateNameValueMap()
            for key, name, collection in (("DesignViewRepresentation", design_view, reps.DesignViewRepresentations),
                                          ("PositionalRepresentation", positional, reps.PositionalRepresentations)):
                if not name:
                    continue
                names = [collection.Item(i).Name for i in range(1, collection.Count + 1)]
                if name not in names:
                    raise ValueError(f"No {key} {name!r} in {model.DisplayName}: {names}")
                options.Add(key, name)
        first = sheet.DrawingViews.Count == 0
        camera, name = self._spun_camera(sheet, model, orient, spin, spin_axis) if spin else (None, "")
        view = sheet.DrawingViews.AddBaseView(
            model, self._sheet_point(x, y), scale, 10763 if camera else orient, self._style(style),
            "", camera, options)
        if name:
            view.Name = name  # the throwaway view took the next name
        if self._is_weldment(model) or weldment_state:
            # A weldment view opens in the assembly state, without its welds.
            state = self._WELD_STATES.get((weldment_state or "welds").lower())
            if state is None:
                raise ValueError(f"weldment_state must be one of {', '.join(self._WELD_STATES)}")
            view.SetWeldmentState(state)
        rect = self._place_check(sheet, view)
        note = ""
        if first:
            filled = self._apply_title_defaults(self.active_drawing())
            note = f"; title block defaults filled: {', '.join(filled)}" if filled else ""
        return f"Base view {view.Name}: {orientation}, scale {scale:g}, {self._fmt_rect(rect)}{note}"

    def _spun_camera(self, sheet, model, orient: int, spin: float, axis: str):
        """Camera of a standard orientation turned about a model axis through its target."""
        import math
        k = {"X": (1, 0, 0), "Y": (0, 1, 0), "Z": (0, 0, 1)}.get(axis.upper())
        if k is None:
            raise ValueError("spin_axis must be X, Y or Z")
        # A throwaway view is the only way to read the camera of a standard orientation.
        probe = sheet.DrawingViews.AddBaseView(model, self._sheet_point(0, 0), 0.01, orient, 32257)
        name = probe.Name
        try:
            c = probe.Camera
            eye, target, up = c.Eye, c.Target, c.UpVector
            eye, target, up = (eye.X, eye.Y, eye.Z), (target.X, target.Y, target.Z), (up.X, up.Y, up.Z)
        finally:
            probe.Delete()
        a = math.radians(spin)

        def turn(v):  # Rodrigues rotation about k
            cross = (k[1] * v[2] - k[2] * v[1], k[2] * v[0] - k[0] * v[2], k[0] * v[1] - k[1] * v[0])
            dot = sum(p * q for p, q in zip(k, v))
            return tuple(v[i] * math.cos(a) + cross[i] * math.sin(a) + k[i] * dot * (1 - math.cos(a))
                         for i in range(3))

        tg = self._tg()
        d = turn(tuple(e - t for e, t in zip(eye, target)))
        camera = self.app.TransientObjects.CreateCamera()
        camera.Target = tg.CreatePoint(*target)
        camera.Eye = tg.CreatePoint(*(t + v for t, v in zip(target, d)))
        camera.UpVector = tg.CreateUnitVector(*turn(up))
        return camera, name

    def _apply_title_defaults(self, doc) -> list[str]:
        """Fill the profile's title_block_defaults into fields that are still empty."""
        defaults = self._profile_of(doc).get("title_block_defaults", {})
        if not defaults:
            return []
        aliases = {k.upper(): v.upper() for k, v in self._profile_of(doc).get("title_block_aliases", {}).items()}
        sheet = doc.ActiveSheet
        available = self._title_block_fields(sheet)
        todo = {}
        for name, value in defaults.items():
            field = aliases.get(name.upper(), name.upper())
            if field in available and not sheet.TitleBlock.GetResultText(available[field][0]).strip():
                todo[field] = value
        if todo:
            self.set_title_block(todo)
        return list(todo)

    def add_projected_view(self, parent: str, x: float, y: float, style: str = "from_base") -> str:
        sheet = self.active_drawing().ActiveSheet
        view = sheet.DrawingViews.AddProjectedView(
            self._view(parent), self._sheet_point(x, y), self._style(style))
        rect = self._place_check(sheet, view)
        return f"Projected view {view.Name} from {parent}: {self._fmt_rect(rect)}"

    def add_section_view(self, parent: str, x1: float, y1: float, x2: float, y2: float,
                         x: float, y: float, label: str = "A", style: str = "from_base",
                         no_hatch: str = "") -> str:
        """Section line from (x1, y1) to (x2, y2) in the parent view, view placed at (x, y).
        no_hatch: assembly components drawn unhatched, e.g. shafts cut along their axis."""
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
        hidden = self._hide_hatch(view, no_hatch) if no_hatch else ""
        return f"Section view {view.Name} from {parent}: {self._fmt_rect(rect)}{hidden}"

    def _hide_hatch(self, view, occurrences: str) -> str:
        # The API has no per-component section participation. A part cut along its axis has
        # the same outline either way, so hiding its hatch draws it as unsectioned.
        names = re.findall(r"\s*(.+?:\d+)\s*(?:,|$)", occurrences)
        hidden = set()
        regions = view.HatchRegions
        for i in range(1, regions.Count + 1):
            region = regions.Item(i)
            try:
                occ = region.SurfaceBody.ContainingOccurrence
            except Exception:
                continue
            if occ is not None and any(self._same_name(occ.Name, n) for n in names):
                region.Visible = False
                hidden.add(occ.Name)
        missing = [n for n in names if not any(self._same_name(h, n) for h in hidden)]
        if missing:
            raise ValueError(f"No hatch in view {view.Name} for {missing}")
        return f"; unhatched: {', '.join(sorted(hidden))}"

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
        try:
            std = sheet.Parent.StylesManager.ActiveStandardStyle
            section_mark = std.GetViewAnnotationDefaults(10503)
            detail_mark = std.GetViewAnnotationDefaults(10502)
        except Exception:
            section_mark = detail_mark = "<DrawingViewName/> / <DrawingViewSheetZone/>"
        # Sheet tokens print as "A / .A6"; without them the mark is the letter alone.
        mark_width = 40 if "Sheet" in section_mark else 15
        fence_half = 20 if "Sheet" in detail_mark else 6
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
                        boxes.append((f"section line label {v.Name}", (x - 5, y - 10, x + mark_width, y + 10)))
            except Exception:
                pass
            try:
                c, r = v.FenceCenter, v.FenceRadius  # only circular detail views
                x, y, r = c.X * 10, c.Y * 10, r * 10
                boxes.append((f"detail fence label {v.Name}", (x - fence_half, y + r, x + fence_half, y + r + 9)))
            except Exception:
                pass
        for label, collection in (("feature control frame", sheet.FeatureControlFrames),
                                  ("symbol", sheet.SketchedSymbols),
                                  ("surface finish", sheet.SurfaceTextureSymbols),
                                  ("parts list", sheet.PartsLists)):
            for i in range(1, collection.Count + 1):
                try:
                    boxes.append((f"{label} {i}", self._rect(collection.Item(i))))
                except Exception:
                    pass
        balloons = sheet.Balloons
        for i in range(1, balloons.Count + 1):  # balloons have no RangeBox
            b = balloons.Item(i)
            r = self._balloon_diameter(b.Style) / 2
            x, y = b.Position.X * 10, b.Position.Y * 10
            boxes.append((f"balloon {b.BalloonValueSets.Item(1).ItemNumber}", (x - r, y - r, x + r, y + r)))
        welds = sheet.WeldingSymbols
        for i in range(1, welds.Count + 1):
            # No RangeBox either; Position is where the reference line meets the leader, and
            # the line runs to one side, so the box covers both.
            p = welds.Item(i).Position
            x, y = p.X * 10, p.Y * 10
            boxes.append((f"weld symbol {i}", (x - 22, y - 7, x + 22, y + 7)))
        return boxes

    @staticmethod
    def _balloon_diameter(style) -> float:
        # Scaled to text height the circle measures 3x the text height (10.5 mm for 3.5 mm
        # text), not BalloonDiameter.
        if style.ScaleToTextHeight:
            return 3 * style.TextStyle.FontSize * 10
        return style.BalloonDiameter * 10

    def _dimension_boxes(self, sheet):
        boxes = []
        dims = sheet.DrawingDimensions.GeneralDimensions
        for i in range(1, dims.Count + 1):
            d = dims.Item(i)
            try:
                boxes.append((f"dimension {d.Text.Text}", self._rect(d.Text)))
            except Exception:
                pass
        notes = sheet.DrawingNotes.HoleThreadNotes
        for i in range(1, notes.Count + 1):
            n = notes.Item(i)
            try:
                boxes.append((f"hole note {n.Text.Text}", self._rect(n.Text)))
            except Exception:
                pass
        notes = sheet.DrawingNotes.ChamferNotes
        for i in range(1, notes.Count + 1):
            try:  # a chamfer note's Text is a plain string; the box is the note's own
                boxes.append((f"chamfer note {notes.Item(i).Text}", self._rect(notes.Item(i))))
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
        for d in new:
            self._tag_view(d, v.Name)
            self._fit_precision(d)
        moved = self._untangle(new, v, obstacles)
        clashes = self._clashes(self._text_boxes(sheet))
        values = ", ".join(d.Text.Text for d in new)
        return (f"Retrieved {len(new)} dimension(s) in {v.Name}: {values}; "
                f"{moved} text move(s) to clear overlaps; remaining text overlaps: {clashes or 'none'}")

    def add_centerlines(self, view: str) -> str:
        """Automated centerlines and center marks, then every cylinder axis drawn full length."""
        doc = self.active_drawing()
        sheet = doc.ActiveSheet
        v = self._view(view)
        lines, marks = sheet.Centerlines.Count, sheet.Centermarks.Count
        settings = v.GetAutomatedCenterlineSettings()
        for flag in ("ApplyToHoles", "ApplyToCylinders", "ApplyToCircularPatterns",
                     "ApplyToRevolutions", "ProjectionNormalAxis", "ProjectionParallelAxis"):
            setattr(settings, flag, True)
        v.SetAutomatedCenterlineSettings(settings)
        overshoot = float(self._profile_of(doc).get("centerline_overshoot_mm", 3))
        extended, added = self._complete_axes(sheet, v, overshoot)
        bolt_circles = self._bolt_circles(sheet, v)
        marked = self._extend_centermarks(sheet, v, overshoot)
        return (f"Centerlines on {v.Name}: +{sheet.Centerlines.Count - lines} centerline(s), "
                f"+{sheet.Centermarks.Count - marks} centermark(s); {extended} axis line(s) "
                f"stretched and {added} added to span their cylinders + {overshoot:g} mm; "
                f"{bolt_circles} bolt circle(s) added; {marked} center mark(s) run past their circle")

    def _bolt_circles(self, sheet, view) -> int:
        """Pitch circle through three or more equal holes spaced evenly around a circle centre.

        Automated centerlines draw one only for a patterned feature; holes cut in one sketch
        get none, and add_dimension "pcd" needs it."""
        circles = []
        curves = view.DrawingCurves
        for i in range(1, curves.Count + 1):
            c = curves.Item(i)
            try:
                if c.CurveType != 5124 or c.Segments.Count != 1 or c.Segments.Item(1).HiddenLine:
                    continue
                g = c.Segments.Item(1).Geometry
                circles.append((c, g.Center.X, g.Center.Y, g.Radius))
            except Exception:
                continue
        existing = []
        for i in range(1, sheet.Centerlines.Count + 1):
            try:
                g = sheet.Centerlines.Item(i).Geometry
                existing.append((g.Center.X, g.Center.Y, g.Radius))
            except Exception:
                continue
        made = 0
        radii = sorted({round(r, 3) for _, _, _, r in circles})
        for radius in radii:
            holes = [c for c in circles if abs(c[3] - radius) < 1e-3]
            if len(holes) < 3:
                continue
            for center in circles:
                if center in holes:
                    continue
                d = [((h[1] - center[1]) ** 2 + (h[2] - center[2]) ** 2) ** 0.5 for h in holes]
                if min(d) < 1e-3 or max(d) - min(d) > 1e-3:
                    continue
                if any(abs(e[0] - center[1]) < 1e-3 and abs(e[1] - center[2]) < 1e-3
                       and abs(e[2] - d[0]) < 1e-3 for e in existing):
                    break
                col = self.app.TransientObjects.CreateObjectCollection()
                for h in holes:
                    col.Add(sheet.CreateGeometryIntent(h[0], 57860))  # kCenterPointIntent
                sheet.Centerlines.AddCenteredPattern(sheet.CreateGeometryIntent(center[0], 57860),
                                                     col, None, None, True)
                existing.append((center[1], center[2], d[0]))
                made += 1
                break
        return made

    def _extend_centermarks(self, sheet, view, overshoot_mm: float) -> int:
        """Run each center mark's extension lines past the largest circle around it.

        Automated marks stop inside the hole; marks of a hole pattern refuse new extension
        points, so those are hidden and replaced by a plain mark on the same circle.
        """
        tg = self._tg()
        rect = self._view_rect(view)
        circles = []  # (curve, center x, center y, radius) in sheet cm
        curves = view.DrawingCurves
        for i in range(1, curves.Count + 1):
            curve = curves.Item(i)
            segments = curve.Segments
            if segments.Count != 1:
                continue
            g = segments.Item(1).Geometry
            try:
                if segments.Item(1).HiddenLine:
                    continue
                circles.append((curve, g.Center.X, g.Center.Y, g.Radius))
            except Exception:
                continue  # not a circle
        if not circles:
            return 0

        def around(x, y):
            same = [c for c in circles if abs(c[1] - x) < 1e-3 and abs(c[2] - y) < 1e-3]
            return max(same, key=lambda c: c[3]) if same else None

        def stretch(mark, radius) -> bool:
            p = mark.Position
            r = radius + overshoot_mm / 10.0
            try:
                for name, (dx, dy) in zip(("One", "Two", "Three", "Four"),
                                          ((r, 0), (0, r), (-r, 0), (0, -r))):
                    setattr(mark, f"ExtensionPoint{name}", tg.CreatePoint2d(p.X + dx, p.Y + dy))
                return True
            except Exception:
                return False

        done = 0
        marks = sheet.Centermarks
        for mark in [marks.Item(i) for i in range(1, marks.Count + 1)]:
            if not mark.Visible:
                continue
            p = mark.Position
            if not (rect[0] <= p.X * 10 <= rect[2] and rect[1] <= p.Y * 10 <= rect[3]):
                continue
            circle = around(p.X, p.Y)
            if circle is None:
                continue
            if not stretch(mark, circle[3]):
                mark.Visible = False
                replacement = marks.Add(sheet.CreateGeometryIntent(circle[0], 57860), True)  # center
                if not stretch(replacement, circle[3]):
                    continue
            done += 1
        return done

    def _complete_axes(self, sheet, view, overshoot_mm: float):
        """Make one centerline per cylinder or cone axis lying in the view plane, spanning
        every silhouette of that axis plus the overshoot. Automated centerlines often stop
        at one feature (e.g. only the hub of a flange)."""
        tg = self._tg()
        groups = []  # {"o": (x, y), "d": (dx, dy), "points": [...], "curves": [...]}, sheet cm
        curves = view.DrawingCurves
        for i in range(1, curves.Count + 1):
            curve = curves.Item(i)
            try:
                face = curve.ModelGeometry
                if face.SurfaceType not in (5891, 5893):  # cylinder, cone
                    continue
                g = face.Geometry
                base, axis = g.BasePoint, g.AxisVector
            except Exception:
                continue
            p0 = view.ModelToSheetSpace(base)
            p1 = view.ModelToSheetSpace(tg.CreatePoint(base.X + axis.X, base.Y + axis.Y, base.Z + axis.Z))
            dx, dy = p1.X - p0.X, p1.Y - p0.Y
            n = (dx * dx + dy * dy) ** 0.5
            if n < 1e-6:
                continue  # axis points at the viewer; center marks cover it
            d = (dx / n, dy / n)
            group = next((gr for gr in groups
                          if abs(gr["d"][0] * d[1] - gr["d"][1] * d[0]) < 1e-3
                          and abs((p0.X - gr["o"][0]) * gr["d"][1] - (p0.Y - gr["o"][1]) * gr["d"][0]) < 0.01),
                         None)
            if group is None:
                group = {"o": (p0.X, p0.Y), "d": d, "points": [], "curves": []}
                groups.append(group)
            segments = curve.Segments
            for j in range(1, segments.Count + 1):
                seg = segments.Item(j)
                group["points"] += [(seg.StartPoint.X, seg.StartPoint.Y), (seg.EndPoint.X, seg.EndPoint.Y)]
            group["curves"].append(curve)

        extended = added = 0
        ext = overshoot_mm / 10.0
        for gr in groups:
            (ox, oy), (dx, dy) = gr["o"], gr["d"]
            ts = [(x - ox) * dx + (y - oy) * dy for x, y in gr["points"]]
            start = tg.CreatePoint2d(ox + dx * (min(ts) - ext), oy + dy * (min(ts) - ext))
            end = tg.CreatePoint2d(ox + dx * (max(ts) + ext), oy + dy * (max(ts) + ext))
            line = self._collinear_centerline(sheet, gr["o"], gr["d"])
            if line is None:
                sides = {}
                for c in gr["curves"]:
                    m = c.MidPoint
                    side = (m.X - ox) * dy - (m.Y - oy) * dx
                    if abs(side) > 1e-4:
                        sides.setdefault(side > 0, c)
                if len(sides) < 2:
                    continue  # only one silhouette visible, nothing to bisect
                line = sheet.Centerlines.AddBisector(sheet.CreateGeometryIntent(sides[True]),
                                                      sheet.CreateGeometryIntent(sides[False]))
                added += 1
            else:
                extended += 1
            # An end that would make the line run backwards is silently ignored, so keep its direction.
            a, b = line.StartPoint, line.EndPoint
            if (b.X - a.X) * dx + (b.Y - a.Y) * dy < 0:
                start, end = end, start
            line.StartPoint, line.EndPoint = start, end
        return extended, added

    @staticmethod
    def _collinear_centerline(sheet, origin, direction):
        lines = sheet.Centerlines
        ox, oy = origin
        dx, dy = direction
        for i in range(1, lines.Count + 1):
            line = lines.Item(i)
            try:
                if hasattr(line.Geometry, "Radius"):
                    continue
                a, b = line.StartPoint, line.EndPoint
            except Exception:
                continue
            if all(abs((p.X - ox) * dy - (p.Y - oy) * dx) < 0.01 for p in (a, b)):
                return line
        return None

    def _nearest_curve(self, view, x: float, y: float, circular: bool = False):
        """Drawing curve of a view closest to a point given in model mm from the view center."""
        curve, miss, _ = self._closest_on_curve(view, x, y, circular)
        return curve, miss

    def _closest_on_curve(self, view, x: float, y: float, circular: bool = False):
        """(curve, distance in model mm, closest point on it as a sheet Point2d)."""
        p = self._view_point(view, x, y)
        best, best_d, best_pt = None, None, None
        curves = view.DrawingCurves  # property get; calling it fails under late binding
        for i in range(1, curves.Count + 1):
            curve = curves.Item(i)
            try:
                segments = curve.Segments
                count = segments.Count
            except Exception:
                continue  # weld bead curves in a weldment view raise E_NOTIMPL here
            for j in range(1, count + 1):
                try:
                    g = segments.Item(j).Geometry
                except Exception:
                    continue
                try:
                    center, radius = g.Center, g.Radius
                    dx, dy = p.X - center.X, p.Y - center.Y
                    n = (dx * dx + dy * dy) ** 0.5 or 1e-12
                    d = abs(n - radius)
                    foot = (center.X + radius * dx / n, center.Y + radius * dy / n)
                    is_circle = True
                except Exception:
                    try:
                        a, b = g.StartPoint, g.EndPoint
                    except Exception:
                        continue  # ellipses and splines
                    vx, vy = b.X - a.X, b.Y - a.Y
                    t = max(0.0, min(1.0, ((p.X - a.X) * vx + (p.Y - a.Y) * vy) / ((vx * vx + vy * vy) or 1e-12)))
                    foot = (a.X + t * vx, a.Y + t * vy)
                    d = ((p.X - foot[0]) ** 2 + (p.Y - foot[1]) ** 2) ** 0.5
                    is_circle = False
                if circular and not is_circle:
                    continue
                if best_d is None or d < best_d:
                    best, best_d, best_pt = curve, d, foot
        if best is None:
            raise ValueError(f"No {'circular ' if circular else ''}curve in view {view.Name}")
        return best, best_d * 10 / view.Scale, self._tg().CreatePoint2d(*best_pt)

    def add_dimension(self, view: str, kind: str, x1: float, y1: float,
                      x2: float | None = None, y2: float | None = None,
                      text_x: float = 0, text_y: float = 0, prefix: str = "",
                      vertex_x: float = 0, vertex_y: float = 0, suffix: str = "") -> str:
        """kind: diameter / radius (curve nearest x1,y1); horizontal / vertical / aligned
        (between the curves nearest x1,y1 and x2,y2); angle (between the centers of the
        circles nearest x1,y1 and x2,y2, seen from the center of the circle nearest
        vertex_x,vertex_y, e.g. two bolt holes around the bore; without x2,y2 the angle is
        from the horizontal axis through the vertex, on its right, to the hole). All points in model mm from
        the view center. prefix goes before the value, e.g. "Ø" for a diameter in a side
        view; suffix after it, "\\n" for a new line, e.g. " THRU\\nON PCD 76, EQ SP"."""
        sheet = self.active_drawing().ActiveSheet
        v = self._view(view)
        dims = sheet.DrawingDimensions.GeneralDimensions
        text = self._view_point(v, text_x, text_y)
        kind = kind.lower()
        if kind in ("diameter", "radius"):
            curve, miss = self._nearest_curve(v, x1, y1, circular=True)
            intent = sheet.CreateGeometryIntent(curve)
            dim = dims.AddDiameter(text, intent) if kind == "diameter" else dims.AddRadius(text, intent)
        elif kind == "pcd":
            centerline, miss = self._nearest_circle_centerline(sheet, v, x1, y1)
            dim = dims.AddDiameter(text, sheet.CreateGeometryIntent(centerline))
        elif kind == "angle":
            c1, m1 = self._nearest_curve(v, x1, y1, circular=True)
            cv, mv = self._nearest_curve(v, vertex_x, vertex_y, circular=True)
            center = 57860  # kCenterPointIntent; the vertex is the middle intent
            if x2 is None or y2 is None:
                # The far end is the vertex circle's point at 0°; Inventor refuses the one at 180°.
                g = cv.Segments.Item(1).Geometry
                end = sheet.CreateGeometryIntent(cv, self._tg().CreatePoint2d(g.Center.X + g.Radius, g.Center.Y))
                miss = max(m1, mv)
            else:
                c2, m2 = self._nearest_curve(v, x2, y2, circular=True)
                end = sheet.CreateGeometryIntent(c2, center)
                miss = max(m1, m2, mv)
            dim = dims.AddAngular(text, sheet.CreateGeometryIntent(c1, center),
                                  sheet.CreateGeometryIntent(cv, center), end)
        elif kind in ("horizontal", "vertical", "aligned"):
            if x2 is None or y2 is None:
                raise ValueError(f"A {kind} dimension needs x2 and y2")
            c1, m1 = self._nearest_curve(v, x1, y1)
            c2, m2 = self._nearest_curve(v, x2, y2)
            miss = max(m1, m2)
            dim_type = {"aligned": 60161, "horizontal": 60162, "vertical": 60163}[kind]
            dim = dims.AddLinear(text, sheet.CreateGeometryIntent(c1), sheet.CreateGeometryIntent(c2), dim_type)
        else:
            raise ValueError("kind must be diameter, radius, pcd, angle, horizontal, vertical or aligned")
        if kind != "angle":
            self._fit_precision(dim)
        if prefix or suffix:
            tail = suffix.replace("\n", "<Br/>")
            dim.Text.FormattedText = prefix + dim.Text.FormattedText + tail
        self._tag_view(dim, v.Name)
        clashes = [c for c in self._clashes(self._text_boxes(sheet)) if f"dimension {dim.Text.Text}" in c]
        picked = "curves" if kind in ("horizontal", "vertical", "aligned", "angle") else "curve"
        return (f"{kind.capitalize()} dimension {dim.Text.Text} in {v.Name} "
                f"(picked {picked} within {miss:.1f} mm); text overlaps: {clashes or 'none'}")

    @staticmethod
    def _fit_precision(dim, most: int = 2) -> None:
        """Show as many decimals as the model value needs (121,42 rather than 121,4), up to
        two: more would also tighten the general tolerance the title block ties to them."""
        try:
            if "°" in dim.Text.Text:
                return  # angles: ModelValue is in radians
            value = abs(dim.ModelValue) * 10
            current = dim.Precision
        except Exception:
            return
        for p in range(current, most + 1):
            if abs(value - round(value, p)) < 5e-4 or p == most:
                if p > current:
                    dim.Precision = p
                return

    def _nearest_circle_centerline(self, sheet, view, x: float, y: float):
        """Circular centerline (e.g. a bolt circle) inside a view, nearest to a model-mm point."""
        p = self._view_point(view, x, y)
        rect = self._view_rect(view)
        best, best_d = None, None
        lines = sheet.Centerlines
        for i in range(1, lines.Count + 1):
            line = lines.Item(i)
            try:
                g = line.Geometry
                center, radius = g.Center, g.Radius
            except Exception:
                continue  # straight centerline
            if not (rect[0] <= center.X * 10 <= rect[2] and rect[1] <= center.Y * 10 <= rect[3]):
                continue
            d = abs(((p.X - center.X) ** 2 + (p.Y - center.Y) ** 2) ** 0.5 - radius)
            if best_d is None or d < best_d:
                best, best_d = line, d
        if best is None:
            raise ValueError(f"No circular centerline in view {view.Name}; run add_centerlines first")
        return best, best_d * 10 / view.Scale

    def add_hole_note(self, view: str, x: float, y: float, text_x: float, text_y: float,
                      second_line: str = "", count: int = 0) -> str:
        """Hole or thread note on the hole edge nearest (x, y), e.g. "4x Ø11 THRU" for a patterned
        hole, or on a thread seen from the side ("M42x1.5 - 6g").
        second_line goes under it, e.g. "EQ SP ON PCD Ø90". count > 0 writes "<count>x" for
        holes made as separate features, which Inventor does not count.
        Points are model mm from the view center."""
        doc = self.active_drawing()
        sheet = doc.ActiveSheet
        v = self._view(view)
        try:
            curve, miss = self._nearest_curve(v, x, y, circular=True)
        except ValueError:
            curve, miss = None, None
        if miss is None or miss > 1.0:
            # A thread seen from the side is a line, not a circle: note it there.
            line, line_miss = self._nearest_curve(v, x, y)
            if miss is None or line_miss < miss:
                curve, miss = line, line_miss
        note = sheet.DrawingNotes.HoleThreadNotes.Add(self._view_point(v, text_x, text_y), curve)
        quantity = self._profile_of(doc).get("hole_note_quantity")
        if count > 0:
            note.FormattedHoleThreadNote = f"{count}x " + note.FormattedHoleThreadNote
        elif quantity:
            try:
                note.FormattedQuantityNote = quantity
                note.FormattedHoleThreadNote = "<QuantityNote/>" + note.FormattedHoleThreadNote
            except Exception:
                pass  # a thread note on a shaft has no hole count
        if second_line:
            # Inside the last style run, or the line falls back to a large default font.
            head, sep, tail = note.FormattedHoleThreadNote.rpartition("</StyleOverride>")
            note.FormattedHoleThreadNote = (head + "<Br/>" + second_line + sep + tail) if sep                 else note.FormattedHoleThreadNote + "<Br/>" + second_line
        clashes = [c for c in self._clashes(self._text_boxes(sheet)) if f"hole note {note.Text.Text}" in c]
        return (f"Hole note '{note.Text.Text}' in {v.Name} (picked hole edge within {miss:.1f} mm); "
                f"text overlaps: {clashes or 'none'}")

    def add_chamfer_note(self, view: str, x: float, y: float, ref_x: float, ref_y: float,
                         text_x: float, text_y: float, prefix: str = "") -> str:
        """Chamfer note ("1 x 45°") on the chamfer line nearest (x, y), measured against the
        edge nearest (ref_x, ref_y). prefix, e.g. "2x ", counts chamfers of the same size.
        Points are model mm from the view center."""
        sheet = self.active_drawing().ActiveSheet
        v = self._view(view)
        chamfer, m1 = self._nearest_curve(v, x, y)
        reference, m2 = self._nearest_curve(v, ref_x, ref_y)
        try:
            note = sheet.DrawingNotes.ChamferNotes.Add(self._view_point(v, text_x, text_y), chamfer, reference)
        except Exception as exc:
            raise ValueError(f"Inventor refused a chamfer note on the curves near ({x}, {y}) and "
                             f"({ref_x}, {ref_y}) in {v.Name}: pick the slanted chamfer line and the "
                             "edge it meets, in a view where the chamfer shows as a slant") from exc
        # The default format carries a zero symmetric tolerance and prints "1 ± 0 X 45° ± 0°".
        text = re.sub(r" (?:UpperTolerance|LowerTolerance|ToleranceType|TolerancePrecision|"
                      r"ToleranceAlternatePrecision)='[^']*'", "", note.FormattedChamferNote)
        note.FormattedChamferNote = prefix + text
        clashes = [c for c in self._clashes(self._text_boxes(sheet)) if "chamfer note" in c[0] or "chamfer note" in c[1]]
        return (f"Chamfer note '{note.Text}' in {v.Name} (picked edges within {max(m1, m2):.1f} mm); "
                f"text overlaps: {clashes or 'none'}")

    def list_dimensions(self) -> list[dict]:
        """Dimensions on the active sheet with text, text center (mm) and view. The view is the
        one the dimension was made in by these tools, otherwise the view nearest its text."""
        sheet = self.active_drawing().ActiveSheet
        rects = {}
        for i in range(1, sheet.DrawingViews.Count + 1):
            v = sheet.DrawingViews.Item(i)
            rects[v.Name] = self._view_rect(v)

        def nearest_view(x, y):
            def gap(r):
                return (max(r[0] - x, 0, x - r[2]) ** 2 + max(r[1] - y, 0, y - r[3]) ** 2) ** 0.5
            return min(rects, key=lambda n: gap(rects[n])) if rects else None

        out = []
        dims = sheet.DrawingDimensions.GeneralDimensions
        for i in range(1, dims.Count + 1):
            d = dims.Item(i)
            r = self._rect(d.Text)
            x, y = (r[0] + r[2]) / 2, (r[1] + r[3]) / 2
            out.append({"index": i, "text": d.Text.Text, "text_mm": [round(x, 1), round(y, 1)],
                        "view": self._tagged_view(d) or nearest_view(x, y)})
        return out

    _TAG_SET = "inventor_mcp"

    def _tag_view(self, dimension, view_name: str) -> None:
        """Remember which view a dimension belongs to; its text may later move near another view."""
        sets = dimension.AttributeSets
        attrs = sets.Item(self._TAG_SET) if sets.NameIsUsed(self._TAG_SET) else sets.Add(self._TAG_SET)
        if attrs.NameIsUsed("view"):
            attrs.Item("view").Value = view_name
        else:
            attrs.Add("view", 14595, view_name)  # kStringType

    def _tagged_view(self, dimension):
        try:
            sets = dimension.AttributeSets
            if sets.NameIsUsed(self._TAG_SET):
                return sets.Item(self._TAG_SET).Item("view").Value
        except Exception:
            pass
        return None

    def delete_dimension(self, indices: list[int]) -> str:
        """Delete dimensions by the index list_dimensions reports."""
        dims = self.active_drawing().ActiveSheet.DrawingDimensions.GeneralDimensions
        count = dims.Count
        bad = [i for i in indices if not 1 <= i <= count]
        if bad:
            raise ValueError(f"Dimension index {bad} out of range 1..{count}")
        removed = []
        for i in sorted(set(indices), reverse=True):
            removed.append(dims.Item(i).Text.Text)
            dims.Item(i).Delete()
        return f"Deleted {len(removed)} dimension(s): {', '.join(reversed(removed))}"

    def move_dimension(self, index: int, text_x: float, text_y: float) -> str:
        """Move the text of the dimension list_dimensions reports at index. The position is
        model mm from the center of the dimension's view."""
        sheet = self.active_drawing().ActiveSheet
        dims = sheet.DrawingDimensions.GeneralDimensions
        if not 1 <= index <= dims.Count:
            raise ValueError(f"Dimension index {index} out of range 1..{dims.Count}")
        dim = dims.Item(index)
        view_name = self._tagged_view(dim)
        if view_name is None:
            raise ValueError(f"Dimension {index} has no recorded view; it was not made by these tools")
        dim.Text.Origin = self._view_point(self._view(view_name), text_x, text_y)
        clashes = [c for c in self._clashes(self._text_boxes(sheet)) if f"dimension {dim.Text.Text}" in c]
        return f"Dimension {index} ({dim.Text.Text}) text moved; text overlaps: {clashes or 'none'}"

    def set_tolerance(self, index: int, kind: str, upper: float = 0, lower: float = 0,
                      fit: str = "") -> str:
        """Tolerance on the dimension list_dimensions reports at index. Values in mm.
        kind: symmetric (±upper), deviation (+upper / -lower), limits, fit (e.g. "H7"
        for a hole, "h6" for a shaft), basic, reference, or default (none)."""
        dims = self.active_drawing().ActiveSheet.DrawingDimensions.GeneralDimensions
        if not 1 <= index <= dims.Count:
            raise ValueError(f"Dimension index {index} out of range 1..{dims.Count}")
        dim = dims.Item(index)
        tol = dim.Tolerance
        kind = kind.lower()
        if kind == "symmetric":
            tol.SetToSymmetric(upper / 10.0)
        elif kind == "deviation":
            tol.SetToDeviation(upper / 10.0, -abs(lower) / 10.0)
        elif kind == "limits":
            tol.SetToLimits(31237, upper / 10.0, -abs(lower) / 10.0)  # kLimitsStackedTolerance
        elif kind == "fit":
            if not fit:
                raise ValueError('kind "fit" needs fit, e.g. "H7" or "h6"')
            hole = fit if fit[0].isupper() else ""
            shaft = "" if hole else fit
            tol.SetToFits(31242, hole, shaft)  # kLimitsFitsLinearTolerance: "Ø30 H7", no limits
        elif kind == "basic":
            tol.SetToBasic()
        elif kind == "reference":
            tol.SetToReference()
        elif kind == "default":
            tol.SetToDefault()
        else:
            raise ValueError("kind must be symmetric, deviation, limits, fit, basic, reference or default")
        return f"Dimension {index} ({dim.Text.Text}) tolerance set to {kind} {fit or ''}".rstrip()

    _GDT = {
        "straightness": 1, "flatness": 2, "circularity": 4, "profile_line": 8,
        "profile_surface": 16, "angularity": 32, "perpendicularity": 64, "parallelism": 128,
        "position": 256, "concentricity": 512, "circular_runout": 1024, "symmetry": 2048,
        "total_runout": 4096, "cylindricity": 8192,
    }

    def _leader_points(self, view, x: float, y: float, text_x: float, text_y: float,
                       attach: bool = True, leader: bool = True):
        """Leader from the text position to (x, y).

        attach: end on the curve nearest (x, y), at its closest point (without that point
        Inventor puts the end on the curve's start). False ends exactly at (x, y), e.g. on
        an extension line, which is not a view curve. leader False: text position only.
        Returns (points, distance to the curve in mm or None).
        """
        points = self.app.TransientObjects.CreateObjectCollection()
        points.Add(self._view_point(view, text_x, text_y))
        if not leader:
            return points, None
        if not attach:
            points.Add(self._view_point(view, x, y))
            return points, None
        curve, miss, foot = self._closest_on_curve(view, x, y)
        points.Add(self.active_drawing().ActiveSheet.CreateGeometryIntent(curve, foot))
        return points, miss

    @staticmethod
    def _where(miss) -> str:
        return "at a free point" if miss is None else f"on a curve within {miss:.1f} mm"

    def _dimension_text_rect(self, sheet, index: int):
        dims = sheet.DrawingDimensions.GeneralDimensions
        if not 1 <= index <= dims.Count:
            raise ValueError(f"Dimension index {index} out of range 1..{dims.Count}")
        return dims.Item(index), self._rect(dims.Item(index).Text)

    def add_gdt(self, view: str, x: float, y: float, text_x: float, text_y: float,
                characteristic: str, tolerance: float, datums: str = "",
                diameter_zone: bool = False, attach: bool = True, leader: bool = True,
                dimension: int = 0) -> str:
        """Feature control frame with a leader to the curve nearest (x, y).
        datums: comma-separated datum letters in order of precedence, e.g. "A,B".
        leader False places the bare frame at (text_x, text_y), e.g. under a hole note.
        dimension: index from list_dimensions; the frame goes directly under that
        dimension's text without a leader (x, y, text_x, text_y are then ignored), the
        ISO way to tie a tolerance to a size feature such as a hole pattern."""
        doc = self.active_drawing()
        sheet = doc.ActiveSheet
        v = self._view(view)
        code = self._GDT.get(characteristic.lower())
        if code is None:
            raise ValueError(f"Unknown characteristic {characteristic}. Use {', '.join(self._GDT)}.")
        if dimension:
            dim, r = self._dimension_text_rect(sheet, dimension)
            # The frame's position is the middle of its top edge.
            points = self.app.TransientObjects.CreateObjectCollection()
            points.Add(self._tg().CreatePoint2d((r[0] + r[2]) / 20, (r[1] - 1.5) / 10))
            leader, miss = False, None
        else:
            points, miss = self._leader_points(v, x, y, text_x, text_y, attach, leader)
        marker = "," if self._profile_of(doc).get("decimal_marker", "comma") == "comma" else "."
        value = f"{tolerance:g}".replace(".", marker)
        letters = [d.strip() for d in datums.split(",") if d.strip()][:3]
        letters += [""] * (3 - len(letters))
        rows = sheet.FeatureControlFrames.CreateFeatureControlFrameRows()
        rows.Add(code, ("Ø" if diameter_zone else "") + value, "", *letters)
        sheet.FeatureControlFrames.Add(points, rows)
        frame = " | ".join([characteristic, ("Ø" if diameter_zone else "") + value] + [d for d in letters if d])
        where = f"under dimension {dimension}" if dimension else (
            "no leader" if not leader else f"leader {self._where(miss)}")
        return f"Feature control frame [{frame}] in {v.Name} ({where})"

    _DATUM_SYMBOL = "Datum identifier (MCP)"

    def _datum_definition(self, doc):
        """Sketched symbol: square box with the datum letter as a prompt. The API has no
        datum identifier call; the leader gets the filled datum triangle when placed."""
        defs = doc.SketchedSymbolDefinitions
        for i in range(1, defs.Count + 1):
            if defs.Item(i).Name == self._DATUM_SYMBOL:
                return defs.Item(i)
        tg = self._tg()
        definition = defs.Add(self._DATUM_SYMBOL)
        sketch = definition.Edit()
        h = 0.35  # 7 mm box
        corners = [tg.CreatePoint2d(-h, -h), tg.CreatePoint2d(h, -h),
                   tg.CreatePoint2d(h, h), tg.CreatePoint2d(-h, h)]
        for i in range(4):
            sketch.SketchLines.AddByTwoPoints(corners[i], corners[(i + 1) % 4])
        box = sketch.TextBoxes.AddByRectangle(corners[0], corners[2], "<Prompt>DATUM</Prompt>")
        box.HorizontalJustification = 19969  # kAlignTextCenter
        box.VerticalJustification = 25601  # kAlignTextMiddle
        definition.ExitEdit(True)
        return definition

    def add_datum(self, view: str, x: float, y: float, label: str,
                  text_x: float, text_y: float, attach: bool = True, dimension: int = 0) -> str:
        """Datum identifier: letter in a box at (text_x, text_y), filled triangle on the
        curve nearest (x, y), or exactly at (x, y) with attach False (e.g. on the extension
        line of a diameter, which makes the axis the datum). Model mm from the view center.
        dimension: index from list_dimensions; the triangle sits on that size dimension's
        text shoulder near the leader, box below it, so the feature's axis is the datum
        (x, y, text_x, text_y are then ignored)."""
        doc = self.active_drawing()
        sheet = doc.ActiveSheet
        v = self._view(view)
        if dimension:
            dim, r = self._dimension_text_rect(sheet, dimension)
            # Drawn like Inventor's own datum identifier, which the API cannot create:
            # triangle on the shoulder 4 mm in from the end the leader joins, a drop of
            # 9 mm, then across to the box.
            inner_right = (r[0] + r[2]) / 2 < v.Center.X * 10
            foot = r[2] - 4 if inner_right else r[0] + 4
            box = foot + (8 if inner_right else -8)
            tg = self._tg()
            points = self.app.TransientObjects.CreateObjectCollection()
            points.Add(tg.CreatePoint2d(box / 10, (r[1] - 9) / 10))
            points.Add(tg.CreatePoint2d(foot / 10, (r[1] - 9) / 10))
            points.Add(tg.CreatePoint2d(foot / 10, r[1] / 10))
            miss = None
        else:
            points, miss = self._leader_points(v, x, y, text_x, text_y, attach)
        prompts = win32com.client.VARIANT(pythoncom.VT_ARRAY | pythoncom.VT_BSTR, [label])
        symbol = sheet.SketchedSymbols.AddWithLeader(self._datum_definition(doc), points, 0.0, 1.0, prompts)
        symbol.Leader.ArrowheadType = 71955  # kDatum60FilledArrowheadType
        where = f"on the shoulder of dimension {dimension}" if dimension else self._where(miss)
        return f"Datum {label} in {v.Name} (triangle {where})"

    def add_surface_finish(self, view: str, x: float, y: float, text_x: float, text_y: float,
                           roughness: str = "Ra 3,2", removal: str = "required",
                           attach: bool = True) -> str:
        """Surface texture symbol with a leader to the curve nearest (x, y), or exactly to
        (x, y) with attach False (e.g. an extension line). removal: required (machined),
        prohibited, or any."""
        sheet = self.active_drawing().ActiveSheet
        v = self._view(view)
        kind = {"any": 76801, "required": 76802, "prohibited": 76803}.get(removal.lower())
        if kind is None:
            raise ValueError("removal must be required, prohibited or any")
        points, miss = self._leader_points(v, x, y, text_x, text_y, attach)
        sheet.SurfaceTextureSymbols.Add(points, kind, False, False, False, roughness)
        return f"Surface finish {roughness} ({removal} removal) in {v.Name} (leader {self._where(miss)})"

    def _title_block_fields(self, sheet) -> dict:
        """{FIELD: (text box, source)} for the fillable fields of the sheet's title block.

        source is "prompt", or the attributes of the <Property> tag (Document, FormatID,
        PropertyID). Computed fields such as sheet number or scale are left out.
        """
        tb = sheet.TitleBlock
        if tb is None:
            return {}
        fields = {}
        boxes = tb.Definition.Sketch.TextBoxes
        for i in range(1, boxes.Count + 1):
            t = boxes.Item(i)
            name = t.Text.strip().strip("<>").strip().upper()
            tag = re.search(r"<Property ([^>]*)>", t.FormattedText)
            if tag:
                fields[name] = (t, dict(re.findall(r"(\w+)='([^']*)'", tag.group(1))))
            elif "<Prompt" in t.FormattedText:
                fields[name] = (t, "prompt")
        return fields

    _UNSET_MATERIALS = ("generic", "default", "")

    def _material_statement(self, model) -> str:
        """What MATERIAL should say: the part's material, the one material all parts of an
        assembly share, or the profile's statement for mixed or unassigned materials."""
        profile = self._profile_of(self.active_drawing())
        none = profile.get("material_none", "NONE")
        if model.DocumentType == 12290:
            name = model.ActiveMaterial.DisplayName
            return none if name.lower() in self._UNSET_MATERIALS else name
        names = set()
        refs = model.AllReferencedDocuments
        for i in range(1, refs.Count + 1):
            d = refs.Item(i)
            if d.DocumentType == 12290:
                name = d.ActiveMaterial.DisplayName
                if name.lower() not in self._UNSET_MATERIALS:
                    names.add(name)
        if not names:
            return none
        if len(names) == 1:
            return names.pop()
        return profile.get("material_mixed", "VARIOUS, SEE PART DRAWINGS")

    def _set_material(self, model, name: str, strict: bool = True) -> bool:
        """Give a part the library material called name. strict False returns False instead
        of raising when there is no such material (MATERIAL then only prints the text)."""
        if model.DocumentType != 12290:
            if strict:
                raise ValueError("MATERIAL can only be set on a part")
            return False
        lib = self.app.ActiveMaterialLibrary.MaterialAssets
        names = [lib.Item(i).DisplayName for i in range(1, lib.Count + 1)]
        match = next((n for n in names if n.lower() == name.lower()), None)
        if match is None:
            if not strict:
                return False
            close = [n for n in names if name.lower().split()[0] in n.lower()][:8]
            raise ValueError(f"No material {name!r} in the active library. Close: {close}")
        assets = model.MaterialAssets
        local = next((assets.Item(i) for i in range(1, assets.Count + 1)
                      if assets.Item(i).DisplayName == match), None)
        model.ActiveMaterial = local or lib.Item(match).CopyTo(model)
        return True

    def set_title_block(self, fields: dict) -> str:
        """Fill title block fields by the names the title block shows, e.g. TITLE, PART NUMBER.

        Each field is written where the title block reads it: a prompt on the sheet, an
        iProperty of the drawing, or an iProperty of the model in the first view
        (MATERIAL sets the part's material). Returns what the title block now shows.
        """
        doc = self.active_drawing()
        sheet = doc.ActiveSheet
        available = self._title_block_fields(sheet)
        if not available:
            raise ValueError("The active sheet has no title block with fillable fields")
        aliases = {k.upper(): v.upper() for k, v in self._profile_of(doc).get("title_block_aliases", {}).items()}
        wanted = {}
        for k, v in fields.items():
            name = k.replace("_", " ").strip().upper()
            wanted[aliases.get(name, name)] = str(v)
        unknown = [k for k in wanted if k not in available]
        if unknown:
            raise ValueError(f"Title block has no field {unknown}. Fields: {sorted(available)}")
        model = None
        if sheet.DrawingViews.Count:
            model = sheet.DrawingViews.Item(1).ReferencedDocumentDescriptor.ReferencedDocument
        changed_model = []
        for name, value in wanted.items():
            box, source = available[name]
            if source == "prompt":
                if name == "MATERIAL" and model is not None and value.strip().upper() != "AUTO":
                    # A library material name also becomes the part's material; NONE or a
                    # statement is only printed.
                    if self._set_material(model, value, strict=False):
                        changed_model.append(name)
                if name == "MATERIAL" and value.strip().upper() == "AUTO":
                    if model is None:
                        raise ValueError("MATERIAL auto needs a view of the model first")
                    value = self._material_statement(model)
                sheet.TitleBlock.SetPromptResultText(box, value)
                continue
            target = doc
            if source.get("Document") == "model":
                if model is None:
                    raise ValueError(f"{name} is read from the model; place a view first")
                target = model
                changed_model.append(name)
            if source.get("Property") == "Material" and target is model:
                self._set_material(model, value)
            else:
                target.PropertySets.Item(source["FormatID"]).ItemByPropId(
                    int(source["PropertyID"])).Value = value
        doc.Update()
        shown = {n: sheet.TitleBlock.GetResultText(box) for n, (box, _) in available.items()}
        result = {"title_block": shown}
        if changed_model:
            result["model_changed"] = {"file": model.DisplayName, "fields": changed_model,
                                       "note": "save_document on the drawing saves the model too"}
        return json.dumps(result, ensure_ascii=False)

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
        boxes = self._text_boxes(sheet)
        problems += [f"{a} overlaps {b}" for a, b in self._clashes(boxes)]
        problems += [f"{name} sticks out of the border" for name, r in boxes
                     if r[0] < area[0] or r[1] < area[1] or r[2] > area[2] or r[3] > area[3]]
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
        doc.SelectSet.Clear()  # the last placed object stays highlighted in red otherwise
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

    # ---------- Assemblies ----------
    # Geometry of a component is picked with a selector in the component's own part
    # coordinates (mm), so it does not change when the component moves:
    #   plane:XY | plane:XZ | plane:YZ      origin work plane
    #   axis:X | axis:Y | axis:Z            origin work axis
    #   circle:x,y,z,r                      circular edge with that center and radius
    #   face:x,y,z                          face nearest the point
    #   cylinder:x,y,z                      cylindrical or conical face nearest the point
    #   edge:x,y,z                          edge nearest the point
    # The component name "assembly" means the assembly's own origin planes and axes.

    ASSEMBLY_TEMPLATE = "builtin:Metric/Standard (mm).iam"

    def active_assembly(self):
        doc = self.active_document()
        if doc.DocumentType != 12291:  # kAssemblyDocumentObject
            raise RuntimeError(f"Active document is not an assembly (type={doc.DocumentType}).")
        return doc

    def create_assembly(self, template: str = "") -> str:
        path = self._resolve_template(template or self.ASSEMBLY_TEMPLATE)
        if not os.path.exists(path):
            raise RuntimeError(f"Assembly template not found: {path}")
        doc = self._add_document(12291, path)
        self.pin_document(doc)
        self._constraint_logs = getattr(self, "_constraint_logs", {})
        self._constraint_logs[doc.InternalName] = []
        return f"Assembly created: {doc.DisplayName}"

    @staticmethod
    def _same_name(a: str, b: str) -> bool:
        # Content Center names carry double spaces ("DIN 933 - M10  x 60:1").
        return " ".join(a.lower().split()) == " ".join(b.lower().split())

    @staticmethod
    def _components(definition) -> list:
        """Occurrences backed by a file. A weldment also holds its welds as an unnamed
        occurrence without a document, which the tools leave out."""
        occs = definition.Occurrences
        return [occs.Item(i) for i in range(1, occs.Count + 1)
                if occs.Item(i).ReferencedDocumentDescriptor is not None]

    def _occurrence(self, name: str):
        occs = self.active_assembly().ComponentDefinition.Occurrences
        names = []
        for i in range(1, occs.Count + 1):
            o = occs.Item(i)
            if self._same_name(o.Name, name):
                return o
            names.append(o.Name)
        raise ValueError(f"No component named {name!r}. Components: {names}")

    @staticmethod
    def _pose(occ) -> str:
        t = occ.Transformation
        origin = [round(t.Cell(r, 4) * 10, 2) for r in (1, 2, 3)]
        z_axis = [round(t.Cell(r, 3), 3) for r in (1, 2, 3)]
        return f"origin {origin} mm, Z axis {z_axis}"

    def place_component(self, path: str, x: float = 0, y: float = 0, z: float = 0,
                        rx: float = 0, ry: float = 0, rz: float = 0, grounded: bool = False) -> str:
        """Place a part or subassembly at (x, y, z) mm, turned rx, ry, rz degrees about X, Y, Z."""
        import math
        ad = self.active_assembly().ComponentDefinition
        path = os.path.abspath(path)
        if not os.path.exists(path):
            raise RuntimeError(f"File not found: {path}")
        tg = self._tg()
        m = tg.CreateMatrix()
        for angle, axis in ((rx, (1, 0, 0)), (ry, (0, 1, 0)), (rz, (0, 0, 1))):
            if angle:
                r = tg.CreateMatrix()
                r.SetToRotation(math.radians(angle), tg.CreateVector(*axis), tg.CreatePoint(0, 0, 0))
                r.PostMultiplyBy(m)
                m = r
        m.SetTranslation(tg.CreateVector(x / 10.0, y / 10.0, z / 10.0))
        occ = ad.Occurrences.Add(path, m)
        if grounded:
            occ.Grounded = True
        return f"Placed {occ.Name}{' (grounded)' if grounded else ''}: {self._pose(occ)}"

    # Content Center members are generated into the active project's Content Center
    # folder, as Inventor's own Place from Content Center does.

    def _cc_node(self, category: str):
        node = self.app.ContentCenter.TreeViewTopNode
        for part in [p.strip() for p in category.replace("\\", "/").split("/") if p.strip()]:
            children = {node.ChildNodes.Item(i).DisplayName.lower(): node.ChildNodes.Item(i)
                        for i in range(1, node.ChildNodes.Count + 1)}
            if part.lower() not in children:
                raise ValueError(f"No Content Center category {part!r} under {node.DisplayName or 'the top'}: "
                                 f"{sorted(c.DisplayName for c in children.values())}")
            node = children[part.lower()]
        return node

    def _cc_families(self, category: str) -> dict:
        # Reading family names is slow (seconds per category), so keep them per session.
        cache = self.__dict__.setdefault("_cc_cache", {})
        key = category.lower().strip("/ ")
        if key not in cache:
            fams = self._cc_node(category).Families
            cache[key] = {fams.Item(j).DisplayName: fams.Item(j) for j in range(1, fams.Count + 1)}
        return cache[key]

    def _cc_family(self, category: str, family: str):
        fams = self._cc_families(category)
        for name, fam in fams.items():
            if name.lower() == family.lower():
                return fam
        starts = [n for n in fams if n.lower().startswith(family.lower())]
        if len(starts) == 1:
            return fams[starts[0]]
        raise ValueError(f"Family {family!r} in {category}: "
                         + (f"ambiguous, matches {starts}" if starts else "not found; list_content_center shows the names"))

    @staticmethod
    def _cc_key(text: str) -> str:
        # Designations use the locale decimal mark and odd spacing: "A 10,5", "M10  x 60".
        return " ".join(text.lower().replace(",", ".").split())

    def _cc_sizes(self, fam) -> list:
        cols = fam.TableColumns
        names = [cols.Item(i).InternalName for i in range(1, cols.Count + 1)]
        col = names.index("SIZE") + 1 if "SIZE" in names else names.index("DESIGNATION") + 1
        rows = fam.TableRows
        return [(rows.Item(i), rows.Item(i).Item(col).Value) for i in range(1, rows.Count + 1)]

    def list_content_center(self, category: str = "", family: str = "", contains: str = "") -> dict:
        """Browse Content Center: subcategories and families of a category, or a family's sizes."""
        if family:
            sizes = [s for _, s in self._cc_sizes(self._cc_family(category, family))
                     if self._cc_key(contains) in self._cc_key(s)]
            return {"family": family, "sizes": sizes}
        node = self._cc_node(category)
        out = {"category": category or "(top)",
               "subcategories": [node.ChildNodes.Item(i).DisplayName for i in range(1, node.ChildNodes.Count + 1)]}
        if category:
            out["families"] = sorted(n for n in self._cc_families(category) if contains.lower() in n.lower())
        return out

    def content_center_member(self, category: str, family: str, size: str) -> str:
        """Path of a Content Center part, generated on first use."""
        fam = self._cc_family(category, family)
        rows = [r for r, s in self._cc_sizes(fam) if self._cc_key(s) == self._cc_key(size)]
        if not rows:
            raise ValueError(f"No size {size!r} in {fam.DisplayName}; list_content_center shows the sizes")
        path, _, message = fam.CreateMember(rows[0])
        if not path or not os.path.exists(path):
            raise RuntimeError(f"Content Center could not create {fam.DisplayName} {size}: {message}")
        return path

    def place_content_center(self, category: str, family: str, size: str, x: float = 0, y: float = 0,
                             z: float = 0, rx: float = 0, ry: float = 0, rz: float = 0,
                             grounded: bool = False) -> str:
        path = self.content_center_member(category, family, size)
        return self.place_component(path, x, y, z, rx, ry, rz, grounded) + f" | file {path}"

    def _native_geometry(self, definition, selector: str):
        """Resolve a selector on a part (or the assembly's own) component definition."""
        kind, _, args = selector.partition(":")
        kind = kind.strip().lower()
        args = args.strip()
        if kind in ("plane", "axis"):
            index = {"YZ": 1, "XZ": 2, "XY": 3, "X": 1, "Y": 2, "Z": 3}.get(args.upper())
            if index is None:
                raise ValueError(f"Unknown {kind} {args!r}")
            return (definition.WorkPlanes if kind == "plane" else definition.WorkAxes).Item(index)
        values = [float(v) for v in args.split(",")] if args else []
        tg = self._tg()
        bodies = definition.SurfaceBodies
        if kind == "circle":
            if len(values) != 4:
                raise ValueError("circle needs x,y,z,r")
            x, y, z, r = values
            for b in range(1, bodies.Count + 1):
                edges = bodies.Item(b).Edges
                for i in range(1, edges.Count + 1):
                    e = edges.Item(i)
                    if e.GeometryType != 5124:  # kCircleCurve
                        continue
                    g = e.Geometry
                    if (abs(g.Radius * 10 - r) < 0.05 and abs(g.Center.X * 10 - x) < 0.05
                            and abs(g.Center.Y * 10 - y) < 0.05 and abs(g.Center.Z * 10 - z) < 0.05):
                        return e
            raise ValueError(f"No circular edge with center ({x}, {y}, {z}) and radius {r}; "
                             "list_occurrence_geometry shows the circles there are")
        if kind in ("face", "cylinder", "edge"):
            if len(values) != 3:
                raise ValueError(f"{kind} needs x,y,z")
            p = tg.CreatePoint(values[0] / 10, values[1] / 10, values[2] / 10)
            best, best_d = None, None
            for b in range(1, bodies.Count + 1):
                items = bodies.Item(b).Edges if kind == "edge" else bodies.Item(b).Faces
                for i in range(1, items.Count + 1):
                    item = items.Item(i)
                    if kind == "cylinder" and item.SurfaceType not in (5891, 5893):
                        continue
                    q = item.GetClosestPointTo(p)
                    d = ((q.X - p.X) ** 2 + (q.Y - p.Y) ** 2 + (q.Z - p.Z) ** 2) ** 0.5
                    if best_d is None or d < best_d:
                        best, best_d = item, d
            if best is None:
                raise ValueError(f"No {kind} in the component")
            if best_d * 10 > 1.0:
                raise ValueError(f"Nearest {kind} is {best_d * 10:.1f} mm from ({args})")
            return best
        raise ValueError(f"Unknown selector {selector!r}: use plane:, axis:, circle:, face:, cylinder: or edge:")

    def _geometry(self, occurrence: str, selector: str):
        """Assembly-context geometry (a proxy) for a selector on a component."""
        if occurrence.lower() == "assembly":
            return self._native_geometry(self.active_assembly().ComponentDefinition, selector)
        occ = self._occurrence(occurrence)
        return occ.CreateGeometryProxy(self._native_geometry(occ.Definition, selector))

    def list_occurrence_geometry(self, occurrence: str, kind: str = "circles") -> list[str]:
        """Selectors for the circular edges ("circles") or planar faces ("planes") of a component."""
        definition = self._occurrence(occurrence).Definition
        out = []
        bodies = definition.SurfaceBodies
        for b in range(1, bodies.Count + 1):
            body = bodies.Item(b)
            if kind == "circles":
                for i in range(1, body.Edges.Count + 1):
                    e = body.Edges.Item(i)
                    if e.GeometryType == 5124:
                        g = e.Geometry
                        out.append(f"circle:{g.Center.X * 10:g},{g.Center.Y * 10:g},{g.Center.Z * 10:g},{g.Radius * 10:g}")
            elif kind == "planes":
                for i in range(1, body.Faces.Count + 1):
                    f = body.Faces.Item(i)
                    if f.SurfaceType == 5890:
                        r = f.Evaluator.RangeBox
                        c = [(getattr(r.MinPoint, a) + getattr(r.MaxPoint, a)) / 2 * 10 for a in "XYZ"]
                        out.append(f"face:{c[0]:.4g},{c[1]:.4g},{c[2]:.4g}")
            else:
                raise ValueError('kind must be "circles" or "planes"')
        return sorted(set(out))

    def add_constraint(self, kind: str, occurrence1: str, geometry1: str, occurrence2: str,
                       geometry2: str, offset: float = 0, angle: float = 0,
                       opposed: bool = True, name: str = "") -> str:
        """kind: mate, flush, insert, angle, tangent. offset in mm (for insert, negative pushes
        the second component into the first), angle in degrees, opposed for insert axes."""
        import math
        doc = self.active_assembly()
        constraints = doc.ComponentDefinition.Constraints
        e1 = self._geometry(occurrence1, geometry1)
        e2 = self._geometry(occurrence2, geometry2)
        kind = kind.lower()
        if kind == "mate":
            c = constraints.AddMateConstraint(e1, e2, offset / 10.0)
        elif kind == "flush":
            c = constraints.AddFlushConstraint(e1, e2, offset / 10.0)
        elif kind == "insert":
            c = constraints.AddInsertConstraint(e1, e2, opposed, offset / 10.0)
        elif kind == "angle":
            c = constraints.AddAngleConstraint(e1, e2, math.radians(angle))
        elif kind == "tangent":
            c = constraints.AddTangentConstraint(e1, e2, False, offset / 10.0)
        else:
            raise ValueError("kind must be mate, flush, insert, angle or tangent")
        base = name or f"{kind.capitalize()}_{occurrence1}_{occurrence2}".replace(":", "_")
        taken = {constraints.Item(i).Name for i in range(1, constraints.Count + 1)} - {c.Name}
        unique, n = base, 2
        while unique in taken:  # Inventor refuses a duplicate name, e.g. two flushes on one pair
            unique, n = f"{base}_{n}", n + 1
        c.Name = unique
        doc.Update()
        logs = getattr(self, "_constraint_logs", {})
        log = logs.setdefault(doc.InternalName, [])
        log.append({"step": len(log) + 1, "name": c.Name, "kind": kind,
                    "first": {"component": occurrence1, "geometry": geometry1},
                    "second": {"component": occurrence2, "geometry": geometry2},
                    "offset_mm": offset, "angle_deg": angle, "opposed": opposed})
        self._constraint_logs = logs
        health = "healthy" if c.HealthStatus == 11778 else f"health {c.HealthStatus}"
        moved = "" if occurrence2.lower() == "assembly" else f"; {occurrence2}: {self._pose(self._occurrence(occurrence2))}"
        return f"{c.Name} ({health}){moved}"

    def _write_constraint_log(self, doc) -> str:
        """Constraint order next to the saved assembly, for an assembly sequence later."""
        if doc.DocumentType != 12291 or not doc.FullFileName:
            return ""
        log = getattr(self, "_constraint_logs", {}).get(doc.InternalName)
        if not log:
            return ""
        path = os.path.splitext(doc.FullFileName)[0] + ".constraints.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"assembly": os.path.basename(doc.FullFileName), "constraints": log}, f,
                      indent=1, ensure_ascii=False)
        return f" (constraint order: {os.path.basename(path)})"

    def list_occurrences(self) -> list[dict]:
        out = []
        for o in self._components(self.active_assembly().ComponentDefinition):
            t = o.Transformation
            dof = o.GetDegreesOfFreedom()
            out.append({"name": o.Name,
                        "file": os.path.basename(o.ReferencedDocumentDescriptor.FullDocumentName),
                        "grounded": bool(o.Grounded),
                        "origin_mm": [round(t.Cell(r, 4) * 10, 2) for r in (1, 2, 3)],
                        "free_translations": dof[0], "free_rotations": dof[2]})
        return out

    def get_dof(self, occurrence: str = "") -> dict:
        """Free translations and rotations of one component, or of all of them."""
        rows = self.list_occurrences()
        if occurrence:
            rows = [r for r in rows if self._same_name(r["name"], occurrence)]
            if not rows:
                raise ValueError(f"No component named {occurrence!r}")
        free = [r["name"] for r in rows if r["free_translations"] or r["free_rotations"]]
        return {"components": {r["name"]: [r["free_translations"], r["free_rotations"]] for r in rows},
                "with_free_dof": free, "fully_constrained": not free}

    def get_bom(self, view: str = "parts") -> list[dict]:
        """Bill of materials: view "parts" (parts only) or "structured" (top level)."""
        bom = self.active_assembly().ComponentDefinition.BOM
        if view.lower().startswith("struct"):
            bom.StructuredViewEnabled = True
            name = "Structured"
        else:
            bom.PartsOnlyViewEnabled = True
            name = "Parts Only"
        bom_view = next(bom.BOMViews.Item(i) for i in range(1, bom.BOMViews.Count + 1)
                        if bom.BOMViews.Item(i).Name == name)
        out = []
        rows = bom_view.BOMRows
        for i in range(1, rows.Count + 1):
            row = rows.Item(i)
            document = row.ComponentDefinitions.Item(1).Document
            props = document.PropertySets.Item("Design Tracking Properties")
            out.append({"item": row.ItemNumber, "quantity": row.ItemQuantity,
                        "part_number": props.Item("Part Number").Value,
                        "description": props.Item("Description").Value,
                        "file": os.path.basename(document.FullFileName)})
        return out

    def analyze_interference(self) -> list[dict]:
        """Every overlapping pair with its volume. Tapped holes are cut at the minor diameter,
        so a tapped part against a threaded one is a thread artifact, not a real clash."""
        ad = self.active_assembly().ComponentDefinition
        col = self.app.TransientObjects.CreateObjectCollection()
        for o in self._components(ad):
            col.Add(o)
        results = ad.AnalyzeInterference(col)

        def tapped(occ):
            try:
                holes = occ.Definition.Features.HoleFeatures
                return any(holes.Item(i).Tapped for i in range(1, holes.Count + 1))
            except Exception:
                return False

        def threaded(occ):
            try:
                return occ.Definition.Features.ThreadFeatures.Count > 0
            except Exception:
                return False

        def cause(a, b):
            if (tapped(a) and threaded(b)) or (tapped(b) and threaded(a)):
                return "thread artifact: tapped hole modelled at the minor diameter"
            if tapped(a) or tapped(b):
                return "likely thread artifact: tapped hole, but the other part has no thread feature"
            return "real overlap"

        out = []
        for i in range(1, results.Count + 1):
            r = results.Item(i)
            a, b = r.OccurrenceOne, r.OccurrenceTwo
            c = r.Centroid
            out.append({"first": a.Name, "second": b.Name, "volume_mm3": round(r.Volume * 1000, 2),
                        "centroid_mm": [round(c.X * 10, 1), round(c.Y * 10, 1), round(c.Z * 10, 1)],
                        "cause": cause(a, b)})
        return out

    def pattern_component(self, occurrences: str, axis_occurrence: str, axis: str,
                          count: int, angle: float = 360) -> str:
        """Circular pattern of components (comma-separated names) about an axis selector,
        e.g. axis_occurrence "Flens:1", axis "axis:Z". angle is the total span in degrees."""
        import math
        ad = self.active_assembly().ComponentDefinition
        col = self.app.TransientObjects.CreateObjectCollection()
        # Names end in ":n" and may hold commas themselves ("DIN 125-1 A A 10,5:1").
        for name in re.findall(r"\s*(.+?:\d+)\s*(?:,|$)", occurrences):
            col.Add(self._occurrence(name))
        axis_entity = self._geometry(axis_occurrence, axis)
        step = angle / count if abs(angle - 360) < 1e-9 else angle / max(count - 1, 1)
        pattern = ad.OccurrencePatterns.AddCircularPattern(col, axis_entity, True, math.radians(step), count)
        return f"Pattern {pattern.Name}: {count} x [{occurrences}] every {step:g} deg"

    # ---------- Assembly drawings ----------

    _PARTS_LIST_LEVELS = {"parts": 46594, "structured": 46593, "all_levels": 46595}
    _ARROWHEADS = {"filled": 71941, "closed": 71940, "open": 71938, "dot": 71949, "none": 71948}

    def _view_curves(self, view, occurrence):
        """Drawing curves of one assembly component in a view."""
        # DrawingCurves takes the component as an argument of a property get, which late
        # binding cannot call directly.
        dispid = view._oleobj_.GetIDsOfNames("DrawingCurves")
        curves = win32com.client.Dispatch(
            view._oleobj_.Invoke(dispid, 0, pythoncom.DISPATCH_PROPERTYGET, True, occurrence))
        return [curves.Item(i) for i in range(1, curves.Count + 1)]

    def set_component_visibility(self, view: str, occurrences: str, visible: bool = False) -> str:
        """Show or hide assembly components in one drawing view only; the assembly and its
        design views are not changed. occurrences: comma-separated names."""
        v = self._view(view)
        model = v.ReferencedDocumentDescriptor.ReferencedDocument
        if model.DocumentType != 12291:
            raise ValueError(f"View {view} does not show an assembly")
        names = re.findall(r"\s*(.+?:\d+)\s*(?:,|$)", occurrences)
        found = {o.Name: o for o in self._components(model.ComponentDefinition)}
        done = []
        for name in names:
            occ = next((o for n, o in found.items() if self._same_name(n, name)), None)
            if occ is None:
                raise ValueError(f"No component {name!r} in {model.DisplayName}: {sorted(found)}")
            v.SetVisibility(occ, bool(visible))
            done.append(occ.Name)
        return (f"{'Shown' if visible else 'Hidden'} in {v.Name}: {', '.join(done)}; "
                f"view now {self._fmt_rect(self._view_rect(v))}")

    def add_parts_list(self, view: str, x: float = 0, y: float = 0, level: str = "parts",
                       hide: str = "") -> str:
        """Parts list of the view's assembly. Without x, y it sits on the title block, flush
        with the right border, as in the Arjuna drawings. (x, y) is its top right corner.
        hide: rows to leave out, by part number or file name, separated by ';' (an unused
        variant kept in the assembly, say); the rest are renumbered."""
        doc = self.active_drawing()
        sheet = doc.ActiveSheet
        v = self._view(view)
        lvl = self._PARTS_LIST_LEVELS.get(level.lower())
        if lvl is None:
            raise ValueError(f"level must be one of {', '.join(self._PARTS_LIST_LEVELS)}")
        pl = sheet.PartsLists.Add(v, self._sheet_point(x or 400, y or 200), lvl)
        settings = self._profile_of(doc).get("parts_list", {})
        heading = {"top": 46337, "bottom": 46338, "none": 46339}.get(settings.get("heading", ""))
        if heading:
            pl.HeadingPlacement = heading
        cols = pl.PartsListColumns
        widths = {k.upper(): w for k, w in settings.get("widths", {}).items()}
        for i in range(1, cols.Count + 1):
            if cols.Item(i).Title.upper() in widths:
                cols.Item(i).Width = widths[cols.Item(i).Title.upper()] / 10.0
        hidden = []
        for key in [k.strip().lower() for k in hide.split(";") if k.strip()]:
            rows = pl.PartsListRows
            match = None
            for i in range(1, rows.Count + 1):
                row = rows.Item(i)
                files = [os.path.basename(row.ReferencedFiles.Item(j).FullFileName).lower()
                         for j in range(1, row.ReferencedFiles.Count + 1)]
                if str(row.Item(3).Value).lower() == key or key in files or key + ".ipt" in files:
                    match = row
                    break
            if match is None:
                raise ValueError(f"No parts list row with part number or file {key!r}")
            match.Visible = False
            hidden.append(key)
        if hidden:
            pl.Renumber()
        r = self._rect(pl)
        if not (x or y):
            area = self._drawing_area(sheet)
            bottom = self._rect(sheet.TitleBlock)[3] if sheet.TitleBlock is not None else area[1]
            x, y = area[2], bottom + (r[3] - r[1])
        pl.Position = self._sheet_point(x, y)
        r = self._rect(pl)
        clashes = [o.Name for o in (sheet.DrawingViews.Item(i) for i in range(1, sheet.DrawingViews.Count + 1))
                   if self._overlap(r, self._view_rect(o))]
        rows = pl.PartsListRows
        items = [f"{rows.Item(i).Item(1).Value}: {rows.Item(i).Item(3).Value} x{rows.Item(i).Item(2).Value}"
                 for i in range(1, rows.Count + 1) if rows.Item(i).Visible]
        warn = f"; overlaps view {', '.join(clashes)}" if clashes else ""
        return f"Parts list {self._fmt_rect(r)}, {len(items)} items: {'; '.join(items)}{warn}"

    def add_balloons(self, view: str, gap: float = 12) -> str:
        """One balloon per parts list item visible in the view, in a row above or below it.

        Each balloon points at the longest edge that no other component shares, near its end
        on the balloon row's side, on the instance with the most edges in the view; balloons
        keep the x order of those points so leaders do not cross.
        gap: distance in mm between the view box and the balloon row.
        """
        doc = self.active_drawing()
        sheet = doc.ActiveSheet
        v = self._view(view)
        model = v.ReferencedDocumentDescriptor.ReferencedDocument
        if model.DocumentType != 12291:
            raise ValueError(f"View {view} shows a part; balloons need an assembly view")
        best = {}  # file -> (curve count, occurrence, curves)
        geometry = []  # (occurrence name, line ends or (center, radius)) of every visible edge
        for o in self._components(model.ComponentDefinition):
            try:
                curves = self._view_curves(v, o)
            except Exception:
                continue
            for c in curves:
                try:
                    segments = [c.Segments.Item(j).Geometry for j in range(1, c.Segments.Count + 1)]
                except Exception:
                    continue  # weld curves in a weldment view raise E_NOTIMPL
                for g in segments:
                    try:
                        geometry.append((o.Name, "arc", (g.Center.X, g.Center.Y), g.Radius, c))
                        continue
                    except Exception:
                        pass
                    try:
                        geometry.append((o.Name, "line", (g.StartPoint.X, g.StartPoint.Y),
                                         (g.EndPoint.X, g.EndPoint.Y), c))
                    except Exception:
                        pass  # ellipses and splines (chamfers seen edge-on) are skipped
            key = os.path.normcase(o.ReferencedDocumentDescriptor.FullDocumentName)
            if curves and len(curves) > best.get(key, (0,))[0]:
                best[key] = (len(curves), o, curves)

        def distance(px, py, kind, a, b):
            if kind == "arc":
                return abs(((px - a[0]) ** 2 + (py - a[1]) ** 2) ** 0.5 - b)
            vx, vy = b[0] - a[0], b[1] - a[1]
            t = max(0.0, min(1.0, ((px - a[0]) * vx + (py - a[1]) * vy) / ((vx * vx + vy * vy) or 1e-12)))
            return ((px - a[0] - t * vx) ** 2 + (py - a[1] - t * vy) ** 2) ** 0.5

        targets = []
        for key, (_, occ, curves) in best.items():
            # The longest straight edge whose midpoint no other component's edge touches,
            # so the arrow cannot be read as pointing at a neighbour (bolt head vs washer).
            own = [g for g in geometry if g[0] == occ.Name and g[1] == "line"]
            others = [g for g in geometry if g[0] != occ.Name]
            choice, fallback = None, None
            middle_y = v.Center.Y

            def rank(g):
                # Leaders run up or down to their row: a vertical edge would hide the leader
                # in its own line, so edges across the leader come first, then by length.
                dx, dy = abs(g[3][0] - g[2][0]), abs(g[3][1] - g[2][1])
                return (dx < 0.3 * dy, -(dx * dx + dy * dy))

            for _, _, a, b, c in sorted(own, key=rank):
                mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
                # Towards the end farther from the view's middle: the balloon row sits on
                # that side, so the leader stays short instead of crossing the view.
                end = a if abs(a[1] - middle_y) >= abs(b[1] - middle_y) else b
                outer = (mid[0] + 0.7 * (end[0] - mid[0]), mid[1] + 0.7 * (end[1] - mid[1]))
                fallback = fallback or (c, mid)
                for point in (outer, mid):
                    if all(distance(point[0], point[1], k, oa, ob) > 0.03 for _, k, oa, ob, _ in others):
                        choice = (c, point)
                        break
                if choice:
                    break
            curve, foot = choice or fallback or (curves[0], (curves[0].StartPoint.X, curves[0].StartPoint.Y))
            targets.append((occ, curve, foot[0] * 10, foot[1] * 10))
        if not targets:
            raise ValueError(f"No components visible in view {view}")

        box = self._view_rect(v)
        cy = (box[1] + box[3]) / 2
        area = self._drawing_area(sheet)
        diameter = self._balloon_diameter(
            doc.StylesManager.ActiveStandardStyle.ActiveObjectDefaults.BalloonStyle)
        step = diameter + 4
        label = self._rect(v.Label) if v.ShowLabel else None
        placed = []
        for row in ("above", "below"):
            group = sorted((t for t in targets if (t[3] >= cy) == (row == "above")), key=lambda t: t[2])
            if not group:
                continue
            xs = [t[2] for t in group]
            for k in range(1, len(xs)):  # spread to the right, then shift back to centre
                xs[k] = max(xs[k], xs[k - 1] + step)
            shift = (sum(t[2] for t in group) - sum(xs)) / len(xs)
            xs = [x + shift for x in xs]
            y = box[3] + gap + diameter / 2 if row == "above" else box[1] - gap - diameter / 2
            on_label_side = label is not None and ((label[1] >= cy) == (row == "above"))
            if on_label_side:
                # Leaders from a row past the label would cross its text, so the row sits
                # level with the label and the balloons step aside of it, keeping their order.
                y = (label[1] + label[3]) / 2
                left_edge, right_edge = label[0] - diameter / 2 - 3, label[2] + diameter / 2 + 3
                mid = (label[0] + label[2]) / 2
                left = [k for k, x in enumerate(xs) if x < mid]
                right = [k for k, x in enumerate(xs) if x >= mid]
                limit = left_edge + step
                for k in reversed(left):
                    xs[k] = limit = min(xs[k], limit - step)
                limit = right_edge - step
                for k in right:
                    xs[k] = limit = max(xs[k], limit + step)
            xs = [min(max(x, area[0] + step), area[2] - step) for x in xs]
            for (occ, curve, fx, fy), bx in zip(group, xs):
                points = self.app.TransientObjects.CreateObjectCollection()
                points.Add(self._sheet_point(bx, y))
                points.Add(sheet.CreateGeometryIntent(curve, self._sheet_point(fx, fy)))
                balloon = sheet.Balloons.Add(points)
                arrow = self._ARROWHEADS.get(self._profile_of(doc).get("balloon_arrowhead", ""))
                if arrow:
                    balloon.Leader.ArrowheadType = arrow
                item = balloon.BalloonValueSets.Item(1).ItemNumber
                placed.append((int(item) if str(item).isdigit() else 0, f"{item} {occ.Name} at ({bx:.0f}, {y:.0f})"))
        return f"{len(placed)} balloons on {view}: " + "; ".join(p for _, p in sorted(placed))

    # ---------- Exploded assemblies ----------
    # The presentation API cannot add tweaks or snapshot views in 2027, so an exploded
    # view is drawn from a copy of the assembly whose components are moved freely.

    def create_exploded_copy(self, assembly: str, path: str) -> str:
        """Copy an assembly to path with constraints and patterns removed, ready to explode.
        The copy uses the same part files; the original assembly is left untouched."""
        src = os.path.abspath(assembly)
        path = os.path.abspath(path)
        if os.path.normcase(src) == os.path.normcase(path):
            raise ValueError("path must differ from the assembly")
        for i in range(1, self.app.Documents.Count + 1):
            if os.path.normcase(self.app.Documents.Item(i).FullFileName) == os.path.normcase(path):
                raise RuntimeError(f"{path} is open in Inventor. Close it first.")
        doc = self._open_model(src)
        doc.SaveAs(path, True)  # save a copy; doc stays the original
        copy = self.app.Documents.Open(path, True)
        ad = copy.ComponentDefinition
        patterns = ad.OccurrencePatterns
        while patterns.Count:
            p = patterns.Item(patterns.Count)
            elements = p.OccurrencePatternElements
            for j in range(2, elements.Count + 1):  # element 1 holds the original components
                elements.Item(j).Independent = True
            p.Delete()
        constraints = ad.Constraints
        for i in range(constraints.Count, 0, -1):
            constraints.Item(i).Delete()
        copy.Update()
        copy.Save()
        self.pin_document(copy)
        log = os.path.splitext(path)[0] + ".explode.json"
        with open(log, "w", encoding="utf-8") as f:
            json.dump({"source": os.path.basename(src), "moves": []}, f, indent=1)
        return (f"Exploded copy {os.path.basename(path)}: {ad.Occurrences.Count} free components, "
                "constraints and patterns removed")

    @staticmethod
    def _center(occ):
        r = occ.RangeBox
        return [round((getattr(r.MinPoint, a) + getattr(r.MaxPoint, a)) / 2 * 10, 3) for a in "XYZ"]

    def explode_components(self, occurrences: str, dx: float = 0, dy: float = 0, dz: float = 0) -> str:
        """Move components of an exploded copy by (dx, dy, dz) mm in assembly coordinates."""
        doc = self.active_assembly()
        log_path = os.path.splitext(doc.FullFileName)[0] + ".explode.json"
        if not doc.FullFileName or not os.path.exists(log_path):
            raise RuntimeError("Active assembly is not an exploded copy; use create_exploded_copy first")
        if doc.ComponentDefinition.Constraints.Count:
            raise RuntimeError("The assembly still has constraints, which would pull components back")
        tg = self._tg()
        names = re.findall(r"\s*(.+?:\d+)\s*(?:,|$)", occurrences)
        if not names:
            raise ValueError("occurrences: comma-separated component names such as 'Flens:2, Poros:2'")
        with open(log_path, encoding="utf-8") as f:
            log = json.load(f)
        moved = []
        for name in names:
            occ = self._occurrence(name)
            before = self._center(occ)
            m = occ.Transformation
            t = m.Translation
            m.SetTranslation(tg.CreateVector(t.X + dx / 10, t.Y + dy / 10, t.Z + dz / 10))
            occ.Transformation = m
            log["moves"].append({"component": occ.Name, "from_mm": before, "to_mm": self._center(occ),
                                 "move_mm": [dx, dy, dz]})
            moved.append(occ.Name)
        doc.Update()
        with open(log_path, "w", encoding="utf-8") as f:
            json.dump(log, f, indent=1, ensure_ascii=False)
        return f"Moved {len(moved)} by ({dx:g}, {dy:g}, {dz:g}) mm: {', '.join(moved)}"

    def add_explode_trails(self, view: str) -> str:
        """Thin chain lines from each exploded component back to where it was assembled,
        merged per straight path, drawn in a sketch of the view."""
        v = self._view(view)
        model = v.ReferencedDocumentDescriptor.ReferencedDocument
        log_path = os.path.splitext(model.FullFileName)[0] + ".explode.json"
        if not os.path.exists(log_path):
            raise ValueError(f"View {view} does not show an exploded copy")
        with open(log_path, encoding="utf-8") as f:
            moves = json.load(f)["moves"]
        # A component moved twice keeps its first start and its last end.
        paths = {}
        for m in moves:
            start = paths.get(m["component"], (m["from_mm"],))[0]
            paths[m["component"]] = (start, m["to_mm"])
        tg = self._tg()
        segments = []
        for start, end in paths.values():
            a = v.ModelToSheetSpace(tg.CreatePoint(*(c / 10 for c in start)))
            b = v.ModelToSheetSpace(tg.CreatePoint(*(c / 10 for c in end)))
            if ((a.X - b.X) ** 2 + (a.Y - b.Y) ** 2) ** 0.5 > 0.05:
                segments.append(((a.X, a.Y), (b.X, b.Y)))
        # Collinear overlapping segments (one bolt line) become one line.
        merged = []
        for a, b in segments:
            for k, (c, d) in enumerate(merged):
                ux, uy = d[0] - c[0], d[1] - c[1]
                n = (ux * ux + uy * uy) ** 0.5
                off = lambda p: abs((p[0] - c[0]) * uy - (p[1] - c[1]) * ux) / n
                if off(a) < 0.02 and off(b) < 0.02:
                    pts = sorted([a, b, c, d], key=lambda p: (p[0] - c[0]) * ux + (p[1] - c[1]) * uy)
                    merged[k] = (pts[0], pts[-1])
                    break
            else:
                merged.append((a, b))
        sketch = v.Sketches.Add()
        sketch.Edit()
        try:
            for a, b in merged:
                line = sketch.SketchLines.AddByTwoPoints(
                    sketch.SheetToSketchSpace(tg.CreatePoint2d(*a)), sketch.SheetToSketchSpace(tg.CreatePoint2d(*b)))
                line.LineType = 37644  # kChainLineType
                line.LineWeight = 0.025
        finally:
            sketch.ExitEdit()
        return f"{len(merged)} trail line(s) on {view} for {len(paths)} moved component(s)"

    def _seat_face(self, proxy, k: int):
        """(coordinate in mm along assembly axis k, outward side +1/-1 or None) of the face a
        constraint geometry sits on: the planar face of a circular edge, or a planar face."""
        faces = [proxy]
        try:
            faces = [proxy.Faces.Item(i) for i in range(1, proxy.Faces.Count + 1)]
        except Exception:
            pass
        for f in faces:
            try:
                if f.SurfaceType != 5890:
                    continue
                p = f.PointOnFace
                normal = f.Evaluator.GetNormalAtPoint([p.X, p.Y, p.Z], [0.0, 0.0, 0.0])[1]
                if abs(normal[k]) > 0.5:  # the evaluator gives the outward normal
                    return (p.X, p.Y, p.Z)[k] * 10, (1 if normal[k] > 0 else -1)
            except Exception:
                continue
        for get in (lambda g: g.Geometry.Center, lambda g: g.Plane.RootPoint, lambda g: g.Line.RootPoint):
            try:
                p = get(proxy)
                return (p.X, p.Y, p.Z)[k] * 10, None
            except Exception:
                continue
        raise ValueError("Cannot locate the constraint geometry")

    def auto_explode(self, spacing: float = 20, axis: str = "Z") -> str:
        """Explode the active exploded copy along one assembly axis, from the constraint log
        of the assembly it was copied from.

        Each component moves away from the component it was constrained to (its first insert
        or mate), off the outward side of the face it sits on, far enough to clear it (a bolt
        by the length inside its washer and flanges) plus spacing; moves add up along the chain.
        Pattern instances follow the original at the same height. Components with no such
        constraint, e.g. the grounded one, stay.
        """
        k = {"X": 0, "Y": 1, "Z": 2}.get(axis.upper())
        if k is None:
            raise ValueError("axis must be X, Y or Z")
        doc = self.active_assembly()
        log_path = os.path.splitext(doc.FullFileName)[0] + ".explode.json"
        if not os.path.exists(log_path):
            raise RuntimeError("Active assembly is not an exploded copy; use create_exploded_copy first")
        with open(log_path, encoding="utf-8") as f:
            explode_log = json.load(f)
        if explode_log["moves"]:
            raise RuntimeError("Components were moved already; auto_explode needs a fresh exploded copy")
        source = os.path.join(os.path.dirname(doc.FullFileName), explode_log["source"])
        constraint_log = os.path.splitext(source)[0] + ".constraints.json"
        if not os.path.exists(constraint_log):
            raise RuntimeError(f"No constraint log {os.path.basename(constraint_log)}: the assembly must "
                               "be built with add_constraint and saved with save_document")
        with open(constraint_log, encoding="utf-8") as f:
            steps = json.load(f)["constraints"]

        span, files = {}, {}
        for o in self._components(doc.ComponentDefinition):
            r = o.RangeBox
            span[o.Name] = ((r.MinPoint.X, r.MinPoint.Y, r.MinPoint.Z)[k] * 10,
                            (r.MaxPoint.X, r.MaxPoint.Y, r.MaxPoint.Z)[k] * 10)
            files[o.Name] = os.path.normcase(o.ReferencedDocumentDescriptor.FullDocumentName)
        names = {" ".join(n.lower().split()): n for n in span}

        def real(name):
            return names.get(" ".join(name.lower().split()))

        seat = {}  # component -> (parent, face coordinate along the axis)
        for step in steps:
            child, parent = real(step["second"]["component"]), real(step["first"]["component"])
            if step["kind"] in ("insert", "mate") and child and parent and child not in seat and child != parent:
                seat[child] = (parent, *self._seat_face(self._geometry(parent, step["first"]["geometry"]), k))

        moves = {}

        def move_of(name, depth=0):
            if name in moves:
                return moves[name]
            if name not in seat or depth > 50:
                moves[name] = 0.0
                return 0.0
            parent, face, side = seat[name]
            lo, hi = span[parent]
            # Off the outward side of the seat face; a work plane has no side, so use the
            # side of the parent's middle it lies on.
            sign = side or (1 if face >= (lo + hi) / 2 else -1)
            c_lo, c_hi = span[name]
            depth_in = max(0.0, face - c_lo) if sign > 0 else max(0.0, c_hi - face)
            moves[name] = move_of(parent, depth + 1) + sign * (depth_in + spacing)
            return moves[name]

        for name in span:
            move_of(name)
        # Pattern instances were never constrained: copy the move of the constrained
        # component made from the same file at the same height along the axis.
        followed = []
        for name in span:
            if name in seat or moves[name]:
                continue
            mid = sum(span[name]) / 2
            twin = next((s for s in seat if files[s] == files[name] and abs(sum(span[s]) / 2 - mid) < 0.5), None)
            if twin:
                moves[name] = moves[twin]
                followed.append(name)

        groups = {}
        for name, d in moves.items():
            if abs(d) > 1e-6:
                groups.setdefault(round(d, 3), []).append(name)
        vector = [0.0, 0.0, 0.0]
        for d, group in sorted(groups.items()):
            vector[k] = d
            self.explode_components(", ".join(group), *vector)
        still = [n for n, d in moves.items() if abs(d) <= 1e-6]
        lines = [f"{d:+g} mm: {', '.join(g)}" for d, g in sorted(groups.items())]
        return (f"Exploded along {axis.upper()}, spacing {spacing:g} mm. " + " | ".join(lines)
                + f" | stays: {', '.join(still) or 'none'}")

    # ---------- Editing drawings and model properties ----------

    def move_view(self, view: str, x: float = 0, y: float = 0, scale: float = 0) -> str:
        """Move a view's centre to (x, y) sheet mm and/or give it a new scale. A result that
        would leave the border or overlap something is undone and reported."""
        sheet = self.active_drawing().ActiveSheet
        v = self._view(view)
        old_center, old_scale = v.Center, v.Scale
        if scale:
            try:
                v.ScaleFromBase = False  # a projected view otherwise keeps its parent's scale
            except Exception:
                pass
            v.Scale = scale
        if x or y:
            v.Center = self._sheet_point(x, y)
        rect = self._view_rect(v)
        area = self._drawing_area(sheet)
        problems = []
        if rect[0] < area[0] or rect[1] < area[1] or rect[2] > area[2] or rect[3] > area[3]:
            problems.append("outside the border")
        if sheet.TitleBlock is not None and self._overlap(rect, self._rect(sheet.TitleBlock)):
            problems.append("overlaps the title block")
        for i in range(1, sheet.DrawingViews.Count + 1):
            other = sheet.DrawingViews.Item(i)
            if other.Name != v.Name and self._overlap(rect, self._view_rect(other)):
                problems.append(f"overlaps view {other.Name}")
        for i in range(1, sheet.PartsLists.Count + 1):
            if self._overlap(rect, self._rect(sheet.PartsLists.Item(i))):
                problems.append("overlaps the parts list")
        if problems:
            if scale:
                v.Scale = old_scale
            v.Center = old_center
            raise ValueError(f"View {view} would sit at {self._fmt_rect(rect)}: {'; '.join(problems)}. Left as it was.")
        return f"View {v.Name}: scale {v.Scale:g}, {self._fmt_rect(rect)}"

    def delete_view(self, view: str) -> str:
        """Delete a view. Views projected or cut from it go with it, as in Inventor."""
        sheet = self.active_drawing().ActiveSheet
        v = self._view(view)
        before = {sheet.DrawingViews.Item(i).Name for i in range(1, sheet.DrawingViews.Count + 1)}
        v.Delete()
        after = {sheet.DrawingViews.Item(i).Name for i in range(1, sheet.DrawingViews.Count + 1)}
        return f"Deleted views: {', '.join(sorted(before - after))}"

    def _notes(self, sheet):
        notes = []
        for kind, collection in (("hole", sheet.DrawingNotes.HoleThreadNotes),
                                 ("chamfer", sheet.DrawingNotes.ChamferNotes)):
            for i in range(1, collection.Count + 1):
                notes.append((kind, collection.Item(i)))
        return notes

    def list_notes(self) -> list[dict]:
        """Hole and chamfer notes on the active sheet with an index for delete_note."""
        out = []
        for k, (kind, note) in enumerate(self._notes(self.active_drawing().ActiveSheet), 1):
            text = note.Text.Text if kind == "hole" else note.Text
            r = self._rect(note.Text) if kind == "hole" else self._rect(note)
            out.append({"index": k, "kind": kind, "text": text.replace("\n", " / "),
                        "center_mm": [round((r[0] + r[2]) / 2, 1), round((r[1] + r[3]) / 2, 1)]})
        return out

    def delete_note(self, indices: str) -> str:
        """Delete hole or chamfer notes by index from list_notes, e.g. to place them again."""
        notes = self._notes(self.active_drawing().ActiveSheet)
        picked = sorted({int(i) for i in indices.split(",") if i.strip()}, reverse=True)
        for i in picked:
            if not 1 <= i <= len(notes):
                raise ValueError(f"No note {i}; list_notes shows {len(notes)}")
        for i in picked:
            notes[i - 1][1].Delete()
        return f"Deleted {len(picked)} note(s)"

    # Names people use for iProperties, mapped to (property set, property name).
    _PROPERTIES = {
        "PART NUMBER": ("Design Tracking Properties", "Part Number"),
        "DESCRIPTION": ("Design Tracking Properties", "Description"),
        "STOCK NUMBER": ("Design Tracking Properties", "Stock Number"),
        "VENDOR": ("Design Tracking Properties", "Vendor"),
        "PROJECT": ("Design Tracking Properties", "Project"),
        "DESIGNER": ("Design Tracking Properties", "Designer"),
        "ENGINEER": ("Design Tracking Properties", "Engineer"),
        "CHECKED BY": ("Design Tracking Properties", "Checked By"),
        "REVISION NUMBER": ("Inventor Summary Information", "Revision Number"),
        "TITLE": ("Inventor Summary Information", "Title"),
        "SUBJECT": ("Inventor Summary Information", "Subject"),
        "AUTHOR": ("Inventor Summary Information", "Author"),
        "COMMENTS": ("Inventor Summary Information", "Comments"),
    }

    def set_properties(self, model_path: str, fields: dict) -> str:
        """Write iProperties of a part or assembly file and save it, e.g. Part Number and
        Description, which BOMs and parts lists read. Other names become custom properties.
        MATERIAL sets a part's material from the active library."""
        path = os.path.abspath(model_path)
        doc = self._open_model(path)
        if doc.DocumentType not in (12290, 12291):
            raise ValueError("set_properties works on .ipt and .iam files")
        written = []
        for key, value in fields.items():
            name = key.replace("_", " ").strip().upper()
            if name == "MATERIAL":
                self._set_material(doc, str(value))
            elif name in self._PROPERTIES:
                set_name, prop = self._PROPERTIES[name]
                doc.PropertySets.Item(set_name).Item(prop).Value = str(value)
            else:
                custom = doc.PropertySets.Item("Inventor User Defined Properties")
                try:
                    custom.Item(key).Value = str(value)
                except Exception:
                    custom.Add(str(value), key)
            written.append(name)
        doc.Save()
        return f"{os.path.basename(path)}: {', '.join(written)} written and saved"

    # ---------- Weldments ----------
    # Inventor 2027's API cannot create weld beads (fillet or groove welds as solids):
    # WeldBeads has no Add. It can create cosmetic welds on edges and welding symbols on
    # drawings, which is what a weld drawing needs.

    WELDMENT_TEMPLATE = "builtin:Metric/Weldment (ISO).iam"
    _WELD_STATES = {"assembly": 80897, "machining": 80898, "welds": 80899, "preparations": 80900}
    _WELD_KINDS = {
        "fillet": 124162, "plug": 124163, "slot": 124164, "stud": 124165, "spot": 124166,
        "seam": 124169, "back": 124172, "surfacing": 124173, "square": 124176, "i_butt": 124176,
        "scarf": 124177, "v": 124178, "v_butt": 124178, "bevel": 124179, "u": 124181,
        "j": 124182, "flare_v": 124184, "flare_bevel": 124185,
    }

    @staticmethod
    def _is_weldment(doc) -> bool:
        try:
            return doc.DocumentType == 12291 and doc.ComponentDefinition.Welds is not None
        except Exception:
            return False

    def create_weldment(self, template: str = "") -> str:
        """New weldment assembly; place and constrain parts with the assembly tools."""
        out = self.create_assembly(template or self.WELDMENT_TEMPLATE)
        if not self._is_weldment(self.active_document()):
            raise RuntimeError(f"{template} did not make a weldment; use a 'Weldment' template")
        return out.replace("Assembly created", "Weldment created")

    def add_cosmetic_weld(self, occurrence: str, edges: str, leg: float = 0) -> str:
        """Cosmetic weld along edges of one component, e.g. the two edges where an upright
        plate meets a base plate. edges: edge selectors separated by ';'. leg: fillet leg in
        mm; its area (leg^2 / 2) counts in the weldment's mass."""
        doc = self.active_assembly()
        if not self._is_weldment(doc):
            raise ValueError("The active assembly is not a weldment; start with create_weldment")
        welds = doc.ComponentDefinition.Welds
        collection = self.app.TransientObjects.CreateEdgeCollection()
        selectors = [s.strip() for s in edges.split(";") if s.strip()]
        if not selectors:
            raise ValueError("edges: one or more edge selectors separated by ';'")
        for sel in selectors:
            collection.Add(self._geometry(occurrence, sel))
        welds.Edit()
        try:
            definition = welds.CosmeticWelds.CreateDefinition(collection)
            if leg:
                definition.Area = f"{leg * leg / 2:g} mm^2"  # an expression string, not a Parameter
            weld = welds.CosmeticWelds.Add(definition)
        finally:
            welds.ExitEdit()
        doc.Update()
        return f"{weld.Name} on {len(selectors)} edge(s) of {occurrence}" + (f", leg {leg:g} mm" if leg else "")

    def add_weld_symbol(self, view: str, x: float, y: float, text_x: float, text_y: float,
                        kind: str = "fillet", size: str = "", length: str = "", sides: str = "arrow",
                        all_around: bool = False, field: bool = False, tail: str = "",
                        attach: bool = True) -> str:
        """ISO welding symbol with its arrow on the curve nearest (x, y) of a view.

        sides: "arrow" (weld on the arrow side: symbol on the full reference line, dashed
        identification line under it), "other" (symbol on the dashed line), "both"
        (symmetrical: symbol on both sides, no dashed line). size e.g. "a4" (throat) or "z5"
        (leg) for fillets, "s8" for butt welds; length e.g. "50" or "3x50(100)" for
        intermittent welds. tail: process or note, e.g. "135". Points are model mm from the
        view center."""
        sheet = self.active_drawing().ActiveSheet
        v = self._view(view)
        code = self._WELD_KINDS.get(kind.lower())
        if code is None:
            raise ValueError(f"Unknown weld kind {kind}. Use {', '.join(self._WELD_KINDS)}.")
        sides = sides.lower()
        if sides not in ("arrow", "other", "both"):
            raise ValueError('sides must be "arrow", "other" or "both"')
        definitions = sheet.WeldingSymbols.CreateDefinitions()
        definition = definitions.Add(1)
        symbols = [definition.WeldSymbolOne] + ([definition.WeldSymbolTwo] if sides == "both" else [])
        for symbol in symbols:
            symbol.WeldSymbolType = code
            if size:
                # The size sits in a different field per kind: fillets take SizeOrStrength,
                # butt welds PenetrationDepth, spot welds Diameter.
                for field_name in ("SizeOrStrength", "PenetrationDepth", "Diameter", "Width"):
                    try:
                        setattr(symbol, field_name, size)
                        break
                    except Exception:
                        continue
                else:
                    raise ValueError(f"A {kind} weld symbol takes no size")
            if length:
                symbol.Length = length
        # ISO 2553 system A: the full line is the arrow side, the dashed one the other side.
        definition.IdentificationLinePlacement = {"arrow": 122883, "other": 122882, "both": 122881}[sides]
        definition.AllAroundSymbol = bool(all_around)
        definition.FieldWeldingSymbol = bool(field)
        if tail:
            definition.TailNote = tail
        points, miss = self._leader_points(v, x, y, text_x, text_y, attach)
        sheet.WeldingSymbols.Add(points, definitions)
        return (f"{kind} weld symbol {size} {length}".rstrip() + f", {sides} side(s), in {v.Name} "
                f"{self._where(miss)}")
