"""Make the Arjuna templates usable in this Inventor release.

Run from the repo root:  python -X utf8 -u tools/prepare_arjuna_templates.py

For every .idw in references/templates/ it writes references/templates/2027/<name>:
a copy opened and saved once in this Inventor (older templates make Documents.Add
fail), with a DOCUMENT TYPE prompt added under the "DOCUMENT TYPE:" label when the
title block has the label but no field, every value centred in its cell, and MATERIAL as
a prompt.
The originals are not touched.

The Arjuna style exports (*.styxml) still have to be imported by hand afterwards,
see docs/drawing-profiles.md; the Inventor API has no import call for them. A template
already in 2027/ is updated in place so those imports survive; --force copies it again
from the original and drops them.
"""

import os
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.inventor_api import InventorConnection  # noqa: E402

SRC = Path(__file__).resolve().parents[1] / "references" / "templates"
DST = SRC / "2027"


def add_document_type_field(doc) -> str:
    definition = doc.ActiveSheet.TitleBlock.Definition
    boxes = definition.Sketch.TextBoxes
    texts = [boxes.Item(i) for i in range(1, boxes.Count + 1)]
    if any("<Prompt" in t.FormattedText and "DOCUMENT TYPE" in t.Text.upper() for t in texts):
        return "DOCUMENT TYPE field already there"
    label = next((t for t in texts if t.Text.strip().upper() == "DOCUMENT TYPE:"), None)
    if label is None:
        return "no DOCUMENT TYPE label, left as is"
    tg = doc.Parent.TransientGeometry
    # The value sits 6 mm under its label, as REV and PART NUMBER do in this block.
    position = tg.CreatePoint2d(label.Origin.X + 0.2, label.Origin.Y - 0.6)
    sketch = definition.Edit()
    try:
        sketch.TextBoxes.AddFitted(
            position, "<StyleOverride FontSize='0,2'><Prompt>DOCUMENT TYPE</Prompt></StyleOverride>")
    finally:
        definition.ExitEdit(True)
    return "DOCUMENT TYPE field added"


# Fields whose values outgrow their box at the template's 2.5 mm, e.g. a 17-character approver name
# (17 characters) in the 24 mm APPROVED BY box wraps onto the label.
SMALL_FIELDS = ("ENGINEER", "CHECKED BY", "DOCUMENT TYPE")


def shrink_long_fields(doc, size_cm: float = 0.2) -> str:
    definition = doc.ActiveSheet.TitleBlock.Definition
    sketch = definition.Edit()
    changed = []
    try:
        boxes = [sketch.TextBoxes.Item(i) for i in range(1, sketch.TextBoxes.Count + 1)]
        # FormattedText takes the decimal mark the document already uses; the other one is refused.
        comma = any(re.search(r"FontSize='\d+,", t.FormattedText) for t in boxes)
        size = f"{size_cm:g}".replace(".", "," if comma else ".")
        for t in boxes:
            name = t.Text.strip().strip("<>").upper()
            if name in SMALL_FIELDS and f"FontSize='{size}'" not in t.FormattedText:
                t.FormattedText = re.sub(r"FontSize='[^']*'", f"FontSize='{size}'", t.FormattedText)
                changed.append(name)
    finally:
        definition.ExitEdit(True)
    return f"font {size_cm:g} cm on {', '.join(changed)}" if changed else "field fonts already small"


def _cell(sketch, x: float, y: float):
    """(left, right, bottom, top) in cm of the title block cell around (x, y)."""
    xs, ys = [], []
    for i in range(1, sketch.SketchLines.Count + 1):
        line = sketch.SketchLines.Item(i)
        a, b = line.StartSketchPoint.Geometry, line.EndSketchPoint.Geometry
        if abs(a.X - b.X) < 1e-4 and min(a.Y, b.Y) <= y <= max(a.Y, b.Y):
            xs.append(a.X)
        if abs(a.Y - b.Y) < 1e-4 and min(a.X, b.X) <= x <= max(a.X, b.X):
            ys.append(a.Y)
    return (max(v for v in xs if v < x), min(v for v in xs if v > x),
            max(v for v in ys if v < y), min(v for v in ys if v > y))


def _font_cm(box, default: float = 0.25) -> float:
    m = re.search(r"FontSize='(\d+[.,]?\d*)'", box.FormattedText)
    return float(m.group(1).replace(",", ".")) if m else default


def _is_value(box) -> bool:
    """A field, or a short fixed value such as "mm"; labels end with a colon."""
    if re.search(r"<(Prompt|Property|DerivedProperty)", box.FormattedText):
        return True
    text = box.Text.strip()
    return bool(text) and ":" not in text and " " not in text


