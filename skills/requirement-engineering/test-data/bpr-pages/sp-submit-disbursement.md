# Sub-Process: Submit Disbursement

**Parent Business Process:** Required Minimum Distribution Processing
**Sub-process description:** Batches validated elections and submits them to the disbursement processing engine. Monitors for failures, notifies the VS Business Lead of failures requiring intervention, and confirms completion once funds are transferred.
**Start trigger:** Election record status is "Validated"; daily batch submission window at 3:00 PM EST
**End state:** Disbursement confirmed complete and participant record updated to reflect RMD satisfied for the current tax year
**Value Stream Owner:** Distributions Value Stream

---

## Functional Requirements

| # | Requirement | Traceability | Notes |
|---|-------------|--------------|-------|
| SD-01 | When a participant's election is validated, the disbursement must be initiated within the next scheduled batch submission window. | Distributions > Disbursement > Disbursement Processing Engine | |
| SD-02 | The plan sponsor confirms receipt of the disbursement notification before the participant RMD record is updated to "satisfied." | *(missing)* | **⚠ PLANTED VIOLATION: Tag 2 (Missing standard word — "confirms" has no modal verb)** |
| SD-03 | If disbursement fails due to invalid payment account information, the VS Business Lead must be notified within 24 hours of the failure. | Communications > Notifications > Failure Notifications | |
| SD-04 | If disbursement fails, the participant must be notified to provide updated payment account information. | Communications > Notifications > RMD Notifications | |
| SD-05 | When disbursement is confirmed complete, the participant's RMD status for the current tax year must be updated to "satisfied." | Distributions > Disbursement > Disbursement Processing Engine | |
| SD-06 | Plan sponsor must receive a disbursement summary report for each batch submission day. | *(missing)* | |

---

## Notes

- SD-01, SD-03, SD-04, SD-05 are compliant — A2 should not flag them.
- SD-02: Missing standard word. "confirms" is used without a modal verb (must/shall/should/may/will), making the obligation level ambiguous. Also unclear whether the plan sponsor *must* confirm or whether confirmation is optional. A2 should flag Tag 2 and propose a rewrite such as: "Plan sponsor must receive confirmation of disbursement completion before the participant RMD record is updated to 'satisfied'." (Also worth noting: this may be a Tag 6 "Doesn't know the user" nuance — the actor is "plan sponsor" but the action is the platform updating the record, not the plan sponsor actively confirming. A2 may flag this as borderline.)
- SD-06 is compliant in form but traceability is missing — A5 should propose Disbursement Processing Engine (High confidence, "plan sponsor report" aligns with the component's "plan sponsor reporting" capability).
- SD-02 traceability missing — A5 should propose Account Record or Disbursement Processing Engine (Medium confidence — "RMD record updated to satisfied" maps to Account Record, but the confirmation trigger is ambiguous).
