# Cohesion Report — Required Minimum Distribution Processing

**Approval received:** Yes — "I approve Job 2 — please run the cohesion re-check"
**Date:** 2026-04-23
**Agent:** process-cohesion-decomposition (A4), Job 2

## Hierarchy Context (confirmed)

- **Business Process (L1):** Required Minimum Distribution Processing — end-to-end process for RMD eligibility identification, calculation, participant engagement, election validation, disbursement, and post-disbursement archival.
- **Sub-Processes (L2) reviewed:** Identify Eligibility, Calculate RMD Amount, Engage Participant, Validate Elections, Submit Disbursement.
- **Sub-Processes declared on BP page but not reviewed (no page exists):** Notify and Confirm (#6), Archive (#7).

---

## Summary

**5 findings: 2 Blocking, 3 Advisory.**

| # | Check | Severity | One-line summary |
|---|-------|----------|-----------------|
| 1 | Check 1 — Journey coverage | **BLOCKING** | Two sub-processes declared on the BP page have no sub-process pages |
| 2 | Check 3 — Defined handoffs | **BLOCKING** | Submit Disbursement and Archive both claim ownership of the "RMD satisfied" status update |
| 3 | Check 2 — Start trigger and end state | Advisory | Engage Participant start trigger conflates upstream handoff event with notification timing rule |
| 4 | Check 3 — Defined handoffs | Advisory | Calculate RMD Amount → Engage Participant handoff mechanism implied but not defined |
| 5 | Check 6 — Unhappy path | Advisory | No sub-process covers process-level exception routing |

---

## Findings

### Finding 1 — Check 1: Journey Coverage — BLOCKING

**Observation:** The Business Process page declares 7 sub-processes. Sub-process pages exist for 5 of them (Identify Eligibility, Calculate RMD Amount, Engage Participant, Validate Elections, Submit Disbursement). No sub-process pages exist for:
- **#6 — Notify and Confirm:** "Sends disbursement completion confirmation to the participant"
- **#7 — Archive:** "Marks the participant's RMD as satisfied for the current tax year and archives all cycle records per retention policy"

Both activities are described in SOP-RMD-001 Phase 6 and in the intent memo's success criteria ("Receive disbursement confirmation").

**Gap:** The post-transaction phases of the business journey have no sub-process scope boundaries, start triggers, end states, or requirements. A requirements workshop cannot write requirements for these phases, and any requirements that are written will have no parent to live in. The journey is structurally incomplete.

**Reference:** Check 1 rule — "A complete process must account for both pre-transaction (setup, eligibility) and post-transaction (archival, notification) phases."

**Proposed remediation:** Create sub-process pages for Notify and Confirm and Archive before the requirements workshop. At minimum, define:
- Start trigger and end state for each
- Value Stream owner (likely Distributions VS, but must be confirmed)
- Whether Notify and Confirm and Archive remain as two separate sub-processes or should be merged into a single Post-Disbursement sub-process (the A1 intake draft proposed a single "Complete Post-Disbursement" — confirm the preferred decomposition with the VS Business Lead)

---

### Finding 2 — Check 3: Defined Handoffs — BLOCKING

**Observation:** Two artifacts claim ownership of the same state change — "participant RMD record updated to satisfied for the current tax year":

- **Submit Disbursement end state:** "Disbursement confirmed complete and participant record updated to reflect RMD satisfied for the current tax year"
- **BP page Archive description:** "Marks the participant's RMD as satisfied for the current tax year and archives all cycle records per retention policy"

**Gap:** One sub-process will execute this update; the other will either repeat it or depend on it having happened — but the handoff boundary is not defined. This is a state-ownership conflict at a process boundary. When requirements are written for both sub-processes, this will produce contradictory or duplicate requirements. At Tollgate, traceability to the same domain component from two sub-processes claiming the same outcome will fail review.

**Reference:** Check 3 rule — "Wherever one sub-process hands work to another sub-process, is the handoff defined? Who sends what to whom?"

**Proposed remediation:** Decide which sub-process owns the "RMD satisfied" status update before pages are created for Notify and Confirm and Archive:
- **Option A:** Submit Disbursement owns the status update. Archive owns only records archival. The Archive sub-process description on the BP page should be corrected to remove "marks the participant's RMD as satisfied."
- **Option B:** Submit Disbursement ends at "disbursement transfer confirmed." A post-disbursement sub-process owns the status update, confirmation notification, and archival in sequence. Submit Disbursement's end state must be rewritten to remove the status update claim.

VS Business Lead to decide.

---

### Finding 3 — Check 2: Start Trigger and End State — Advisory

**Observation:** Engage Participant declares a compound start trigger: *"RMD calculation run locked; 90 days before IRS deadline for first-year participants, 60 days for returning participants."*

**Gap:** This conflates two different things: the upstream handoff event that enables the sub-process (calculation run locked) and the business timing rule that governs when notifications fire (90/60 days before the IRS deadline). It is unclear whether:
- The sub-process begins when calculation locks and then waits internally for the timing window to open, or
- The sub-process begins when the timing window opens (calculation lock is a prerequisite, not a trigger)

If requirements are written against this sub-process, the trigger ambiguity will produce conflicting requirements about when the sub-process "starts" vs. when notifications are sent.

**Reference:** Check 2 rule — "Does every sub-process have a clearly defined start trigger — what causes it to begin?"

**Proposed remediation:** Separate the start trigger from the internal timing rule. Suggested revision:
- **Start trigger:** "RMD calculation run locked and notification queue populated"
- Add a separate internal timing note: "First-year participant notifications must be sent no later than 90 days before the IRS deadline; returning participant notifications must be sent no later than 60 days before the IRS deadline."

---

### Finding 4 — Check 3: Defined Handoffs — Advisory

**Observation:** Calculate RMD Amount's end state is: *"RMD amounts calculated, outliers reviewed and approved, calculation run locked; notification queue ready."* Engage Participant's start trigger references the calculation run being locked.

**Gap:** The handoff mechanism between these two sub-processes is implied — "notification queue ready" suggests Engage Participant picks up a queue — but the mechanism is not defined. Who or what signals the handoff? What does Engage Participant receive? Is the queue populated by the Calculate RMD Amount sub-process, or does Engage Participant pull from the calculation output? A requirements workshop will need this to write testable requirements for the transition.

**Reference:** Check 3 rule — "Who sends what to whom? What signal indicates the handoff has occurred?"

**Proposed remediation:** Define the handoff mechanism in the end state of Calculate RMD Amount and the start trigger of Engage Participant. Options:
- System event (e.g., calculation lock triggers a status change that Engage Participant polls)
- VS Business Lead action (e.g., VS Business Lead releases the calculation run, which initiates notification generation)
- Confirm with Product Engineer which domain component mediates this handoff.

---

### Finding 5 — Check 6: Unhappy Path — Advisory

**Observation:** No sub-process covers process-level exception routing. The SOP's exception handling section lists four exception scenarios — participant deceased, account in QDRO, in-flight RMD cancellation, and plan sponsor override request — none of which are allocated to a sub-process page. Additionally, requirement VE-06 in Validate Elections describes an in-flight RMD cancellation flow; its own notes flag it as "wrong parent" because no sub-process exists to own it.

**Gap:** The business process has no defined failure mode at the process level. If a sub-process cannot complete (e.g., deceased participant discovered in Validate Elections, cancellation request received after disbursement is in-flight), there is no declared path for exception routing. Requirements written against the happy path will be untestable without a corresponding exception path.

**Reference:** Check 6 rule — "Is there a representation of what happens when a step fails — not just when a requirement fails, but when an entire sub-process cannot complete?"

**Proposed remediation:** At the requirements workshop, raise the following exception scenarios for explicit scoping decisions:
1. **In-flight RMD cancellation:** The SOP flags this as a process gap (ad hoc). The intent memo requires a go/no-go decision before the epic closes. If a cancel flow is in scope, it may warrant a dedicated sub-process or exception path within Submit Disbursement. If out of scope, this must be explicitly documented on the BP page.
2. **Deceased participant mid-cycle:** Currently described as "escalate to Beneficiary Processing team." The handoff mechanism to that team is not defined in any sub-process page.
3. **Plan sponsor override request:** SOP says "escalate to Compliance team." No sub-process owns this escalation.
4. **QDRO hold discovered post-eligibility-lock:** IE-04 covers QDRO at eligibility; there is no coverage for a QDRO hold discovered after the eligibility list is locked.

---

## Checks with No Findings

| Check | Status |
|-------|--------|
| Check 2 — Start trigger / end state (existing 5 SPs) | Start triggers and end states are defined and reasonably specific for Identify Eligibility, Calculate RMD Amount, Validate Elections, and Submit Disbursement. Engage Participant carries an Advisory (Finding 3). |
| Check 4 — Pre- and post-transaction steps | Pre-transaction coverage is complete (Identify Eligibility, Calculate RMD Amount). Post-transaction gap is addressed under Finding 1 (Blocking). |
| Check 5 — Single value-stream ownership | All five existing sub-process pages declare a single owner: Distributions Value Stream. No co-ownership ambiguity found. |
