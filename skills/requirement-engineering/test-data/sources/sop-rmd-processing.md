# SOP-RMD-001: Required Minimum Distribution Processing

**Version:** 4.2
**Effective date:** 2024-01-01
**Owner:** Distributions Operations Team
**Review cycle:** Annual

---

## Purpose

This SOP describes the end-to-end process for identifying participants subject to the Required Minimum Distribution rules, calculating the required amount, notifying and engaging the participant, collecting their election, and completing the disbursement by the IRS deadline.

---

## Scope

Applies to all qualified retirement plan accounts administered on the recordkeeping platform where the participant has reached or is approaching RMD eligibility age. Excludes Roth IRA accounts (not subject to RMDs during owner's lifetime) and inherited accounts (governed by SOP-RMD-005).

---

## Process Steps

### Phase 1: Identify RMD-Eligible Participants

1. Each year on October 1, the Distributions Operations team initiates the eligibility identification run.
2. The system reviews all active participant records and flags those who will reach RMD eligibility age by December 31 of the following year. This creates the "upcoming eligibility" population.
3. The system also flags participants who are already RMD-eligible and have not yet taken their current-year RMD.
4. The VS Business Lead reviews the flagged population for exceptions (inherited accounts, QDRO situations, participants who have already taken a distribution that satisfies the RMD). Manual review cases are escalated per SOP-RMD-001A.
5. Once the eligibility list is confirmed, it is locked and passed to the Calculation phase.

**Output:** Confirmed eligibility list with participant IDs, plan IDs, and eligibility status.

### Phase 2: Calculate RMD Amounts

1. For each participant on the confirmed eligibility list, the system retrieves the plan balance as of December 31 of the prior year.
2. The system determines the applicable divisor from the IRS Uniform Lifetime Table based on the participant's age as of December 31 of the current year. If the participant's sole beneficiary is a spouse more than 10 years younger, the Joint Life Expectancy Table applies; this flag must be set on the account by the VS Business Lead before calculation runs.
3. The system calculates the RMD amount: Plan Balance ÷ Applicable Divisor = RMD Amount.
4. For participants with multiple plan accounts at the same plan sponsor, amounts are calculated per-account. The participant may satisfy the aggregate RMD by taking the total from one or more accounts (this aggregation rule is noted in the participant notification).
5. Calculated amounts are reviewed by the VS Business Lead for outliers (amounts that appear disproportionately high or low relative to the prior year). Outliers are investigated before notifications are sent.

**Output:** RMD amount per participant per account, ready for notification.

### Phase 3: Engage Participants

1. For participants approaching eligibility (first RMD year), an educational notification is generated and sent via the participant's e-delivery preference approximately 90 days before the IRS deadline.
2. For existing RMD participants, a reminder notification is generated and sent 60 days before the IRS deadline, including the calculated RMD amount.
3. The notification includes: the RMD amount, the applicable deadline, a link to the election portal, information about withholding options, and spousal waiver requirements (where applicable).
4. If a participant does not respond within 30 days of the initial notification, a follow-up notification is automatically sent.
5. Participants may contact the call center at any point to make their election by phone. Call center agents follow SOP-RMD-003.

**Output:** Notification records with delivery status.

### Phase 4: Validate Elections

1. When a participant submits an election via the portal or by phone, the election record is created with status "Pending Validation."
2. The system checks:
   a. Is the elected amount ≥ the calculated RMD amount? (Partial elections are allowed; multiple distributions can satisfy the requirement.)
   b. Is the payment method valid? (bank account on file, check mailing address confirmed)
   c. Does the plan type require a spousal waiver? (For plans subject to QJSA rules, a spousal waiver must be on file before disbursement proceeds.)
3. If a spousal waiver is required and not on file, the election is held in "Pending Waiver" status. The participant and spouse are notified. Operations staff follow SOP-RMD-002 to collect the waiver.
4. A withholding election must accompany every disbursement. If the participant does not provide one, the system applies the default federal withholding rate (10%) and zero state withholding. The participant is notified of the default applied.
5. The VS Business Lead reviews elections that cannot be automatically validated and approves or rejects them within 2 business days.

**Output:** Validated election records ready for disbursement, or held elections with documented reason.

### Phase 5: Submit Disbursement

1. Validated elections are batched and submitted to the Disbursement Processing engine each business day at 3:00 PM EST.
2. The Disbursement Processing engine initiates the fund transfer.
3. If a disbursement fails (invalid account, rejected bank transfer), the VS Business Lead is notified within 24 hours and the participant record is updated with failure status. The participant is notified to provide updated payment information.
4. The plan sponsor receives a daily disbursement summary report.
5. Once disbursement is confirmed complete, the participant record is updated to reflect the RMD as satisfied for the current year.

**Output:** Completed disbursement records; participant RMD status updated to "satisfied."

### Phase 6: Post-Disbursement

1. An RMD completion confirmation is sent to the participant via e-delivery preference within 1 business day of disbursement completion.
2. All RMD records (election, calculation, disbursement, notifications) are retained per the firm's records retention policy (7 years).
3. Tax reporting (Form 1099-R) is generated in January of the following year for all disbursements made in the current tax year.

**Output:** Confirmation notifications sent; records archived.

---

## Exception Handling

- **Participant deceased:** Escalate to Beneficiary Processing team; remove from current RMD cycle.
- **Account in QDRO:** Flag for manual review; do not calculate until legal hold is resolved.
- **Participant requests cancellation of in-flight RMD:** Contact VS Business Lead immediately. If disbursement has not been submitted to the bank, cancellation may be possible. If funds have been transferred, cancellation is not possible and participant must be informed. (No formal sub-process exists for this; handled ad hoc — flagged as a process gap in the 2024 process review.)
- **Plan Sponsor requests to override RMD:** Not permitted; escalate to Compliance team.

---

## Roles and Responsibilities

| Role | Responsibility in this process |
|------|-------------------------------|
| Distributions Operations | Day-to-day processing, exception handling, manual waiver collection |
| VS Business Lead | Population review, outlier review, election validation oversight |
| Call Center | Phone-based election capture per SOP-RMD-003 |
| Compliance | Override requests, regulatory questions |
| Product Engineer | System support, calculation configuration, domain component updates |
