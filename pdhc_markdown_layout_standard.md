# PDHC Markdown Layout Standard (Repo-Agnostic)

This document defines a **formal, reusable standard** for producing markdown documentation that renders as clean, scannable, “documentation-like” pages in common viewers (GitHub, IDE markdown preview, and typical static-site markdown renderers).

It is intentionally **not** literal CSS. Instead, it specifies **structure, rhythm, and formatting conventions** that create a consistent reading experience across repositories.

---

## 1) Scope and goals

### 1.1 Scope

This standard applies to markdown documentation intended to be read by engineers, designers, product stakeholders, and operators, including:

- Architecture and system overviews
- API documentation and endpoint inventories
- Data model and field references
- Process and workflow documentation

### 1.2 Goals

- **High scannability**: readers can skim headings and bold labels to find what they need.
- **Low cognitive load**: information is chunked into predictable blocks.
- **Cross-renderer consistency**: uses widely supported markdown patterns (no custom extensions required).
- **Referenceability**: stable section numbering enables precise discussion (“see 4.2”).

### 1.3 Non-goals

- Defining brand UI styles (colors, fonts, components) for actual UIs.
- Requiring a specific static-site generator or markdown flavor.
- Enforcing strict content schemas beyond the layout rules below.

---

## 2) Document structure requirements

### 2.1 Single primary title

- Each document MUST start with exactly one **H1** title using `#`.
- The H1 is the page title; do not use multiple H1s.

**Example**

```md
# Plan Definition Service
```

### 2.2 Chapter segmentation

- Major chapters MUST be separated with a horizontal rule:
  - Use `---` on its own line.
- The separation acts as a “visual chapter break” for fast scrolling.

### 2.3 Progressive disclosure ordering

Documents SHOULD follow this sequencing where applicable:

- **Vocabulary / definitions first**
- **Concept relationships second**
- **Workflows and pipelines third**
- **API endpoints and operational details last**

This ensures the reader learns the language before being asked to interpret endpoints or flows.

---

## 3) Heading hierarchy and numbering

### 3.1 Heading depth

- Allowed heading levels: **H1 → H2 → H3**
- Avoid deeper nesting (`####` and below) except for rare cases (e.g., very large specs).

### 3.2 Numbered H2 chapters

- H2 headings MUST be numbered with an integer prefix:
  - `## 1) ...`
  - `## 2) ...`

Numbering provides a table-of-contents feel even without an explicit TOC and supports unambiguous reference.

### 3.3 Numbered H3 subchapters

- H3 headings MUST use a dotted prefix aligned to the parent chapter:
  - `### 2.1 ...`
  - `### 2.2 ...`

### 3.4 “Parenthetical summaries” for scan speed

H2 (and optionally H3) headings SHOULD include a brief parenthetical summary when helpful.

**Example**

```md
## 3) Valuesets (how values are grouped)
### 3.2 Lookup integration (where codes originate)
```

---

## 4) Paragraph rhythm and whitespace

### 4.1 Lead paragraph per section

Most sections SHOULD start with a short framing paragraph (1–3 lines) answering one of:

- What is this?
- Why does it matter?
- What constraint is important?

### 4.2 Whitespace as structure

- Always include a blank line between:
  - headings and body text
  - paragraphs and lists
  - list blocks and the next paragraph

This preserves readability in raw markdown and in rendered views.

### 4.3 Avoid dense prose blocks

Long, unbroken paragraphs SHOULD be converted into:

- short paragraphs + bullet lists
- H3 subsections
- repeated templates (see section 7)

---

## 5) List conventions (scannability standard)

### 5.1 When to use lists

Lists SHOULD be the default for:

- fields and properties
- constraints and rules
- capabilities and operations
- “what happens when…” explanations

### 5.2 Bold labels as “micro-headings”

Bullets SHOULD start with a bold label when they represent a named concept.

**Example**

```md
- **Identification**
  - `id`: Stable identifier for cross-references.
  - `canonical_refnumber`: Human-friendly reference.
```

### 5.3 Nested bullets for “category → details”

Use nested bullets to group details under a single label. This yields a “card-like” visual shape in most renderers.

### 5.4 Consistent token formatting

- Use backticks for exact identifiers:
  - file paths, module names
  - database fields / column names
  - API endpoints and route templates
  - constant values, enums, codes
- Use plain text for narrative descriptions.

---

## 6) Technical formatting requirements

### 6.1 Backticks for verbatim tokens

Backticks MUST be used for:

- file paths (e.g., `app/api/concepts.py`)
- model/table/field names (e.g., `ValueSetValue`, `valuesets`, `canonical_refnumber`)
- endpoints (e.g., `/api/v1/concepts/<concept_id>/values`)

This reduces ambiguity and helps readers visually distinguish “exact strings” from narrative text.

### 6.2 Inline math (optional)

Inline math MAY be used for short constraints when supported:

- \(low \le high\)

When math rendering is not supported, the plain text remains readable.

---

## 7) Standard section templates (recommended)

To make documents predictable, reuse these templates across repos.

### 7.1 Definition block template

- **What it is**: short description
- **Why it matters**: operational or user impact
- **Key fields**: bullet list grouped by categories

### 7.2 Capability block template

- “Capabilities implemented:” followed by bullet operations
- Follow with constraints/notes

### 7.3 Pipeline / workflow block template

- Use lettered or numbered steps (A/B/C… or 1/2/3…)
- Each step is a short statement plus optional nested bullets for details

### 7.4 Endpoint wrap-up template

Group endpoints by domain area, and for each group:

- list minimal endpoints required
- explicitly call out gaps, limitations, or TODOs

---

## 8) “Visual affordances” in plain markdown

This standard uses phrasing (not special callout syntax) to create emphasis consistently.

### 8.1 Callout phrases

Use phrases like these as the first words in a paragraph or bullet:

- **Why it matters**
- **Important**
- **Practical implication**
- **Constraint**

### 8.2 Explicit constraint lines

Constraints SHOULD be stated plainly and separated from narrative, so they are not lost in details.

---

## 9) Adoption checklist (for other repos)

To mimic this layout style in another repository:

- Use exactly one `#` title, then only `##` and `###`.
- Number all `##` chapters as `## 1) ...`, `## 2) ...`, etc.
- Number all `###` subchapters as `### 2.1 ...`, `### 2.2 ...`, etc.
- Insert `---` between major chapters.
- Start most sections with a short lead paragraph.
- Prefer short paragraphs + bullet lists over long prose.
- Use bold labels in bullets for “micro-headings”.
- Put exact technical tokens (fields, endpoints, files) in backticks.
- Keep heading depth controlled to preserve outline readability.

---

## 10) Suggested file naming and placement

Repositories adopting this standard SHOULD include one of:

- `docs/STYLE_GUIDE.md`
- `docs/markdown-layout-standard.md`
- `CONTRIBUTING.md` (as a “Documentation Style” section)

If multiple repos share the same standard, consider mirroring the file content verbatim to reduce drift.

