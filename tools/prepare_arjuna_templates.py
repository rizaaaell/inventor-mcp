"""Make the Arjuna templates usable in this Inventor release.

Run from the repo root:  python -X utf8 -u tools/prepare_arjuna_templates.py

For every .idw in references/templates/ it writes references/templates/2027/<name>:
a copy opened and saved once in this Inventor (older templates make Documents.Add
fail), with a DOCUMENT TYPE prompt added under the "DOCUMENT TYPE:" label when the
title block has the label but no field. The originals are not touched.

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


# Fields whose values outgrow their box at the template's 2.5 mm, e.g. "Rachmadi Norcahyo"
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
