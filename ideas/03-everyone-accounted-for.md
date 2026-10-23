# Everyone Accounted For

## One-line concept

Give a local coordinator a clear, privacy-conscious view of who has been contacted, who needs assistance, who has transport assigned, and who has arrived at an authorised destination.

## Problem

During an authorised evacuation or local assistance operation, sending an alert is only the first step. Coordinators may need to distinguish between several operational states:

- Contact attempted
- Contact confirmed
- Assistance required
- Appropriate transport assigned
- Person collected
- Person received at the destination
- Case unresolved or information conflicting

Telephone calls, paper lists, chat messages, and separate agency records can make it difficult to identify the small number of people whose needs remain unresolved.

## Primary users

- Municipal civil-protection coordinators
- Parish-level coordinators and authorised local safety officers
- Transport coordinators
- Staff at authorised reception or refuge locations

This should not be designed as a public self-evacuation application. The decision to evacuate, the destination, and the operational instructions remain with the competent authorities.

## Proposed platform

The platform tracks assistance cases from first contact to confirmed handover. It could provide:

- A queue of households or people requiring follow-up
- Accessibility, mobility, language, medical-transport, or animal-transport needs, limited to what is operationally necessary
- Transport assignment and capacity
- A timestamped history of status changes
- Destination reception and handover confirmation
- Duplicate or conflicting record warnings
- A view of unresolved cases, without presenting false certainty
- Role-based access and minimal data exposure

The tool should support telephone calls and in-person checks because residents cannot be assumed to have smartphones or connectivity.

## Hackathon scope

Create a fictional village exercise with:

- Around 20 households
- Two transport vehicles with different accessibility
- One authorised destination
- Three staff roles: local contact, transport coordinator, and destination receiver
- One duplicate record, one unreachable household, and one specialised transport need

Use entirely fictional personal data.

## Demonstration story

An authorised operation begins. Most households are contacted quickly, but one still requires accessible transport and another appears twice under slightly different addresses. The coordinator assigns an appropriate vehicle, resolves the duplicate without losing the audit history, and sees the final handover confirmed by the destination team. The platform continues to display the unreachable household as unresolved.

## Meaningful impact measures

- Time required to identify every unresolved case
- Duplicate visits or transport assignments avoided
- Percentage of collected people with confirmed handover
- Time between assistance request and transport assignment
- Number of status changes without a clear actor or timestamp
- Operator workload during a tabletop or field exercise

## Relevant Portuguese context

The concept fits the local preparation and evacuation-exercise work described by ANEPC's [Aldeia Segura, Pessoas Seguras programme](https://prociv.gov.pt/pt/prevencao-e-preparacao/programas-e-projetos/aldeia-segura-pessoas-seguras/). Its practical scope should be checked with a municipality, parish, fire brigade, and the competent data-protection staff.

## Main adoption risks

Personal information can become inaccurate, excessive, or visible to the wrong people. A viable concept needs a narrow operational purpose, clear retention rules, role-based access, an audit trail, and a process for maintaining information before an emergency. The system also needs a degraded mode for lost connectivity and a safe way to reconcile duplicated offline updates.

## Questions for deeper exploration

1. Is the useful unit a person, household, address, or assistance case?
2. Who is legally and operationally authorised to view and update each field?
3. Which information must exist before an event, and which should be collected only during one?
4. How is arrival or handover confirmed today?
5. What is the paper fallback, and how are paper updates reconciled later?

## Prompt for a follow-up thread

Explore Everyone Accounted For as a Portuguese hackathon project supporting an authorised local evacuation or assistance exercise. Define the narrow MVP, roles, state transitions, privacy model, offline and paper fallback, fictional demo scenario, measurable outcomes, and interview questions. Avoid designing emergency policy or public evacuation instructions; focus on coordination and confirmed handover.
