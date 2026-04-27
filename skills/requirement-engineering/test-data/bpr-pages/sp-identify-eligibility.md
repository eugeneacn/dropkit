# Sub-Process: Identify Eligibility

**Parent Business Process:** Required Minimum Distribution Processing
**Sub-process description:** Identifies participants at or approaching RMD eligibility age each year, applies account-type exclusions, resolves manual exceptions, and produces a confirmed eligibility list for the current RMD cycle.
**Start trigger:** Annual cycle initiation on October 1
**End state:** Confirmed eligibility list locked and passed to Calculate RMD Amount sub-process
**Value Stream Owner:** Distributions Value Stream

---

## Functional Requirements

| # | Requirement | Traceability | Notes |
|---|-------------|--------------|-------|
| IE-01 | When the annual RMD cycle initiates, participants who will reach RMD eligibility age by December 31 of the following year must be identified and added to the upcoming eligibility population. | Distributions > Calculation > Eligibility Evaluator | |
| IE-02 | The system will run a nightly batch job to check all participant birth dates against the RMD eligibility threshold and flag matching accounts in the eligibility_flags table. | *(missing)* | **⚠ PLANTED VIOLATION: Tag 1 (HOW not WHAT) + Tag 4 (design details)** |
| IE-03 | Where a participant account is classified as a Roth IRA, that account must be excluded from RMD eligibility determination. | Distributions > Calculation > Eligibility Evaluator | |
| IE-04 | Where a participant account is subject to a QDRO hold, the account must be flagged for manual review and excluded from automated eligibility processing. | SOP-RMD-001A | |
| IE-05 | Once the VS Business Lead confirms the eligibility population, the eligibility list must be locked and no further changes permitted until the following annual cycle. | Distributions > Calculation > Eligibility Evaluator | |
| IE-06 | The plan sponsor confirms receipt of the eligibility summary report before the eligibility list is locked. | *(missing)* | **⚠ PLANTED VIOLATION: Tag 2 (Missing standard word — "confirms" has no modal verb)** |

---

## Notes

- IE-02 and IE-06 contain deliberate violations for A2 testing.
- IE-03, IE-04, and IE-05 are compliant and should receive no A2 flags.
- IE-02 traceability link is missing — A5 should propose a match (Eligibility Evaluator, High confidence).
- IE-06 traceability link is missing — A5 should propose a match (Eligibility Evaluator or Account Record, Medium confidence given the actor ambiguity).
