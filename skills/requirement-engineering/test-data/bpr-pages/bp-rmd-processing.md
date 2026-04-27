# Required Minimum Distribution Processing

## Business Process Page

| Field | Value |
|-------|-------|
| **Business Process Name** | Required Minimum Distribution Processing |
| **Description** | The end-to-end process for identifying participants who have reached or are approaching RMD eligibility age, calculating the required annual disbursement amount, engaging the participant to collect their election, validating the election and any required spousal waiver, initiating and confirming the disbursement, and archiving the completed RMD record. Runs annually for each eligible participant; initial RMD deadline is April 1 following the year the participant first reaches RMD eligibility age; subsequent RMDs are due December 31 of each year. |
| **Value Stream Owner** | Distributions Value Stream — VS Business Lead |
| **Business Service** | TBD — needs Product Owner |
| **Market Offer** | TBD — needs Value Stream Business Lead |
| **Impacted Users** | Participant, Plan Sponsor, VS Business Lead, Distributions Operations, Call Center |
| **Version History** | See table below |

### Version History

| Version | Date | Author | Change Summary |
|---------|------|--------|----------------|
| 1.0 | 2025-09-25 | [VS Business Lead] | Initial draft from A1 intake |

---

## Non-Functional Requirements

### Security

- All participant PII included in RMD notifications and election records must be masked in system and audit logs.

*Gaps: Authentication and authorisation controls not yet defined. Data classification of RMD records pending Security Architect review.*

### Performance

*TBD — needs Product Engineer and SRE input.*

### Usability

**N/A — accepted.** The participant-facing notification and election portal is governed by the Platform UX team under a separate NFR framework. The RMD process itself does not own the user interface standards. VS Business Lead confirmed 2025-09-20.

### Availability

*TBD — needs SRE input. Disbursement processing window has a hard IRS deadline dependency; availability target must account for December 31 peak load.*

### Disaster Recovery

*TBD — needs SRE input. P-tier classification not yet assigned. Interim assumption: P2 (mission-critical; affects participant compliance). Requires confirmation.*

---

## Traceability

| Component / SOP | Notes |
|----------------|-------|
| TBD — needs Product Engineer | Traceability mapping to be completed at Tollgate prep with Product Engineer per RKT Writing Guide |

---

## Sub-Processes

| # | Sub-Process Name | Description |
|---|-----------------|-------------|
| 1 | Identify Eligibility | Identifies participants at or approaching RMD eligibility age, applies exclusions, and produces a confirmed eligibility list for the current cycle |
| 2 | Calculate RMD Amount | Calculates the required minimum distribution amount for each eligible participant using the prior year plan balance and IRS-applicable divisor |
| 3 | Engage Participant | Notifies participants of their RMD obligation and collects their distribution election via portal or call center |
| 4 | Validate Elections | Validates the participant's election against the required amount, payment method, withholding election, and spousal waiver requirements |
| 5 | Submit Disbursement | Batches validated elections and initiates fund transfers; monitors for failures and triggers VS Business Lead notification |
| 6 | Notify and Confirm | Sends disbursement completion confirmation to the participant |
| 7 | Archive | Marks the participant's RMD as satisfied for the current tax year and archives all cycle records per retention policy |

---

## Open Items

| # | Item | Owner | Target date |
|---|------|-------|-------------|
| 1 | Confirm P-tier for DR classification | SRE Lead | 2025-10-15 |
| 2 | Performance targets for disbursement processing | Product Engineer + SRE | 2025-10-15 |
| 3 | Authentication and access control requirements | Security Architect | 2025-10-10 |
| 4 | Cancellation of in-flight RMD — define scope | VS Business Lead | 2025-10-20 |
| 5 | Electronic spousal waiver legal approval | Legal Counsel | Pending |
