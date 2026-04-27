# Sub-Process: Validate Elections

**Parent Business Process:** Required Minimum Distribution Processing
**Sub-process description:** Validates each submitted election against the calculated RMD amount, payment method, withholding election presence, and spousal waiver requirements. Routes non-auto-validatable elections to the VS Business Lead for manual review.
**Start trigger:** Election record received with status "Pending Validation"
**End state:** Election record updated to "Validated" (proceeds to Submit Disbursement) or "Held" (pending waiver or manual review) with documented hold reason
**Value Stream Owner:** Distributions Value Stream

---

## Functional Requirements

| # | Requirement | Traceability | Notes |
|---|-------------|--------------|-------|
| VE-01 | While a spousal waiver is pending, the RMD disbursement must not proceed to the Submit Disbursement sub-process. | Distributions > Disbursement > Election Processing | |
| VE-02 | When a spousal waiver is required but not on file, the participant and spouse must be notified that the election is on hold pending receipt of the spousal waiver. | Communications > Notifications > RMD Notifications | |
| VE-03 | Participants must not be required to call the call center in order to make their RMD election. | *(missing)* | **⚠ PLANTED VIOLATION: Tag 7 (Negative phrasing without exception condition)** |
| VE-04 | Where a participant does not provide a withholding election, the default federal withholding rate must be applied and the participant must be notified of the default applied. | Distributions > Disbursement > Withholding Calculator | |
| VE-05 | When an election cannot be automatically validated, the VS Business Lead must review and approve or reject the election within 2 business days. | SOP-RMD-001A | |
| VE-06 | When a participant requests to cancel an in-flight RMD, the disbursement must be halted and funds must be returned to the participant account. | *(missing)* | **⚠ PLANTED VIOLATION: Tag 9 (Wrong parent — no sub-process covers cancellation)** |

---

## Notes

- VE-01, VE-02, VE-04, VE-05 are compliant — A2 should not flag them.
- VE-03: Negative phrasing violation. The requirement states what must NOT happen without an exception condition or positive pairing. A2 should flag Tag 7. Proposed rewrite could be: "Participant must be able to make their RMD election via the participant portal without requiring a call center interaction." Or, using EARS Unwanted-behavior: "If a participant's RMD election requires call center intervention, the call center must follow SOP-RMD-003."
- VE-06: Wrong parent. This requirement describes a cancellation flow that has no home in the current sub-process list. VE-06 is not a validation activity — it describes cancellation of an in-progress transaction that spans from Submit Disbursement backward. A2 should flag Tag 9 and suggest the BA run A4-Job2 (cohesion re-check) because no suitable parent sub-process currently exists.
- VE-03 traceability missing — A5 should propose Communications > Notifications + Election Processing (Medium, multi-domain).
- VE-06 traceability missing — A5 should flag "manual mapping required" because no domain component or SOP exists for in-flight RMD cancellation (per domain-components.md coverage gaps).
