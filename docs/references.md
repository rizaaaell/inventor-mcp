# Reference material

Team material that guides the drawings lives in `references/` at the repo root. The
folder is in `.gitignore` and must stay out of git: the GitHub fork is public, and the
material is Arjuna's.

| Folder | Holds | Used for |
|---|---|---|
| `references/standar/` | drawing standards and course material (PDF) | rules for view choice, dimensioning, tolerances, title block content |
| `references/baseline/` | Arjuna's 2024 FSAE Japan supplement drawings (PDF) | the bar Claude's drawings are compared against |
| `references/templates/` | Arjuna `.idw` templates and `.styxml` style exports, as received | source of the team look |
| `references/templates/2027/` | copies of the templates opened and saved in Inventor 2027 | the `template` of the default drawing profile |

How each is used:

- Standards are distilled into rules in the drawing skill (phase 6) and, where a rule
  is a setting, into a profile in `drawing_profiles/`. The source stays here.
- Baseline drawings set the profile and the layout habits: third angle, one decimal
  with comma and no trailing zeros, "A-A ( 1 : 1 )" section titles, letter-only section
  marks, full-length centerlines, an isometric view in a free corner.
- Templates from an older Inventor release must be opened and saved once in 2027
  before use; the originals stay untouched, the migrated copies go to `2027/`.

PDF pages are rendered with Windows' own PDF engine, no extra install:

```powershell
powershell -File tools\pdf2png.ps1 -Pdf "references\baseline\<file>.pdf" -OutDir <folder> -MaxPages 3
```

The resulting PNG files can be opened with the Read tool.
