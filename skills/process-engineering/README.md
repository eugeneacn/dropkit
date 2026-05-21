# Process Engineering Skills

Five BPR agents that support the business process requirements authoring lifecycle. Use them in sequence across an epic — from kickoff shaping through Tollgate handoff.

## Agent Index

| ID | Skill directory | When to run | Input | Output |
|----|----------------|-------------|-------|--------|
| A1 | [bpr-intake-shaper/](bpr-intake-shaper/) | Epic kickoff — once | Raw source docs + UL doc | Draft BP page + candidate SP list |
| A2 | [requirement-rewriter/](requirement-rewriter/) | Throughout drafting — many times | Requirement statements + hierarchy context + UL doc | Violation report + rewrites |
| A3 | [nfr-coverage-agent/](nfr-coverage-agent/) | Pre-NFR workshop or Tollgate | BP page + SP pages | NFR coverage matrix + workshop questions |
| A4 | [process-cohesion-decomposition/](process-cohesion-decomposition/) | Kickoff (Job 1) or mid-epic opt-in (Job 2) | Street-view map or BP+SP pages + UL doc | Decomposition report or cohesion findings |
| A5 | [traceability-linker/](traceability-linker/) | Pre-Tollgate handoff | SP page + domain corpus + UL doc | Traceability proposals (High / Medium / Low) |

## Shared Procedures

All five agents load from [`shared/`](shared/):

- [`ubiquitous-language-resolver.md`](shared/ubiquitous-language-resolver.md) — resolves domain terms against the project's Ubiquitous Language document (required by all agents)
- [`hierarchy-context-resolver.md`](shared/hierarchy-context-resolver.md) — confirms L1 Business Process / L2 Sub-Process context before acting on requirements (used by A2, A4, A5)
- [`dos-and-donts-linter.md`](shared/dos-and-donts-linter.md) — 10 violation tags from the requirements writing guide Do's and Don'ts (used by A1, A2, A4)

## Structure Note

These are **pure-prompt skills**: all logic lives in `SKILL.md` procedure documents with no runtime scripts, dependencies, or executables. This differs from other dropkit skills that include `scripts/`, `requirements.txt`, or `package.json`. The difference is intentional — BPR authoring is a human-in-the-loop workflow; the agents advise and draft, and humans commit every decision.

## Source References

These agents reference two internal standards that are not publicly available:

- **requirements writing guide** — the internal requirements authoring standard that defines the Do's and Don'ts rubric, EARS pattern guidance, and the L1/L2/L3 hierarchy. If adapting for a different organisation, substitute your own requirements authoring standard.
- **DR tier classification** — the NFR Coverage Agent asks which DR tier applies. The tier labels are organisation-specific; substitute your own classification scheme's labels.
