# Water Turnaround

## One-line concept

Help the command and logistics structure choose and run refill circuits that return the greatest useful volume of water to the incident over time.

## Problem

The geographically closest water point is not necessarily the quickest operational choice. A useful comparison may need to consider:

- Whether the point is currently usable
- Terrestrial, aerial, or mixed compatibility
- Vehicle dimensions and capacity
- Route suitability and travel time
- Filling rate
- Queue length
- Time to re-enter the operation

The practical unit is the complete refill cycle, rather than distance to water.

In Portuguese operational language, the familiar terms are closer to *abastecimento/reabastecimento de água*, *vaivém de veículos tanque* and *transfega entre bombas*. "Water turnaround" is a useful product shorthand, but should not be assumed to be the term crews use.

## What happens today

Public doctrine describes the command structure and the available water-supply methods, but not a single nationwide step-by-step refill script. The exact practice will vary with incident size, terrain, the participating fire brigade and the instructions of the incident commander. The following is therefore a documented operating model, not a claim that every crew behaves identically.

### 1. Before an incident

- Local authorities are expected to validate the water points in the inventory, confirm whether they are operational for rotary-wing aircraft and/or terrestrial vehicles, and publish the information through SGIF and the water-point portal.
- Municipal plans inventory water points and supporting roads. This is planning data rather than a live view of access, fill rate, queueing or water availability.
- Fire brigades maintain the readiness of their vehicles and crews. Current national vehicle specifications illustrate the different roles: a VFCI frontline rural engine has a 3,000-4,000 litre tank, while a VTTF water-support vehicle has at least 8,000 litres.

### 2. Arrival and initial attack

