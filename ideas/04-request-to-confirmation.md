# Request to Confirmation

## One-line concept

Make one cross-organisation operational workflow visible from request through ownership, dependencies, execution, and confirmation by the receiving party.

## Problem

A request can be transmitted without being operationally complete. For example, a municipality may request transport, an organisation may acknowledge it, a vehicle may be assigned, and yet the action may still depend on confirming the collection point, access, capacity, or receiving destination.

The coordination failure is often hidden between states such as "message sent," "request accepted," "resource assigned," and "outcome confirmed."

Portugal already has national information and interoperability initiatives, including the SGIFR's PLIS. A viable hackathon concept therefore needs to solve one sharply defined handoff rather than present itself as a replacement for national command or incident-management systems.

## Primary users

The exact users depend on the selected workflow. A transport-request example might include:

- Municipal civil protection
- A transport provider or supporting organisation
- A field collection team
- Staff at an authorised destination

## Proposed platform

The platform represents each operational request with:

- Requesting organisation and responsible person
- Precise requested outcome
- Priority and required-by time
- Acknowledgement and current owner
- Dependencies and blockers
- Assigned resource
- Status updates with actor and timestamp
- Completion evidence
- Confirmation or rejection by the receiving party
- A concise decision and handover history

The most useful view is likely an exception queue: unowned requests, overdue acknowledgements, unresolved dependencies, and actions awaiting confirmation.

## Hackathon scope

Select exactly one workflow. Good candidates include:

- Municipal request for assisted transport
- Request to verify a road or water point
- Request for a local liaison or access key
- Request to prepare and confirm an authorised reception location

Build three role-based views and approximately ten requests in one scenario. Avoid creating a generic incident dashboard.

## Demonstration story

A municipality requests transport for several people. The provider acknowledges the request and assigns a vehicle. The collection team cannot proceed because access for the selected vehicle has not been confirmed. The platform exposes that dependency, assigns verification to a named owner, records the answer, and later captures confirmation that the passengers were received.

## Meaningful impact measures

- Time from request to acknowledgement
- Requests without a current owner
- Time spent waiting on an unresolved dependency
- Duplicate follow-up calls or messages
- Completed actions without receiving-party confirmation
- Data-entry time per request

## Relevant Portuguese context

- [AGIF overview of the SGIFR](https://www.agif.pt/pt/sobre-o-sgifr)
- [AGIF description of PLIS](https://www.agif.pt/pt/apresentacao-dos-projetos-plataforma-interoperavel-do-sgifr-e-voo-lidar)
- [ANEPC Aldeia Segura, Pessoas Seguras](https://prociv.gov.pt/pt/prevencao-e-preparacao/programas-e-projetos/aldeia-segura-pessoas-seguras/) for potential local exercise workflows

These references establish the institutional context. Interviews are required to determine whether a particular handoff is already covered and where the actual delay occurs.

## Main adoption risks

An extra coordination tool can increase work during an emergency. The project must demonstrate that it replaces repeated calls, messages, or manual reconciliation. Integration may eventually be important, but the first validation should test the workflow and information states before attempting technical integration.

## Questions for deeper exploration

1. Which request most often requires repeated follow-up?
2. What event constitutes acknowledgement, assignment, completion, and confirmation?
3. Which dependencies are commonly discovered too late?
4. Can updates be captured from existing actions rather than requiring duplicate entry?
5. Who has authority to close or reject a request?

## Prompt for a follow-up thread

Explore Request to Confirmation as a hackathon project. First choose one concrete cross-organisation workflow in Portuguese rural-fire response. Map its actors, request states, dependencies, failure modes, current communication channels, minimum interface, five-minute demo, and validation metrics. Treat existing national systems as part of the environment and define a complementary role rather than assuming they are absent.