def center_fields(doc) -> str:
    """Centre every value of the title block in its cell, horizontally and vertically.

    A cell with a label ("REV:", "MATERIAL:") keeps the label at the top left; the value is
    centred in the space under it. The label's box can be taller than its text, so the text
    height comes from its font size and line count.
    """
    definition = doc.ActiveSheet.TitleBlock.Definition
    sketch = definition.Edit()
    moved = []
    try:
        boxes = [sketch.TextBoxes.Item(i) for i in range(1, sketch.TextBoxes.Count + 1)]
        labels = [b for b in boxes if not _is_value(b)]
        tg = doc.Parent.TransientGeometry
        for value in (b for b in boxes if _is_value(b)):
            # A value with a label of its own name ("DOCUMENT TYPE:") belongs in the label's
            # cell, even when it was first placed below it, in the next row.
            name = value.Text.strip().strip("<>").upper()
            own = next((lb for lb in labels if lb.Text.strip().rstrip(":").strip().upper() == name), None)
            x, y = (own.Origin.X + 0.3, own.Origin.Y - 0.2) if own else (value.Origin.X, value.Origin.Y)
            try:
                left, right, bottom, top = _cell(sketch, x, y)
            except ValueError:
                continue  # not inside a closed cell
            inside = [lb for lb in labels if left <= lb.Origin.X < right and bottom < lb.Origin.Y <= top + 0.05]
            ceiling = top
            if inside:
                label = max(inside, key=lambda lb: lb.Origin.Y)
                lines = label.Text.count("\n") + 1
                ceiling = min(top, label.Origin.Y - lines * _font_cm(label) * 1.6)
            value.HorizontalJustification = 19969  # kAlignTextCenter
            value.VerticalJustification = 25601  # kAlignTextMiddle
            value.Origin = tg.CreatePoint2d((left + right) / 2, (bottom + ceiling) / 2)
            moved.append(value.Text.strip().strip("<>")[:16])
    finally:
        definition.ExitEdit(True)
    return f"centred {len(moved)} values"


def material_prompt(doc) -> str:
    """Turn the MATERIAL field into a prompt.

    It read the model's Material iProperty, which is read-only and has nothing to say for an
    assembly; as a prompt the tools can write a material, NONE, or a statement for mixed
    materials.
    """
    definition = doc.ActiveSheet.TitleBlock.Definition
    sketch = definition.Edit()
    try:
        for i in range(1, sketch.TextBoxes.Count + 1):
            t = sketch.TextBoxes.Item(i)
            if "<Property" in t.FormattedText and ">MATERIAL<" in t.FormattedText:
                t.FormattedText = re.sub(r"<Property [^>]*>MATERIAL</Property>", "<Prompt>MATERIAL</Prompt>",
                                         t.FormattedText)
                return "MATERIAL is a prompt"
            if "<Prompt" in t.FormattedText and "MATERIAL" in t.Text.upper():
                return "MATERIAL already a prompt"
    finally:
        definition.ExitEdit(True)
    return "no MATERIAL field"


def _find(collection, name):
    for i in range(1, collection.Count + 1):
        if collection.Item(i).Name == name:
            return collection.Item(i)
    return None


def _copy(collection, source_name: str, new_name: str):
    existing = _find(collection, new_name)
    if existing is not None:
        return existing
    return _find(collection, source_name).Copy(new_name)


def arjuna_standard(doc) -> str:
    """Give the imported Arjuna styles names the style library does not have.

    New drawings replace any style whose name the library also has (Object Defaults
    (ISO), General (ISO), Note Text (ISO)) with the library's version, so the imported
    leader and text settings and the Arjuna defaults would be lost. Copies under new
    names survive, and "Arjuna Standard" ties them together.
    """
    sm = doc.StylesManager
    arjuna = _find(sm.DimensionStyles, "Arjuna")
    if arjuna is None:
        return "no Arjuna dimension style imported yet, standard left as is"
    text = _copy(sm.TextStyles, "Note Text (ISO)", "Arjuna Note Text")
    leader = _copy(sm.LeaderStyles, "General (ISO)", "Arjuna Leader")
    try:
        leader.TextStyle = text
    except Exception:
        pass
    arjuna.TextStyle = text
    base = sm.ActiveStandardStyle
    defaults = _copy(sm.ObjectDefaultsStyles, base.ActiveObjectDefaults.Name, "Arjuna Object Defaults")
    for attr in ("LinearDimensionStyle", "DiameterDimensionStyle", "RadialDimensionStyle",
                 "AngularDimensionStyle", "BaselineDimensionStyle", "OrdinateDimensionStyle",
                 "OrdinateSetDimensionStyle", "LeaderTextStyle", "HoleNoteStyle", "ThreadNoteStyle",
                 "ChamferNoteStyle", "HoleTagStyle", "BendNoteStyle", "PunchNoteStyle"):
        setattr(defaults, attr, arjuna)
    defaults.SketchedSymbolLeaderStyle = leader
    defaults.SketchedSymbolTextStyle = text
    defaults.GeneralNoteStyle = text
    standard = _copy(sm.StandardStyles, base.Name, "Arjuna Standard")
    standard.ActiveObjectDefaults = defaults
    standard.FirstAngleProjection = False
    sm.ActiveStandardStyle = standard
    return "Arjuna Standard active (Arjuna dimensions, Arjuna Leader, Arjuna Note Text)"


def main():
    inv = InventorConnection()
    print(inv.connect())
    app = inv.app
    DST.mkdir(exist_ok=True)
    force = "--force" in sys.argv
    for src in sorted(SRC.glob("*.idw")):
        dst = DST / src.name
        for doc in list(app.Documents):
            if doc.FullFileName and os.path.normcase(doc.FullFileName) == os.path.normcase(str(dst)):
                doc.Close(True)
        fresh = force or not dst.exists()
        if fresh:
            shutil.copy2(src, dst)  # an existing copy keeps its imported styles
        app.SilentOperation = True
        doc = None
        try:
            doc = app.Documents.Open(str(dst), False)
            note = ("migrated, " if fresh else "kept, ") + add_document_type_field(doc)
            note += ", " + shrink_long_fields(doc)
            note += ", " + center_fields(doc)
            note += ", " + material_prompt(doc)
            note += ", " + arjuna_standard(doc)
            doc.Save()
            print(f"OK   {src.name}: {note}")
        except Exception as exc:
            print(f"FAIL {src.name}: {exc}")
        finally:
            if doc is not None:
                doc.Close(True)
            app.SilentOperation = False


if __name__ == "__main__":
    main()
