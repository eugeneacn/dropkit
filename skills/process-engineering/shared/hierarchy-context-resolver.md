# Hierarchy Context Resolver

Shared procedure used by A2, A4, and A5. The RKT Writing Guide structures business requirements at three levels: Business Process (L1) → Sub-Process (L2) → Business Requirement (L3). Any agent that acts on a requirement or sub-process must know its position in this hierarchy before proceeding.

---

## Why this matters

A requirement evaluated or rewritten without knowing its parent sub-process and parent business process cannot be correctly assessed for:
- **Wrong parent** — is this requirement scoped correctly for this sub-process?
- **Wrong level** — is this a functional requirement (belongs at sub-process) or NFR (belongs at process)?
- **Coherence** — does the requirement fit the sub-process's declared start/end boundary?

Agents that skip hierarchy confirmation produce outputs that look correct in isolation and fail in review.

---

## Procedure

### Step 1 — Check what has been provided

Before acting on any requirement or sub-process, confirm the following are present in the user's input:

| Required context | What it is |
|---|---|
| **Parent L2 Sub-Process name** | The name of the sub-process this requirement belongs to |
| **Parent L2 Sub-Process description** | 1–3 sentence description of what the sub-process does (its scope boundary) |
| **Parent L1 Business Process name** | The name of the overall business process |
| **Parent L1 Business Process description** | 1–3 sentence description of the end-to-end process |

### Step 2 — Ask if missing

If either the L2 or L1 context is missing, stop and ask before proceeding:

> "Before I can evaluate [this requirement / these requirements / this sub-process], I need the parent context:
> - What is the name and description of the **Sub-Process** this sits under?
> - What is the name and description of the **Business Process** above that?
>
> These are required — the RKT Writing Guide writes requirements at the sub-process level, and I cannot assess scope, level, or parent fit without knowing the hierarchy."

### Step 3 — Never infer hierarchy from content

Do not guess the parent sub-process or business process from the text of the requirement. A requirement about "RMD notification" could belong to the Engage sub-process, the Notify sub-process, or the Archive sub-process depending on the process design. Only the user knows the intended assignment.

### Step 4 — Record confirmed hierarchy at the top of output

Once confirmed, include the hierarchy context at the top of any output report:

```
## Hierarchy Context (confirmed)
- **Business Process (L1):** [name] — [description]
- **Sub-Process (L2):** [name] — [description]
```

This makes it visible to any reviewer and prevents hierarchy drift across a long requirements list.
