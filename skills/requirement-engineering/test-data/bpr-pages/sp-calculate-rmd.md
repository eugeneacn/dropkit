# Sub-Process: Calculate RMD Amount

**Parent Business Process:** Required Minimum Distribution Processing
**Sub-process description:** Calculates the required minimum distribution amount for each participant on the confirmed eligibility list, using the prior year plan balance and the IRS applicable divisor. Flags outliers for VS Business Lead review before notifications are sent.
**Start trigger:** Confirmed eligibility list received from Identify Eligibility sub-process
**End state:** RMD amounts calculated, outliers reviewed and approved, calculation run locked; notification queue ready
**Value Stream Owner:** Distributions Value Stream

---

## Functional Requirements

| # | Requirement | Traceability | Notes |
|---|-------------|--------------|-------|
| CA-01 | Participant RMD amount must be calculated using the current plan balance and applicable divisor. | Distributions > Calculation > Calculator for RMD | |
| CA-02 | Where the participant's sole beneficiary is a spouse more than 10 years younger, the RMD amount must be calculated using the Joint Life Expectancy Table applicable divisor rather than the Uniform Lifetime Table applicable divisor. | Distributions > Calculation > Calculator for RMD | |
| CA-03 | As a VS Business Lead, I want the system to flag calculation outliers so that I can review them before notifications are sent. | *(missing)* | **⚠ PLANTED VIOLATION: Tag 3 (Agile user-story format)** |
| CA-04 | The RMD calculation should be accurate and completed quickly. | *(missing)* | **⚠ PLANTED VIOLATION: Tag 5 (Vague language — "accurate", "quickly")** |
| CA-05 | The RMD calculation batch process must complete within a 4-hour processing window. | *(missing)* | **⚠ PLANTED VIOLATION: Tag 8 (Wrong level — NFR at sub-process level)** |
| CA-06 | When a participant holds multiple accounts at the same plan sponsor, the RMD amount must be calculated per account and the aggregate total presented to the participant in the notification. | Distributions > Calculation > Calculator for RMD | |

---

## Notes

- CA-01, CA-02, CA-06 are compliant — A2 should not touch them.
- CA-03: Agile user-story format violation. A2 should flag Tag 3 and propose a rewrite (e.g., "When RMD calculation completes, outlier amounts must be flagged for VS Business Lead review before notifications are sent.")
- CA-04: Vague language. A2 should flag Tag 5 for "accurate" (unmeasurable) and "quickly" (unmeasurable). Rewrite should introduce placeholders.
- CA-05: Performance NFR placed at sub-process level. A2 should flag Tag 8 (Wrong level) and suggest moving to the Business Process page.
- CA-05 traceability missing — but since A2 should flag it as wrong-level NFR, A5 would not link it here; it belongs on the BP page under Performance.
