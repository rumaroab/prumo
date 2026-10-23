# Before You Arrive

## One-line concept

Give incoming emergency crews a short, verified, offline operational brief containing the local knowledge that normally exists only in the heads of local firefighters, municipal staff, and residents.

## Problem

Crews supporting an incident outside their usual area may see roads, buildings, and water points on a map without knowing the details that determine whether those features are usable. A road may be too narrow for a tanker, a bridge may have a weight restriction, a gate may be locked, a vehicle may have no place to turn around, or a mapped water point may be inaccessible.

This is primarily an information freshness and trust problem. The useful question is not merely "where is the road?" but "who last confirmed that this road is usable by this type of vehicle, and when?"

## Primary users

- Incoming fire crews and team leaders
- Local fire brigades
- Municipal civil-protection and forestry teams
- Incident logistics and planning staff

## Proposed platform

The platform maintains small operational briefs for villages or predefined response areas. Each brief could contain:

- Vehicle-specific access notes and turnaround locations
- Gates, keys, restrictions, and useful local contacts
- Water points with type, capacity, access, and last verification
- Refuge or assembly locations
- Photographs taken from the approach direction
- Known communication blind spots
- Temporary observations such as roadworks, fallen trees, or unavailable water points

Every observation has a source, timestamp, confidence level, and expiry or review date. Conflicting reports remain visible until an authorised user resolves them.

The field experience should remain useful with poor connectivity. A crew downloads or receives a compact brief before departure and can later synchronise observations made in the field.

## Hackathon scope

Choose one parish or small cluster of villages. Model approximately:

- 10–20 access observations
- 5–10 water or refuge points
- Two vehicle profiles, such as a light vehicle and a heavy tanker
- Three user roles: contributor, verifier, and field reader

The project does not need live integrations with emergency systems. Use public geographic data plus clearly marked sample operational observations.

## Demonstration story

An external crew is assigned to a village. Its offline brief initially recommends one approach. A local operator then reports a blocked entrance and attaches a photograph. The platform marks the old route as unavailable, shows who reported it and when, and highlights the remaining verified access information. The crew receives the updated brief without having to search across documents or call several people.

## Meaningful impact measures

- Time required to answer an access or water-point question
- Percentage of operational observations with a current verification
- Number of calls or messages needed to resolve a local-information question
- Time between a field observation and its availability to another crew
- Incorrect or stale facts identified during an exercise

## Public data that can support it

- [ICNF geographic catalogue](https://geocatalogo.icnf.pt/catalogo.html), including water points and fire-related layers
- [ICNF water-point map service](https://sigservices.icnf.pt/server/rest/services/BDG/Pontos_agua/MapServer/0)
- [DGT SMOS/COS land-use data](https://www.dgterritorio.gov.pt/atividades/cartografia/cartografia-tematica/SMOS-CLMS)
- OpenStreetMap for the initial road and building base map

Public data should provide context rather than be treated as proof that an operational feature is currently usable.

## Main adoption risk

The platform loses value if observations are not reviewed. The concept therefore needs an explicit maintenance workflow: who may verify a fact, what becomes stale, what is archived, and how routine exercises or inspections update the records.

## Questions for deeper exploration

1. Which five pieces of local knowledge most often require a phone call?
2. What information can safely be visible to every responder, and what requires restricted access?
3. Who is already responsible for inspecting roads, water points, and refuge areas?
4. How should vehicle constraints be represented without promising safe routing?
5. Would brigades prefer an area brief, a route brief, or a searchable map?

## Prompt for a follow-up thread

Explore this hackathon concept as a product and operational workflow. Identify the narrowest useful MVP, the exact user journey, the data model, trust and verification rules, an offline interaction design, a five-minute demo, validation interviews, and the strongest objections. Keep the design realistic for one Portuguese municipality or fire brigade and do not assume access to sensitive live emergency-system data.