Under [DECIR 2026](https://prociv.gov.pt/media/gufh5pvz/don-decir-n%C2%BA-2_2026-vers%C3%A3o-final.pdf), the first team reports the exact fire location through the SIRESP radio system and its leader initially becomes the Comandante das Operações de Socorro (COS). When a fire-brigade team arrives, the most senior member of that team assumes command.

If reinforcements are requested, the COS establishes a Ponto de Trânsito (PT) to control entry and exit. Every arriving team contacts the PT or COS and receives a mission; DECIR 2026 says this should happen preferably within 15 minutes of arrival. A force may only leave the theatre of operations after completing its mission and with COS authorization.

For water, this means a driver should not independently optimize a route and disappear from the operation. In a small incident, the COS or team leader can make the refill decision directly. As the incident grows, the assignment belongs in the command-and-logistics chain.

### 3. How water is moved

The Portuguese firefighter training material describes three basic patterns:

1. **Direct supply:** connect a hydrant or other water take-off to the firefighting vehicle, normally with a supply hose. This is the simplest option when the source is close and provides adequate flow and pressure.
2. **Tanker shuttle:** vehicles cycle between a water source and the firefighting vehicles. The ENB hydraulics manual uses this pattern as the normal option once the source is more than roughly 200 metres away. It requires enough tankers and tight coordination; demountable tanks may buffer supply when the journey is long relative to demand.
3. **Pump relay / transfer:** pumps or portable pumps are connected in series when water must be moved over distance, elevation or terrain that vehicles cannot practically bridge.

The ENB's more recent [urban and industrial firefighting manual](https://www.enb.pt/admin/docs/repositorio/Combate%20a%20Inc%C3%AAndios%20Urbanos.pdf) still identifies direct hydrant supply, tanker shuttle and pump-to-pump transfer as the available methods, and makes the COS responsible for selecting the method. The mechanics are not specific to urban incidents, although rural route and access constraints are usually more severe.

### 4. When the incident scales

The Posto de Comando Operacional (PCO) expands modularly. The Célula de Logística (CELOG) sustains the operation and prepares a logistics plan for resources, reserves, maintenance, transport and re-supply, for COS approval. A Zona de Concentração e Reserva (ZCR) can include a designated *Área de Reabastecimento* for water, fuel, equipment and consumables.

Water reinforcement can be requested through the command chain. DECIR 2026 defines a Grupo de Reforço para Reabastecimento de Água (GRRA) as five high-capacity tankers, each over 15,000 litres, plus a command vehicle, twelve firefighters and a local guide. This is a scalable reinforcement package, not the everyday starting point for every incident.

### 5. What crews do while moving

The operational loop is best understood as:

`assigned source -> acknowledge -> leave under command control -> travel -> queue -> connect/fill -> report obstruction or failure -> return -> transfer water -> become available/reassigned`

Communication is primarily through the operational hierarchy and radio networks, including SIRESP, REPC and ROB, with telephones as additional channels. The formal record sits with the command structure: the operations cell maintains the situation picture and timeline, while logistics maintains the resource and re-supply picture. Public documents do not describe a shared live queue, automatic tank telemetry or turn-by-turn route assignment for refill vehicles.

That gap matters. On the move, the most valuable crew reports are small and time-sensitive:

- point usable / unusable, with a reason;
- arrival and estimated queue;
- filling started / completed and litres taken;
- access restriction, locked gate or unsafe manoeuvre;
- departure and estimated return;
- route obstruction or changed destination.

These reports currently fit radio and local practice, but the public doctrine does not expose a structured data loop that turns them into updated cycle estimates for all vehicles.

## Guimarães-specific reading

The current public material presents a useful but fragmented picture.

- The [Guimarães Municipal Emergency Plan, Part II](https://www.cm-guimaraes.pt/cmguimaraes/uploads/document/file/20829/02_pme_guimaraes_parte_ii_v06.pdf) is version 06 from November 2022 and was approved in 2023. It records **44 water points: 14 mixed and 30 terrestrial**. The published type breakdown—20 irrigation tanks, 9 ponds, 4 swimming pools, 4 rivers, 2 wells, 2 weir reservoirs and 1 lake—adds up to only **42**. Two points are therefore unaccounted for in the typology and should not be guessed or silently assigned. Its map shows a distributed network across the municipality.
- The municipality's [PMDFCI page](https://www.cm-guimaraes.pt/pages/1130), updated in 2026, still presents the 2019-2028 action plan as the plan in force. That plan calls for maintenance and improvement around municipal points, including access for terrestrial and aerial resources. Its named mixed points include Penha/Costa, Senhora da Saúde, Falperra/Longos and Souto Santa Maria, and its planning table gives class and maximum volume for the broader inventory.
- The municipal emergency plan assigns water-network operational reporting, maintenance and restoration to VIMÁGUA. Its communications structure includes both the Bombeiros Voluntários de Guimarães and the Bombeiros Voluntários das Caldas das Taipas, coordinated at municipal level by the Serviço Municipal de Proteção Civil.
- The municipal plan gives CELOG responsibility for re-supply planning and identifies an *Área de Reabastecimento* within a ZCR, but it does not publish a Guimarães-specific live refill circuit, source flow rates, connector details, queue state or heavy-vehicle access rules.
- Guimarães hosted the presentation of the [Ave sub-regional DECIR 2026 plan](https://www.cm-guimaraes.pt/areas-de-intervencao/noticia/plano-de-operacoes-sub-regional-do-dispositivo-especial-de-combate-a-incendios-rurais-reforca-capacidade-de-meios-e-prevencao-para-2026). The public summary emphasizes permanent operational coordination and municipal logistical and technical support, but does not disclose the operational water-assignment detail.

### What the Guimarães documents do and do not answer

| Question | Publicly documented | Still missing or operationally volatile |
| --- | --- | --- |
| Where can water potentially be found? | Municipal map, point type and terrestrial/mixed class | Precise connector, drafting setup and safe staging position |
| Is it intended for terrestrial vehicles? | Yes, at class level | Which vehicle dimensions and weights can use it today |
| How much water exists? | A maximum volume appears in the older PMDFCI table | Current usable volume and replenishment rate |
| Who coordinates supply? | COS, PCO/CELOG and municipal/sub-regional command chain | Who performs the role on a small Guimarães incident in practice |
| How is status communicated? | Radio/telephone hierarchy and command records | A compact standard for queue, fill start/end, failure and return ETA |
| Which source is quickest? | Not calculated | Travel, access, queue, connection, fill and return times |

The mismatch between a planning inventory and the information required for a live cycle is the strongest justification for the product. It also warns against presenting the municipal dataset as real-time truth.

### Recency boundary

The municipality's PMDFCI page was updated in April 2026, but the action plan it publishes covers 2019–2028. The municipal emergency-plan page was updated in October 2026, while its current plan is Version 06 of November 2022, approved in 2023. I also checked the [revised PROCIV technical guidance announced on 13 October 2026](https://prociv.gov.pt/pt/noticias/dia-internacional-para-a-reducao-do-risco-de-catastrofes-assinalado-com-novo-impulso-ao-planeamento-de-emergencia/): it reinforces that emergency planning must remain dynamic and continuously valid, but it does not publish a more detailed live water-turnaround procedure. For the operational chain described here, **DECIR 2026 remains the most current public source**.

## Primary users

- COS or team leader during a small incident
- CELOG / logistics officer during a scaled incident
- Sector or group commanders coordinating vehicles
- Drivers or vehicle team leaders
- Municipal civil-protection staff responsible for water infrastructure

The driver is primarily the reporter and recipient of an assignment, not the sole optimizer. The recommendation should enter through the installed chain of command.

## Proposed platform

The platform combines a known water-point inventory with temporary operational status. For each vehicle, it compares possible refill cycles and explains the recommendation in plain terms.

It could show:

- Available and unavailable water points
- Vehicle compatibility and access limitations
- Estimated travel, queue, filling, and return time
- Expected litres returned per hour
- Current vehicle assignments
- The operational consequence of a point becoming unavailable
- Missing or stale inputs that make the estimate uncertain

The system should support a human decision rather than issue an unexplained optimal assignment. Users must be able to override a suggestion and record information the model does not know.

### Minimum operational loop

For a first version, avoid replacing radio, SIRESP or SADO. Support the conversation already taking place:

1. Command selects a vehicle and assigns a source and approved route.
2. The vehicle acknowledges the assignment.
3. The crew sends one-tap state changes: *en route*, *queued*, *filling*, *returning*, *delivering*, *available*.
4. A crew can report *unusable*, *restricted* or *slow*, with a short reason and optional voice note/photo.
5. Observed travel, wait and fill times update the estimate for the next vehicle.
6. Command can override, close or reopen a point and broadcast the change.

Every datum should carry a source and timestamp: municipal inventory, planning assumption, command decision or crew observation.

### Decision model

For vehicle `v` and source `s`:

`cycle_time(v,s) = outbound + queue + connect + fill + return + transfer`

`useful_rate(v,s) = transferable_litres / cycle_time`

The recommendation is constrained before it is ranked:

- source currently approved and reported usable;
- compatible with the vehicle and the supply method;
- approved route and safe access/turnaround;
- no conflict with aerial use or other command restriction;
- enough reserve remains to move and protect the vehicle safely.

The highest litres-per-hour option is not automatically selected. Command may value predictability, sector continuity, keeping a vehicle at the fire, road safety or source resilience more highly.

## Hackathon scope

Use a synthetic incident in Guimarães, grounded in the public water-point inventory but with all live conditions clearly labelled as fictional:

- Three vehicles with different capacities
- Four water points with different access and filling characteristics
- A small road network
- A simple queue model
- Manual status updates

Avoid modelling national resource dispatch or live vehicle tracking. The interesting problem is a small, understandable allocation decision.

A credible local scenario could use one mixed point around Penha and three terrestrial points from different parts of the municipality. Do not publish invented fill rates, access constraints or live availability as facts about the real points.

## Demonstration story

At the start, the nearest water point appears attractive but has a slow fill rate and a queue. The platform recommends a slightly farther point because it returns more water per hour. One point then becomes unavailable. The recommendations, expected cycle times, and total estimated delivery change immediately, with the reasons visible.

Show two views of the same event:

- **Command:** all vehicle cycles, point status, bottlenecks, confidence and suggested reassignment.
- **Crew:** the current approved destination, route caution, simple status actions and a radio fallback phrase.

## Meaningful impact measures

- Estimated litres delivered to the incident per hour
- Vehicle time spent travelling, waiting, and filling
- Number of vehicles assigned to an incompatible or unavailable point
- Time taken by a logistics officer to construct a refill plan
- Difference between estimated and observed cycle times during an exercise

## Public data that can support it

- [ICNF geographic catalogue](https://geocatalogo.icnf.pt/catalogo.html)
- [ICNF water-point map service](https://sigservices.icnf.pt/server/rest/services/BDG/Pontos_agua/MapServer/0)
- [DECIR 2026](https://prociv.gov.pt/pt/documentacao/diretiva-operacional-nacional-n%C2%BA-2-decir-2026/)
- [Guimarães Municipal Emergency Plan](https://www.cm-guimaraes.pt/areas-de-intervencao/protecao-e-seguranca/protecao-civil/plano-municipal-de-emergencia-de-protecao-civil-de-guimaraes)
- [Guimarães PMDFCI](https://www.cm-guimaraes.pt/pages/1130)
- [2024 specifications for Portuguese fire-service vehicles](https://diariodarepublica.pt/dr/detalhe/despacho/1240-2024-839900762)
- [ENB hydraulics manual mirror](https://www.bombeiros.pt/wp-content/uploads/2013/07/03.Hidraulica.pdf), for the mechanics of direct supply, tanker shuttle and pump relay
- OpenStreetMap road data for an initial routing graph
- Terrain from the [Copernicus Data Space STAC API](https://documentation.dataspace.copernicus.eu/APIs/STAC.html) or DGT, if slope or vehicle access becomes relevant

The public inventory provides candidate infrastructure. Current usability, fill rate, queues, and operational access will generally require local or manually supplied information.

## Main adoption risks

Bad operational inputs can produce precise-looking but misleading results. The interface must distinguish verified facts, planning assumptions, estimates, and live reports. Routing must also respect operator-approved roads; a generic navigation route may be unsafe or physically impossible for a heavy vehicle.

Additional risks exposed by the current process:

- A parallel app can fragment command information if it is not operated through the COS/CELOG chain.
- Asking drivers for too much interaction while moving creates a safety problem; the driver view must be minimal and usable by another crew member or by voice/radio proxy.
- A point marked mixed or terrestrial is not proof of current access or flow.
- Optimizing a single vehicle can make the whole incident worse by creating a queue or draining a fragile source.
- Exact positions and live force movements may be operationally sensitive; access control and retention need to be designed with the authorities.

## Field validation in Guimarães

The public documents are enough to justify the problem, but not enough to claim the informal workflow. Validate it with the Serviço Municipal de Proteção Civil, Bombeiros Voluntários de Guimarães, Bombeiros Voluntários das Caldas das Taipas and VIMÁGUA.

### Interview prompts

1. In a one-vehicle or two-vehicle rural fire, who tells a crew where to refill?
2. At what incident size is water supply handed to a dedicated logistics role?
3. What exact radio words are used for low water, departure, queue, failure and return?
4. Is the municipal water-point map available in the vehicle, at dispatch, in SADO, or only through local knowledge?
5. Who knows whether a hydrant can sustain the requested flow without affecting public supply?
6. Where do crews currently record a locked gate, poor turn radius, empty pond or failed pump?
7. Do tankers normally feed an engine directly, use a temporary tank, or rotate the engine away from the fire?
8. How are aerial and terrestrial demands separated at a mixed point?
9. What makes a refill route unsafe even when a normal navigation app says it is passable?
10. Which one-tap report would remove the most radio traffic without weakening command control?

### Exercise

Run three vehicles through two real but non-emergency approved points during a drill. Record timestamps for assignment, departure, arrival, connection, fill start/end, return and transfer. Compare the observed cycle with the model, then introduce one blocked access and one queue. Success is not merely choosing the fastest source; it is preserving command awareness and avoiding an interrupted water supply.

## Questions for deeper exploration

1. In Guimarães, how does the practical role split between COS, sector command, CELOG, the two fire brigades and the municipal service?
2. Is the key objective water volume, cycle predictability, frontline vehicle availability, or continuity at a particular sector?
3. Which status changes can crews report with one tap or a short radio message?
4. How quickly do queues form, and who can observe them reliably?
5. Can VIMÁGUA safely expose hydrant availability or expected flow without implying a guarantee?
6. Which parts of SGIF, the water-point portal or SADO can be integrated, and which must remain separate?

## Prompt for a follow-up thread

Explore Water Turnaround as a hackathon product. Define the decision model, minimum required data, assumptions and uncertainty, operator workflow, explainable recommendations, a five-minute scenario-based demo, and a validation exercise. Keep it bounded to one incident and a handful of vehicles and water points. Do not assume access to live fleet systems.
