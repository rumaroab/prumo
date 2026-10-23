# After the Fire, Before the Rain

## One-line concept

Help a municipality turn a burned-area perimeter and a rain forecast into a reasoned, updateable field-inspection plan.

## Problem

After a rural fire, rainfall can create additional concerns: erosion, debris movement, blocked drainage, slope instability, effects on roads and structures, and possible impacts on water sources. Municipal teams have limited time and field capacity, so they need to decide which locations should be inspected first.

The useful output is a screening and inspection queue with visible reasons. It is not an engineering diagnosis or an automatic declaration that a location is safe.

## Primary users

- Municipal civil-protection teams
- Municipal environment, roads, and public-works teams
- Forestry and watershed staff
- Field inspection teams

## Proposed platform

The platform combines a supplied burn perimeter with terrain, drainage, infrastructure, exposed assets, and rainfall information. It identifies candidate inspection locations and lets an authorised coordinator prioritise and assign them.

A candidate could be flagged because of a combination such as:

- Steep burned terrain above a road or settlement
- A drainage crossing below a burned catchment
- A water intake or reservoir downstream
- A culvert or bridge with limited capacity
- An area with a known history of erosion or blockage
- Heavy forecast rainfall before an inspection has occurred

Each priority should show the contributing evidence, uncertainty, last review, assigned team, and field outcome. Field teams should be able to attach photographs and mark whether specialist assessment is required.

## Hackathon scope

Use one historical or synthetic burned perimeter and:

- A digital elevation model
- A small road and drainage network
- Ten candidate assets or inspection sites
- Two field teams
- Two rainfall scenarios

Create simple, transparent screening rules with expert-readable assumptions. The challenge is prioritisation and workflow, not high-fidelity debris-flow modelling.

## Demonstration story

The initial forecast suggests moderate rain, producing a manageable inspection queue. A revised forecast increases rainfall intensity. Two drainage crossings and a road below steep burned ground move upward in priority. The coordinator assigns teams, receives a field photograph showing one culvert is clear, and escalates another location for specialist assessment.

## Meaningful impact measures

- Time required to produce an initial inspection plan
- Percentage of high-priority locations inspected before forecast rain
- Travel time needed to cover the assigned inspections
- Number of priorities with a clearly stated reason and data provenance
- Difference between screening result and field assessment
- Time from field observation to reassignment or escalation

## Public data that can support it

- [ICNF burned-area map service](https://sigservices.icnf.pt/server/rest/services/BDG/areas_ardidas/MapServer)
- [DGT terrain and LiDAR products](https://www.dgterritorio.gov.pt/atividades/cartografia/cartografia-topografica/modelos-digitais)
- [Copernicus Data Space STAC API](https://documentation.dataspace.copernicus.eu/APIs/STAC.html) for a 30 m DEM and Earth-observation products
- [IPMA Open Data](https://api.ipma.pt/) for Portuguese observations and available forecasts
- Municipal road, drainage, water, and infrastructure inventories where available

ANEPC has explicitly highlighted post-fire concerns involving slope instability, transport infrastructure, and water quality in its [hydrological-year guidance](https://prociv.gov.pt/pt/noticias/01102026-inicio-do-ano-hidrologico/).

## Main adoption risks

Simple risk scores can appear more authoritative than their evidence supports. The platform must expose the rules, data age, missing layers, and uncertainty. Experts should define escalation thresholds, and field or engineering assessment must remain the basis for intervention decisions.

## Questions for deeper exploration

1. Which municipal team currently creates the first post-fire inspection list?
2. What locations have caused problems after previous fires?
3. Which infrastructure inventories are current enough to use?
4. What forecast quantity and time horizon trigger action today?
5. Which screening rules can an engineer or civil-protection officer defend and validate?

## Prompt for a follow-up thread

Explore After the Fire, Before the Rain as a hackathon product for one Portuguese municipality. Define a transparent screening method, minimum spatial data, coordinator and field-team workflows, uncertainty communication, a five-minute demonstration, validation against a historical case or tabletop exercise, and clear boundaries between prioritisation and professional engineering assessment.
