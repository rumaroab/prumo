# Hackathon Idea Comparison

This comparison uses the hackathon's official weighted criteria:

- Innovation and originality: **25%**
- Technical feasibility: **25%**
- Impact and relevance: **30%**
- Presentation and continuation potential: **20%**

Scores are out of 10. The overall score is the weighted result of those four criteria. Operational practicality and similarity risk are shown separately so that a visually impressive but unrealistic concept does not hide its main weakness. Similarity risk means the likelihood that another team presents a broadly comparable idea; lower is better.

| Rank | Idea | Innovation 25% | Feasibility 25% | Impact 30% | Presentation and continuity 20% | Operational practicality | Similarity risk | Hackathon outlook | Overall |
| ---: | --- | ---: | ---: | ---: | ---: | --- | --- | --- | ---: |
| 1 | [Fire-Aware Road Access](06-fire-aware-road-access.md) | 9.0 | 7.0 | 8.5 | 9.5 | Medium — credible for scenario planning, not yet safe for live routing | Medium–high — fire maps and evacuation routing may recur, but journey-wide access deadlines are distinctive | **High ceiling, conditional:** potentially the strongest demo if the simulator-to-road pipeline works reliably | **8.5** |
| 2 | [After the Fire, Before the Rain](05-after-the-fire-before-the-rain.md) | 8.5 | 8.0 | 8.0 | 8.5 | High — supports an existing inspection and prioritisation task without making live tactical decisions | Low | **High:** distinctive, locally relevant and defensible with public data | **8.2** |
| 3 | [Water Turnaround](02-water-turnaround.md) | 8.0 | 7.5 | 8.5 | 8.5 | High if it supports command decisions through manual status updates; lower if it assumes live integrations | Low–medium | **High:** concrete operational metric and a strong before/after demonstration | **8.1** |
| 4 | [Everyone Accounted For](03-everyone-accounted-for.md) | 6.5 | 8.0 | 8.5 | 8.0 | Medium — useful, but identity reconciliation, privacy and multi-agency ownership are difficult | Medium | **Medium–high:** emotionally strong and easy to understand, but less original | **7.8** |
| 5 | [Before You Arrive](01-before-you-arrive.md) | 7.0 | 8.0 | 7.5 | 8.0 | Medium — technically achievable, but operational value depends on continuous verification and adoption | Medium | **Medium:** credible demo, although judges may challenge who maintains the information | **7.6** |
| 6 | [Request to Confirmation](04-request-to-confirmation.md) | 6.0 | 9.0 | 7.5 | 7.5 | Very high — it closely matches an existing coordination workflow and can work without complex integrations | Low–medium | **Medium:** most likely to work completely, but risks appearing like a generic task board | **7.5** |

## How to interpret the ranking

**Fire-Aware Road Access has the highest winning ceiling, not the lowest delivery risk.** Its fire timeline, route failure, detour and eventual loss of access form the clearest visual story of the six ideas. Its score assumes a small prepared area, reproducible precomputed scenarios and honest positioning as a planning demonstrator. If compatible fire-simulation output cannot be produced early, its feasibility score should fall sharply.

**After the Fire, Before the Rain is the safest distinctive alternative.** It avoids live-response liability, can use public datasets and gives municipal teams a concrete inspection plan.

**Water Turnaround offers the best balance of operational relevance and demo clarity.** It becomes especially strong if the prototype uses a simple manual operational loop and shows litres delivered per hour rather than pretending to integrate with live emergency systems.

**Request to Confirmation is the strongest practicality fallback.** It is unlikely to fail technically and may give municipalities a useful direction, even if its innovation score makes it less likely to win.

## Recommendation

Prototype Fire-Aware Road Access first only far enough to prove the risky technical chain: run one fire scenario, extract timed spatial output, convert it into road deadlines and reject a route that becomes unavailable during travel. Do not build its full interface before this works.

Keep After the Fire, Before the Rain or Water Turnaround as the pragmatic fallback. Both can still produce a complete, useful hackathon demonstration if the simulation integration proves too fragile.
