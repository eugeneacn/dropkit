# Street-View Map — Required Minimum Distribution Processing

**Process:** Required Minimum Distribution Processing
**Version:** Future-state (post-platform migration)
**Format:** Swim-lane description (Visio source available separately)
**Date:** 2025-09-20

---

## Swim lanes

The map has five actor swim lanes running horizontally:

- **Participant** (top)
- **VS Business Lead**
- **Distributions Platform** (system)
- **Distributions Operations** (manual/operations staff)
- **Plan Sponsor** (bottom)

---

## Phase descriptions

### A. IDENTIFY ELIGIBILITY

**Trigger:** Annual process; initiates October 1 each year

Activities visible in swim lane:
- *Distributions Platform:* Run eligibility scan across all participant records; flag participants at or approaching RMD eligibility age; generate exception list
- *VS Business Lead:* Review exception list; confirm or exclude flagged participants; apply manual overrides (QDRO holds, inherited account flags)
- *Distributions Platform:* Lock confirmed eligibility list; pass to calculation phase

**Handoff out:** Confirmed eligibility list → Phase B

---

### B. CALCULATE RMD AMOUNT

**Trigger:** Confirmed eligibility list received from Phase A

Activities visible in swim lane:
- *Distributions Platform:* Retrieve plan balance (Dec 31 prior year) per participant; retrieve applicable divisor from IRS table; compute RMD amount; flag outliers
- *VS Business Lead:* Review flagged outliers; approve or investigate; confirm calculation run complete
- *Distributions Platform:* Calculation results locked; notifications queued

**Handoff out:** Calculated RMD amounts → Phase C

**Boundary note (seam):** The "flag outliers" activity could belong to Phase B (as part of calculation validation) or Phase C (as part of pre-notification review). Currently shown in Phase B.

---

### C. ENGAGE PARTICIPANT

**Trigger:** Calculation confirmed; IRS deadline 90+ days away for first-year RMDs, 60 days for subsequent

Activities visible in swim lane:
- *Distributions Platform:* Generate educational notification (first-year participants) or reminder notification (existing RMD participants); send via participant's e-delivery preference
- *Participant:* Receives notification; reviews RMD amount and deadline
- *Distributions Platform:* If no response after 30 days, send follow-up notification
- *Participant:* Makes election (via portal or calls call center)

**Handoff out:** Election submitted → Phase D
**Parallel path:** Participant calls call center → Call Center follows SOP-RMD-003; election submitted → Phase D

---

### D. VALIDATE ELECTIONS

**Trigger:** Election received

Activities visible in swim lane:
- *Distributions Platform:* Validate election amount (≥ RMD amount?); validate payment method; check spousal waiver requirement; check withholding election present
- *Distributions Platform:* If validation passes → proceed to Phase E
- *Distributions Operations:* If spousal waiver required and not on file → collect waiver per SOP-RMD-002; update election status when received
- *VS Business Lead:* Review elections that cannot be auto-validated; approve or reject within 2 business days
- *Participant:* Notified if waiver required or if election is held

**Handoff out:** Validated election → Phase E

---

### E. SUBMIT DISBURSEMENT

**Trigger:** Election validated; batch submission at 3:00 PM EST daily

Activities visible in swim lane:
- *Distributions Platform:* Batch validated elections; submit to disbursement engine; receive confirmation or failure status
- *VS Business Lead:* Notified of failures; investigates and resolves within SLA
- *Participant:* Notified of failure (if applicable); provides updated payment details
- *Plan Sponsor:* Receives daily disbursement summary report

**Handoff out:** Disbursement confirmed complete → Phase F

---

### F. NOTIFY AND CONFIRM

**Trigger:** Disbursement confirmed complete

Activities visible in swim lane:
- *Distributions Platform:* Generate completion confirmation; send to participant via e-delivery preference
- *Participant:* Receives confirmation notification

**Handoff out:** Confirmation sent → Phase G

---

### G. ARCHIVE

**Trigger:** RMD cycle complete for participant

Activities visible in swim lane:
- *Distributions Platform:* Mark participant RMD status as "satisfied" for current tax year; archive all RMD records (election, calculation, notifications, disbursement) per retention policy (7 years)
- *Distributions Platform:* Flag records for 1099-R generation in January (Tax Operations handoff)

**Handoff out:** Records archived → Process end (for current tax year)

---

## Exception paths shown on map

- **No election received by deadline:** VS Business Lead escalation lane shows manual intervention; not decomposed further in this map
- **Disbursement failure:** Loop back from Phase E to VS Business Lead lane; resolved within Phase E (not a separate sub-process on the current map)
- **Spousal waiver not received within 30 days:** Operations escalation note within Phase D

## Exception paths NOT shown on map

- **Cancellation of in-flight RMD:** No swim lane or activity exists for this scenario. The SOP notes it as an ad hoc exception. This is a known gap flagged by the VS Business Lead — a decision on whether to add a sub-process for this scenario is pending.
- **Participant deceased mid-cycle:** Escalation to Beneficiary Processing (out of scope)
