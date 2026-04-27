# BPR Skills — End-to-End Test Data

Scenario: **Required Minimum Distribution (RMD) Processing** epic for a retirement plan recordkeeping platform. This is a mid-sized epic covering eligibility identification through disbursement, which exercises all five BPR skills in sequence.

---

## Test data map

```
sources/sop-rmd-processing.md  ─┐
sources/stakeholder-intent-memo.md ─┤──► A1 (bpr-intake-shaper)
ubiquitous-language.md ─────────┘
                                         ▼ produces draft BP + sub-process pages
street-view-map.md ─────────────────► A4 decomposition mode
                                         ▼ confirms sub-process list
bpr-pages/bp-rmd-processing.md  ─┐
bpr-pages/sp-*.md ───────────────┤──► A2 (requirement-rewriter)  [per sub-process]
ubiquitous-language.md ──────────┘
                                         ▼ cleaned requirements
bpr-pages/bp-rmd-processing.md  ─┐
bpr-pages/sp-*.md ───────────────┤──► A3 (nfr-coverage-agent)
                                  │──► A4 cohesion re-check mode (confirms before running)
ubiquitous-language.md ──────────┘
                                         ▼
bpr-pages/sp-*.md ───────────────┐
domain-components.md ────────────┤──► A5 (traceability-linker)  [per sub-process]
ubiquitous-language.md ──────────┘
```

---

## How to run each skill

### A1 — BPR Intake & Shaper
**Goal:** Generate the BP page and sub-process list from raw sources.

Inputs:
- `sources/sop-rmd-processing.md`
- `sources/stakeholder-intent-memo.md`
- `ubiquitous-language.md`

Invoke: Load the `bpr-intake-shaper` skill with the three files attached and ask it to produce a draft.

**Expected output:** A markdown file matching (or close to) `bpr-pages/bp-rmd-processing.md` + `bpr-pages/sp-*.md` structure.

---

### A4 — Process Decomposition
**Goal:** Confirm sub-process segmentation from the street-view map.

Inputs:
- `street-view-map.md`
- `ubiquitous-language.md`
- Business Process context: "Required Minimum Distribution Processing — end-to-end process for identifying RMD-eligible participants, calculating required amounts, collecting elections, and disbursing funds"

Invoke: Load the `process-cohesion-decomposition` skill with the files attached and ask it to run the decomposition.

**Expected output:** Sub-process list with 6–8 entries, a value-stream ownership grid, and any boundary seams identified.

---

### A2 — Requirement Rewriter
**Goal:** Lint and rewrite the deliberately flawed requirements across the sub-process pages.

Inputs (run per sub-process):
- One `bpr-pages/sp-*.md` file
- `ubiquitous-language.md`
- Parent hierarchy stated in the prompt

Known violations planted in the test data (see below for details):
- `sp-identify-eligibility.md` — 1 HOW-not-WHAT + design detail, 1 missing standard word
- `sp-calculate-rmd.md` — 1 Agile user-story format, 1 vague language, 1 wrong level (NFR)
- `sp-engage-participant.md` — 1 HOW-not-WHAT + design detail
- `sp-validate-elections.md` — 1 negative phrasing (no condition), 1 wrong parent
- `sp-submit-disbursement.md` — 1 missing standard word

Compliant requirements are also present — A2 should not touch them.

Invoke: Load the `requirement-rewriter` skill with parent context and UL doc.

---

### A3 — NFR Coverage Agent
**Goal:** Surface NFR gaps in the Business Process page.

Inputs:
- `bpr-pages/bp-rmd-processing.md`
- All `bpr-pages/sp-*.md` files (for process context)
- Usability is pre-marked as accepted N/A in the BP page

NFR state in test data:
- Security: partial (PII masking present; auth/access control gaps)
- Performance: none
- Usability: N/A accepted
- Availability: none
- Disaster Recovery: none

**Expected output:** 4 categories with gaps + questions, 1 N/A (Usability) not re-flagged.

Invoke: Load the `nfr-coverage-agent` skill with the BP page and sub-process pages.

---

### A4 — Cohesion Re-check
**Goal:** Confirm the cohesion gap introduced by the wrong-parent requirement in `sp-validate-elections.md`.

Inputs:
- All `bpr-pages/sp-*.md` files
- `bpr-pages/bp-rmd-processing.md`
- `ubiquitous-language.md`

The wrong-parent requirement in Validate Elections ("cancel an in-flight RMD") has no sub-process to live in — this should surface as a Blocking finding.

Invoke: Load the `process-cohesion-decomposition` skill with all files attached and ask it to run a cohesion check. The skill will describe what it will do and ask you to confirm before running.

---

### A5 — Traceability Linker
**Goal:** Propose links for requirements that are missing them.

Inputs (run per sub-process):
- One `bpr-pages/sp-*.md` file
- `domain-components.md`
- `ubiquitous-language.md`

Not all requirements have traceability links — the unlinking is deliberate. Expected outcomes:
- Several High-confidence proposals (clear UL vocabulary + component scope match)
- Some Medium-confidence (multi-domain or partial overlap)
- At least one manual-mapping-required (the spousal waiver requirement — no matching component in corpus)

Invoke: Load the `traceability-linker` skill with the sub-process page, domain components, and UL doc.

---

## Planted violations summary

| Sub-process page | Requirement | Violation tag(s) |
|---|---|---|
| sp-identify-eligibility | "The system will run a nightly batch..." | HOW not WHAT, Contains design details |
| sp-identify-eligibility | "The plan sponsor confirms receipt..." | Missing standard word |
| sp-calculate-rmd | "As a VS Business Lead, I want..." | Uses Agile user-story format |
| sp-calculate-rmd | "The RMD calculation should be accurate and completed quickly" | Vague or general language |
| sp-calculate-rmd | "The RMD calculation batch must complete within a 4-hour window" | Wrong level (NFR at sub-process) |
| sp-engage-participant | "The engagement notification must be generated using NotificationService..." | HOW not WHAT, Contains design details |
| sp-validate-elections | "Participants must not be required to call the call center..." | Negative phrasing (no exception condition) |
| sp-validate-elections | "When a participant requests to cancel an in-flight RMD..." | Wrong parent |
| sp-submit-disbursement | "The plan sponsor confirms receipt of the disbursement notification..." | Missing standard word |
