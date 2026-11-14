# Reference material

Team material that guides the drawings lives in `references/` at the repo root. The
folder is in `.gitignore` and must stay out of git: the GitHub fork is public, and the
material is Arjuna's.

| Folder | Holds | Used for |
|---|---|---|
| `references/standar/` | drawing standards and course material (PDF, images, notes) | rules for view choice, dimensioning, tolerances, title block content |
| `references/baseline/` | last year's Arjuna drawings (`.idw` with their models, or PDF) | the bar Claude's drawings are compared against |
| `references/templates/` | Arjuna `.idw` templates and style library files | the `template` of the Arjuna drawing profile |

How each is used:

- Standards are distilled into rules in the drawing skill (phase 6) and, where a rule
  is a setting, into a profile in `drawing_profiles/`. The source stays here.
- Baseline `.idw` files are opened in Inventor and read through the API (views,
  scales, dimension styles, title block fields) to fix the profile and the layout
  habits. PDF and images are read page by page.
- Templates from an older Inventor release must be opened and saved once in 2027
  before use; work on a copy in `references/templates/`, not on the team's original.

PDF pages can only be read once a PDF renderer is installed on this machine
(poppler's `pdftoppm`); images (PNG, JPG) and `.idw` files can be read already.
