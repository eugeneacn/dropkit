# Do's and Don'ts Linter

Shared rubric used by A1, A2, and A4. Defines the 10 violation tags from the RKT Writing Guide Do's and Don'ts. Apply every check to each requirement being evaluated.

---

## How to apply this rubric

For every requirement, evaluate it against all 10 tags in order. For each violation found:

1. Record the **tag name** exactly as written below
2. Write a **one-sentence diagnosis** naming the specific triggering phrase in the original text
3. Use the **diagnostic template** provided for each tag as a starting point

A requirement may have zero, one, or multiple violations. List each separately. Do not group them.

**Asymmetric posture:** When a requirement is borderline on a tag, flag it and note it is borderline. Do not silently pass it. A missed violation ships; a false positive costs the author ten seconds to override.

---

## The 10 Violation Tags

---

### Tag 1 — Describes HOW not WHAT

**Definition:** The requirement describes the implementation mechanism (how the system does something) rather than the business need (what must happen). Business requirements describe WHAT is needed; HOW is for Capabilities and Features.

**Triggering patterns:**
- Verbs that imply system internals: "stores," "processes via," "calls," "sends to the API," "queries the database," "triggers the service"
- Phrases like: "the system will," "by using [technology]," "through the [interface name]," "via [specific mechanism]"
- Named technology components: specific software systems, APIs, database tables, microservices

**Diagnostic template:**
> "The phrase '[triggering phrase]' describes [implementation mechanism / system behaviour], not a business need."

**Remediation:** Remove the mechanism. Express what outcome is required in business language. Example: "the system sends an email via the notification service" → "participant must receive an educational notification."

---

### Tag 2 — Missing standard word

**Definition:** Business requirements must use one of the five standard modal verbs: **must**, **shall**, **should**, **may**, **will**. Requirements without a modal verb are ambiguous about obligation level.

**Triggering patterns:**
- Absence of must/shall/should/may/will in the main clause
- Informal substitutes: "needs to," "has to," "is required to," "will be able to," "can," "should be able to," "is expected to"

**Diagnostic template:**
> "The requirement uses '[informal phrase]' rather than a standard modal verb (must / shall / should / may / will), making the obligation level ambiguous."

**Remediation:** Replace the informal phrase with the appropriate modal verb. Use *must* for mandatory requirements, *should* for strong recommendations, *may* for optional behaviour.

---

### Tag 3 — Uses Agile user-story format

**Definition:** "As a [user], I want [capability] so that [benefit]" is the format for technical requirements — Capabilities and Features. It is explicitly reserved for those levels and must not be used for Business Process Requirements.

**Triggering patterns:**
- Starts with "As a"
- Contains "I want" or "so that [benefit]"
- Three-clause structure: role / capability / benefit

**Diagnostic template:**
> "The requirement is written in Agile user-story format ('As a [role], I want...'), which is reserved for Capabilities and Features. BPRs must not use this format."

**Remediation:** Rewrite as a business requirement. Identify the business object and the obligated action. Do not proceed with a rewrite without explicitly flagging this format violation first.

---

### Tag 4 — Contains design details

**Definition:** Technology choices, system names, field names, table names, API names, and UI component names belong in Capabilities or Features — not in Business Process Requirements.

**Triggering patterns:**
- Named software systems or products: "Salesforce," "ServiceNow," "Oracle," specific internal system names
- Data structure references: "field," "record," "table," "schema," "payload," "JSON," "XML"
- API/integration references: "REST call," "API endpoint," "webhook," "message queue"
- UI component references: "button," "dropdown," "modal," "form field"

**Diagnostic template:**
> "The phrase '[design detail]' names a specific [technology / system / data structure / UI component], which is a design detail belonging at the Capability or Feature level, not in a Business Process Requirement."

**Remediation:** Replace the design detail with the business capability it provides. Example: "updates the participant record in Salesforce" → "participant record must be updated."

---

### Tag 5 — Vague or general language

**Definition:** The requirement uses terms that are unmeasurable or subjective, making it impossible to test or validate.

**Triggering patterns:**
- Time words: "timely," "quickly," "promptly," "soon," "within a reasonable time"
- Quality adjectives: "appropriate," "adequate," "sufficient," "acceptable," "good," "user-friendly," "easy," "simple"
- Quantity hedges: "some," "many," "few," "several," "as needed," "as appropriate"

**Diagnostic template:**
> "The term '[vague term]' is unmeasurable; the requirement cannot be validated or tested without a specific, agreed criterion."

