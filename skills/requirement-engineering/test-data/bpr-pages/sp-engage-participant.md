# Sub-Process: Engage Participant

**Parent Business Process:** Required Minimum Distribution Processing
**Sub-process description:** Notifies participants of their RMD obligation and calculated amount, and collects their distribution election through the portal or call center channel.
**Start trigger:** RMD calculation run locked; 90 days before IRS deadline for first-year participants, 60 days for returning participants
**End state:** Participant election submitted and received; election record created with status "Pending Validation"
**Value Stream Owner:** Distributions Value Stream

---

## Functional Requirements

| # | Requirement | Traceability | Notes |
|---|-------------|--------------|-------|
| EN-01 | When a participant reaches RMD eligibility age for the first time, an educational notification must be sent via the participant's e-delivery preference no later than 90 days before the IRS deadline. | Communications > Notifications > RMD Notifications | |
| EN-02 | When a participant has an active RMD obligation in a subsequent year, a reminder notification including the calculated RMD amount must be sent via the participant's e-delivery preference no later than 60 days before the IRS deadline. | Communications > Notifications > RMD Notifications | |
| EN-03 | The engagement notification must be generated using the NotificationService.sendRMDEmail() API method and stored in the COMM_LOG database table before delivery is attempted. | *(missing)* | **⚠ PLANTED VIOLATION: Tag 1 (HOW not WHAT) + Tag 4 (Contains design details)** |
| EN-04 | If a participant has not submitted an election within 30 days of the initial notification, a follow-up notification must be sent via the participant's e-delivery preference. | Communications > Notifications > RMD Notifications | |
| EN-05 | When a participant submits an election via the portal, an election record must be created with status "Pending Validation." | Distributions > Disbursement > Election Processing | |
| EN-06 | Where a participant contacts the call center to make their election, the call center agent must follow SOP-RMD-003 and submit the election on the participant's behalf. | SOP-RMD-003 | |

---

## Notes

- EN-01, EN-02, EN-04, EN-05, EN-06 are compliant — A2 should not flag them.
- EN-03 is the planted violation: "NotificationService.sendRMDEmail()" is a named API method (Tag 4) and "generated using... API method and stored in... table" describes HOW (Tag 1). A2 should flag both and propose a rewrite such as: "When a participant notification is ready to send, the notification must be delivered via the participant's e-delivery preference and a delivery record must be created."
- EN-03 traceability missing — A5 should propose RMD Notifications (High confidence) since the term "engagement notification" + "e-delivery" maps clearly via UL doc to this component.
- EN-01, EN-02, EN-04 have traceability already filled — A5 should skip these.
