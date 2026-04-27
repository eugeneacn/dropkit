# Stakeholder Intent Memo — RMD Processing Epic

**To:** VS Business Lead, Distributions Value Stream
**From:** Product Owner, Retirement Services Platform
**Date:** 2025-09-15
**Re:** Required Minimum Distribution Processing — Epic Intent

---

## Why we're doing this epic

The current RMD process runs across three disconnected systems with no single source of truth for participant eligibility or disbursement status. The SECURE 2.0 Act raised the RMD eligibility age from 72 to 73, and our current system still hard-codes the old age threshold — we had three compliance escapes in Q3 2025 where participants were incorrectly flagged or missed entirely.

Additionally, the spousal waiver collection process is entirely manual and paper-based, creating a 3–5 week bottleneck in the Validate Elections phase. Participants are calling the call center repeatedly to ask where their disbursement is, and the answer is almost always "waiting for the spousal waiver."

The intent of this epic is to modernise the RMD process end-to-end: from eligibility identification through disbursement confirmation, running on the new platform infrastructure.

---

## What success looks like

By the end of this epic, a participant approaching or at RMD eligibility age should be able to:
1. Receive a clear, timely educational notification
2. Make their election online (or by phone, as today)
3. Complete the spousal waiver electronically (no paper)
4. Receive disbursement confirmation

The VS Business Lead should be able to:
1. Monitor the RMD population and intervene on exceptions without a manual spreadsheet
2. See disbursement status in real time

The plan sponsor should receive consolidated reporting without a manual extract.

---

## Scope boundaries

**In scope:**
- Eligibility identification (participants approaching or at RMD age)
- RMD amount calculation
- Participant notification and engagement
- Election collection (portal + call center)
- Spousal waiver collection (new: move to electronic)
- Election validation
- Disbursement initiation and tracking
- Post-disbursement confirmation and archival

**Out of scope for this epic:**
- Inherited RMD rules (separate epic, different calculation method)
- Beneficiary processing after participant death
- Tax reporting (1099-R generation) — already handled by the Tax Operations team
- Roth IRA RMD exemption logic (Roth accounts are excluded from this process)

---

## Known risks and open questions

1. **Cancellation of in-flight RMDs:** The SOP notes this is handled ad hoc today. The business has not defined a formal sub-process for this. We need to decide before this epic closes whether to build a cancel flow or explicitly document the limitation. This is currently a gap.

2. **Electronic spousal waiver legality:** Legal is reviewing whether electronic spousal waivers are compliant with ERISA Section 205. Pending their ruling — if not approved, the paper SOP stays in place and this epic excludes waiver collection from the digital flow.

3. **RMD eligibility age:** Requirements must not hard-code age 73. Reference "RMD eligibility age" throughout — the platform must be configurable if the age changes again.

4. **Call center handoff:** The call center makes elections on behalf of participants. We need to confirm whether the call center agent appears as the election submitter or the participant does. The current SOP is ambiguous on this.

---

## Stakeholders

| Name | Role | Involvement |
|------|------|-------------|
| [VS Business Lead] | Process owner | Approves all requirements |
| [Product Engineer] | Technical lead | Traceability and domain component mapping |
| [SRE Lead] | Availability/DR | NFR targets for disbursement availability |
| [Security Architect] | Security | PII and access control requirements |
| [Legal Counsel] | Compliance | Electronic waiver approval |
| [Call Center Manager] | Operations | Call center election flow sign-off |