**Remediation:** Replace with a specific, testable criterion. If the specific value is not yet known, use a placeholder: `[time period — to be confirmed with stakeholders]`. Do not invent a number.

---

### Tag 6 — Doesn't know the user

**Definition:** The requirement does not identify which user, role, or actor is responsible for or affected by the action. Requirements without a named actor are untraceable to a value stream and cannot be allocated to a team.

**Triggering patterns:**
- No named actor in the requirement
- Generic references: "users," "customers," "people," "they"
- Passive voice constructions that omit the actor: "the form must be submitted," "notification must be sent" (without specifying to whom or by whom)

**Diagnostic template:**
> "The requirement does not identify which [user / role / actor] is responsible for or affected by '[action]'. Without a named actor, the requirement cannot be allocated to a value stream."

**Remediation:** Name the actor explicitly using the UL doc's canonical role names (e.g., "participant," "plan sponsor," "VS Business Lead," "Product Engineer").

---

### Tag 7 — Uses negative phrasing

**Definition:** Requirements should state what must happen (positive obligation), not what must not happen — except in the context of a genuine EARS Unwanted-behavior pattern where an explicit exception condition is given.

**Triggering patterns:**
- "must not," "shall not," "cannot," "is not allowed to," "may not" — without an accompanying exception condition
- Prohibition statements without a trigger: "The system must not display participant PII" (no condition given)

**Note:** The EARS Unwanted-behavior pattern (`If <exception condition>, <business object> must not <action>`) is acceptable and is not a violation. The violation is a bare prohibition with no exception condition.

**Diagnostic template:**
> "The requirement uses negative phrasing ('must not [action]') without pairing it with a positive requirement or an explicit exception condition, making the business intent unclear."

**Remediation:** Either rewrite as a positive statement of what must happen, or apply the EARS Unwanted-behavior pattern: `If <exception condition>, <business object> must <handling>`.

---

### Tag 8 — Wrong level

**Definition:** The RKT Writing Guide is explicit about where different requirement types live. Functional requirements belong at the Sub-Process level. Non-functional requirements (Security, Performance, Usability, Availability, DR) belong at the Business Process level.

**Triggering patterns:**
- NFR language (SLA targets, performance numbers, security classifications, availability percentages) on a Sub-Process page
- Functional process steps ("participant must submit the form," "plan sponsor must approve the request") on a Business Process page

**Diagnostic template:**
> "This appears to be a [functional / non-functional] requirement placed at the [sub-process / process] level. Per the RKT Writing Guide, it belongs at the [correct level]."

**Remediation:** Move the requirement to the correct level. For NFRs on sub-process pages, escalate to the Business Process page. For functional steps on a Business Process page, allocate to the appropriate sub-process.

---

### Tag 9 — Wrong parent

**Definition:** The requirement describes an activity that is out of scope for the sub-process it is currently assigned to. It belongs under a different sub-process, or under a sub-process that does not yet exist.

**Triggering patterns:**
- The subject, actor, trigger event, or outcome of the requirement doesn't match the sub-process's stated scope
- The requirement implies a lifecycle stage (e.g., cancellation, archival, notification) that the current sub-process doesn't handle

**Diagnostic template:**
> "The activity described ('[activity]') appears to be out of scope for '[current sub-process]' because [reason]. It may belong under '[likely correct sub-process]' — or no existing sub-process covers this scenario (consider running A4-Job2 to check process cohesion)."

**Remediation:** Move to the correct sub-process if one exists. If no sub-process covers this activity, raise a process cohesion concern — this is a candidate for A4-Job2 (cohesion re-check).

---

### Tag 10 — Term inconsistent with Ubiquitous Language

**Definition:** The requirement uses a term that differs from or conflicts with the UL doc's canonical terminology for the same concept. (See `ubiquitous-language-resolver.md` for the full resolution procedure.)

**Triggering patterns:**
- Synonyms for UL doc terms: e.g., "customer" vs. "participant," "account" vs. "plan," "advisor" vs. "financial professional"
- Informal abbreviations not in the UL doc
- Capitalisation or spelling that differs from the UL doc entry

**Diagnostic template:**
> "The term '[input term]' appears to be a synonym for '[UL doc term]' per the Ubiquitous Language document. Using both terms across requirements risks traceability inconsistency."

**Remediation:** Do not auto-correct. Surface the inconsistency and ask the author to confirm which term to use. The author decides; the UL doc is authoritative once the author commits.
