# Ubiquitous Language Resolver

Shared procedure used by all BPR agents (A1–A5). Load this reference before acting on any input that contains domain terms, process names, or role names.

---

## Purpose

The project's Ubiquitous Language (UL) document is the single source of truth for terminology in a given epic or value stream. Agents must resolve all domain vocabulary against it — never invent or override definitions. Inconsistent terminology across requirements is one of the most common traceability and review failures the RKT Writing Guide is designed to prevent.

---

## Procedure

### 1. Load the UL document

The user must supply the UL document as an input. If it is absent, stop and ask for it:

> "I need the project's Ubiquitous Language document before I can proceed. It is a required input — without it I cannot resolve domain terms consistently or flag inconsistencies across requirements."

### 2. Scan input for domain terms

For every input artifact (requirements, meeting notes, process descriptions, etc.), identify:
- Proper nouns (process names, system names, role names, product names)
- Acronyms and abbreviations
- Domain-specific noun phrases (e.g., "spousal waiver," "RMD calculation," "e-delivery preference")

### 3. Resolve each term

For each identified term:

| Situation | Action |
|-----------|--------|
| Term is in the UL doc | Use the UL doc's canonical spelling and definition. If the input uses a different spelling or capitalisation, note the inconsistency (do not silently correct — the author decides). |
| Term is a synonym for a UL doc entry (e.g., input says "customer," UL doc says "participant") | Flag as: **Term inconsistency** — `"[input term]" appears to be a synonym for "[UL doc term]" per the Ubiquitous Language document. Author to confirm.` Do not auto-correct. |
| Term appears 2+ times in the input and is NOT in the UL doc | Flag as a **candidate glossary stub**: `"[term]" — appears [n] times across input; not found in Ubiquitous Language document. Candidate for UL doc addition.` Do not invent a definition. |
| Term appears once and is not in the UL doc | No action needed unless it is clearly domain-specific and likely to recur. |

### 4. Surface all findings

Do not silently apply resolutions. Report:
- **Term inconsistencies** — places where the input uses a different word than the UL doc for the same concept
- **Undefined candidates** — terms used 2+ times with no UL doc entry
- Let the human decide in every case. Never override the UL doc and never invent a definition.

---

## Key rule

> Agents treat the Ubiquitous Language document as authoritative. They do not invent or override definitions. Inconsistency is surfaced; resolution is left to the human.
