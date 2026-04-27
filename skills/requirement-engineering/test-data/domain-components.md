# Domain Component Corpus — Distributions Value Stream

**Version:** 3.0
**Owner:** Product Engineer, Distributions Value Stream
**Last updated:** 2025-08-01

This document lists the catalogued domain components available for traceability mapping in the Distributions value stream. Used as input to the Traceability Linker (A5).

---

## Domain: Distributions

### Sub-domain: Calculation

#### Component: Calculator for RMD
**Description:** Computes required minimum distribution amounts for eligible participants using IRS-approved life expectancy divisors and prior-year account balances. Supports Uniform Lifetime Table and Joint Life Expectancy Table calculations. Produces a per-participant, per-account RMD amount for the current tax year.
**Supports:** System-supported requirements
**Key capabilities:** Balance retrieval, divisor lookup, amount computation, outlier flagging, multi-account aggregation

---

#### Component: Eligibility Evaluator
**Description:** Determines and maintains RMD eligibility status for each participant account. Evaluates participant age against the RMD eligibility age threshold, applies account-type exclusions (Roth IRA, inherited accounts), and flags participants for the upcoming eligibility population.
**Supports:** System-supported requirements
**Key capabilities:** Age-based eligibility determination, Roth exclusion logic, exception flagging, eligibility list generation and lock

---

### Sub-domain: Disbursement

#### Component: Disbursement Processing Engine
**Description:** Initiates, tracks, and records the transfer of funds from participant retirement accounts to designated payees. Manages the full disbursement lifecycle from election submission to fund transfer confirmation. Handles batch submission, failure detection, and status updates.
**Supports:** System-supported requirements
**Key capabilities:** Batch processing, fund transfer initiation, failure detection and notification, status lifecycle management, plan sponsor reporting

---

#### Component: Election Processing
**Description:** Captures, validates, and records participant distribution elections. Validates election amount against the calculated RMD amount, confirms payment method validity, checks withholding election presence, and applies default withholding where absent. Routes elections requiring manual review to the VS Business Lead queue.
**Supports:** System-supported requirements
**Key capabilities:** Election capture, amount validation, payment method validation, withholding default application, manual review routing, election status management

---

### Sub-domain: Withholding

#### Component: Withholding Calculator
**Description:** Calculates and applies federal and state tax withholding amounts to disbursements based on participant withholding elections. Applies default withholding rates where no election is provided.
**Supports:** System-supported requirements
**Key capabilities:** Federal withholding calculation, state withholding calculation, default rate application, withholding confirmation

---

## Domain: Communications

### Sub-domain: Notifications

#### Component: RMD Notifications
**Description:** Generates and manages RMD-specific participant communications, including educational notices for first-year eligible participants, annual reminder notifications with calculated amounts, follow-up notices for non-responsive participants, and disbursement completion confirmations.
**Supports:** System-supported requirements
**Key capabilities:** Educational notification generation, reminder notification generation, follow-up scheduling, completion confirmation, delivery status tracking

---

#### Component: Communication Preferences
**Description:** Manages participant communication channel preferences. Determines whether communications are delivered via e-delivery (email or secure portal) or postal mail based on the participant's registered preference. Routes all outbound communications through the appropriate channel.
**Supports:** System-supported requirements
**Key capabilities:** Preference lookup, channel routing, delivery preference enforcement

---

#### Component: Failure Notifications
**Description:** Generates and delivers operational failure notifications to internal staff (VS Business Lead, Distributions Operations) when automated processes encounter errors requiring human intervention.
**Supports:** System-supported requirements
**Key capabilities:** VS Business Lead failure alerts, disbursement failure notifications, SLA-based escalation

---

## Domain: Participant

### Sub-domain: Account Management

#### Component: Account Record
**Description:** Maintains core participant account information including plan balance history, plan type classification, RMD eligibility status, and account-level flags (QDRO holds, spousal beneficiary designation, RMD satisfied status). The authoritative source of participant account state.
**Supports:** System-supported requirements
**Key capabilities:** Balance history maintenance, eligibility flag management, RMD satisfied status tracking, QDRO hold management

---

### Sub-domain: Eligibility

*See Distributions > Calculation > Eligibility Evaluator for RMD-specific eligibility logic.*

---

## Domain: Compliance

### Sub-domain: Records Retention

#### Component: RMD Archive
**Description:** Archives completed RMD cycle records (election, calculation, notification, and disbursement records) per the firm's records retention policy. Supports 7-year retention requirement for retirement account transactions.
**Supports:** System-supported requirements
**Key capabilities:** Record archival, retention period enforcement, retrieval for audit, handoff flag for 1099-R generation

---

## Standard Operating Procedures (manually-supported requirements)

| SOP ID | Title | Description |
|--------|-------|-------------|
| SOP-RMD-001A | Manual RMD Eligibility Review | VS Business Lead procedure for reviewing and resolving exception cases in the eligibility population (QDRO, inherited accounts) |
| SOP-RMD-002 | Spousal Waiver Collection — Paper | Step-by-step procedure for operations staff to collect, review, and process spousal waiver forms submitted by participants via postal mail |
| SOP-RMD-003 | Participant Phone Election | Script and procedure for call center agents assisting participants making RMD elections by phone |
| SOP-RMD-004 | Disbursement Failure Resolution | VS Business Lead procedure for investigating and resolving failed disbursements including participant outreach and payment detail updates |

---

## Coverage gaps

The following scenarios currently have **no domain component or SOP** to map to:

- **Cancellation of in-flight RMD** — no component or SOP exists. Handled ad hoc. Any requirement describing cancellation of a submitted but not yet disbursed RMD will require manual traceability mapping pending a decision on whether to build this capability.
