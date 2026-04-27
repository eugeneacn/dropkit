# Ubiquitous Language — RKT Retirement Platform (RMD Domain)

Version 2.1 | Owner: VS Business Lead, Distributions Value Stream

---

## Domain Terms

| Term | Definition | Notes |
|------|-----------|-------|
| **Participant** | An individual enrolled in a qualified retirement plan who is subject to RMD rules. | Do not use "customer," "account holder," "member," or "retiree" — use "participant." |
| **Plan Sponsor** | The employer or organization that establishes and maintains the retirement plan on behalf of participants. | Do not use "employer" or "company." |
| **RMD (Required Minimum Distribution)** | The minimum amount that federal tax law requires a participant to withdraw from a qualified retirement account each year once they reach RMD eligibility age. | Always spell out on first use; abbreviation RMD is acceptable thereafter. |
| **RMD Eligibility Age** | The age at which a participant becomes subject to mandatory annual withdrawals. Currently age 73 per SECURE 2.0 Act. | Do not hard-code the age in requirements — reference "RMD eligibility age" to accommodate future legislative changes. |
| **IRS Deadline** | The required-by date for an RMD withdrawal: April 1 of the year following the year the participant first reaches RMD eligibility age (initial RMD only); December 31 of each subsequent calendar year. | |
| **Plan Balance** | The fair market value of a participant's retirement account as of December 31 of the prior calendar year, used as the basis for the current year's RMD calculation. | Do not use "account balance" or "year-end balance." |
| **Applicable Divisor** | The IRS life expectancy factor used to calculate the RMD amount. Derived from the Uniform Lifetime Table or, where the sole beneficiary is a spouse more than 10 years younger, the Joint Life Expectancy Table. | Do not use "IRS factor," "divisor," or "life expectancy number." |
| **RMD Amount** | The calculated required minimum distribution for a specific participant for the current tax year. Equal to Plan Balance divided by Applicable Divisor. | |
| **Spousal Waiver** | A signed consent form required from the spouse of a participant who is electing a distribution form other than a qualified joint and survivor annuity. | Do not use "spouse consent," "spousal consent form," or "waiver form." |
| **E-delivery Preference** | A participant's registered preference to receive account communications via electronic delivery (email or secure message portal) rather than postal mail. | Do not use "email preference," "paperless," or "digital preference." |
| **Election** | A participant's formal, recorded choice regarding RMD distribution amount, timing, payment method, and withholding. | |
| **Disbursement** | The payment or transfer of RMD funds from a participant's retirement account to a designated payee. | Do not use "distribution," "payment," or "withdrawal" — use "disbursement." |
| **In-flight RMD** | An RMD transaction that has been initiated (election recorded and submitted) but not yet completed (funds not yet transferred). | |
| **VS Business Lead** | Value Stream Business Lead. The senior business representative accountable for process design and requirements within a value stream. | Do not abbreviate further. |
| **Product Engineer** | The engineer within a value stream responsible for technical solutioning, domain component mapping, and Engineering Hub handoff. | |
| **Tollgate** | A formal gated review checkpoint in the RKT process at which artifacts must meet the Definition of Ready before progressing to the next phase. | Capitalise; do not use "gate," "review checkpoint," or "sign-off." |
| **Domain Component** | A catalogued system capability within the domain hierarchy (Domain > Sub-domain > Component) that supports business requirements. Used as the unit of traceability for system-supported requirements. | |
| **SOP** | Standard Operating Procedure. A documented manual process followed by operations staff where no system support exists. Used as the unit of traceability for manually-supported requirements. | |
| **Withholding Election** | A participant's choice of federal and/or state tax withholding percentage to apply to their disbursement. | |
| **QJSA (Qualified Joint and Survivor Annuity)** | A form of retirement benefit payment that provides a life annuity to the participant and a survivor annuity to the spouse. Requires spousal waiver if participant elects a different form. | |

---

## Acronyms

| Acronym | Expansion |
|---------|-----------|
| RMD | Required Minimum Distribution |
| QJSA | Qualified Joint and Survivor Annuity |
| SOP | Standard Operating Procedure |
| VS | Value Stream |
| PII | Personally Identifiable Information |
| RKT | Recordkeeping Transformation |
| IRS | Internal Revenue Service |
| SECURE 2.0 | Setting Every Community Up for Retirement Enhancement Act of 2022 |

---

## Out-of-scope terms (do not use in BPRs)

These terms have been intentionally excluded from this domain's vocabulary. If they appear in requirements, flag for clarification.

| Term to avoid | Use instead |
|---|---|
| customer | participant |
| account holder | participant |
| account balance | plan balance |
| employer | plan sponsor |
| distribution | disbursement |
| payment | disbursement |
| withdrawal | disbursement |
| divisor | applicable divisor |
| life expectancy factor | applicable divisor |
| email preference | e-delivery preference |
| digital preference | e-delivery preference |
