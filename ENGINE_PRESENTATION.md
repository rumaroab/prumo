# Forest Fire Model Engine Presentation

## Slide 1 — Platform purpose

### Comparing fire-spread engines for road-exposure planning

The platform runs several wildfire models through one shared scenario and converts their results into the same 30 m arrival-time grid. This allows users to compare when fire may reach roads without changing the existing map, timeline, or road-exposure workflow.

**Key message:** this release is a comparative planning demonstration, not an operational fire forecast or road-closure system.

---

## Slide 2 — Engines implemented

The platform currently supports five engines:

1. **Python MTT** — a fast experimental Minimum Travel Time implementation.
2. **Cell2Fire C2F-W** — a cell-based fire-spread simulator.
3. **FARSITE** — a perimeter-growth model used here in surface-fire mode.
4. **QUIC-Fire** — a detailed fire and local-flow simulator requiring a licensed executable.
5. **WRF-SFIRE** — a coupled atmosphere and fire model intended primarily for remote high-performance computing.

Parameter ensembles and engine comparisons are run modes built on these engines; they are not separate simulation engines.

---

## Slide 3 — Main engine comparison

Speed ratings compare the engines for the same small demonstration area. Actual runtime depends on domain size, duration, resolution, hardware, and output frequency.

| Engine | Relative speed | Potential physical realism | Current demonstration confidence | Weather support | Main strength | Main limitation |
|---|---:|---:|---:|---|---|---|
| **Python MTT** | **Fastest — 5/5** | 2/5 | 2/5 | Constant | Immediate interactive results and useful bounding scenarios | Experimental implementation with no claim of FlamMap equivalence |
| **Cell2Fire C2F-W** | **Fast — 4/5** | 3/5 | 3/5 | Constant | Efficient cell-based spread and repeatable seeded simulations | Uses a demonstration Portuguese land-cover-to-fuel mapping |
| **FARSITE, surface mode** | **Moderate — 3/5** | 3/5 | 3/5 | Constant or uploaded series | Established perimeter growth with terrain, fuels, moisture, and changing weather | Current adapter disables crown fire and spotting; output is every five minutes |
| **QUIC-Fire** | **Slow — 2/5** | 4/5 | 2/5 | Constant or uploaded series | Resolves three-dimensional fuels and local wind/fire interactions | Licensed simulator required; current vertical fuels are synthetic approximations |
| **WRF-SFIRE** | **Slowest — 1/5** | **5/5 when coupled and calibrated** | 2/5 | Constant for coupled mode; series for standalone mode | Two-way interaction between the fire and atmosphere | Very high compute and setup cost; current fuel crosswalk and idealized atmosphere are illustrative |

**Fastest option:** Python MTT.

**Fastest established external simulator:** Cell2Fire.

**Highest potential realism:** coupled WRF-SFIRE, when it has calibrated fuels, atmospheric initialization, suitable resolution, and adequate computing resources.

**Best balance for this demonstration:** FARSITE or Cell2Fire, depending on whether changing weather/perimeter output or faster repeated runs matter more.

---

## Slide 4 — What “more realistic” means

Realism is not determined by model complexity alone. It depends on four elements:

- **Fire processes represented:** surface spread, spotting, crown fire, fuel consumption, and fire-atmosphere feedback.
- **Input quality:** locally calibrated fuels, canopy information, terrain, moisture, and observed weather.
- **Resolution:** spatial cell size and the frequency of model outputs.
- **Validation:** comparison against observed fires in the same vegetation and climate.

A complex engine with synthetic fuels can be less trustworthy than a simpler engine with well-calibrated local inputs. The realism scores in this presentation describe each engine's potential capability, while the demonstration-confidence score describes the present implementation.

---

## Slide 5 — Python MTT

### Best for rapid exploration

- Uses Pyretechnics surface-fire spread rates and a Minimum Travel Time search over the 30 m landscape.
- Produces minute-resolution arrival times directly on the platform grid.
- Runs locally with low compute requirements and no external executable.
- Works well for interface testing, fast scenario exploration, and uncertainty ensembles.
- Uses constant weather and simplified spread links.

**Use it when:** a quick answer or many repeated runs are more important than detailed fire physics.

---

## Slide 6 — Cell2Fire C2F-W

### Best for fast cell-based simulation

- Uses homogeneous landscape cells with fuel, topography, moisture, and weather attributes.
- Supports repeatable simulations through deterministic seeds.
- Produces detailed message output that the platform converts into cell arrival times.
- Is suitable for larger batches and ensemble experiments at a moderate compute cost.
- Currently uses constant weather and the demonstration Scott–Burgan fuel conversion.

**Use it when:** fast scenario or ensemble simulation is needed with a dedicated wildfire simulator.

---

## Slide 7 — FARSITE

### Best for interpretable fire perimeters with changing weather

- Uses elevation, slope, aspect, surface fuels, fuel moisture, ignition geometry, and weather records.
- Accepts both constant weather and uploaded time-varying weather series.
- Exports native fire perimeters every five minutes.
- The platform rasterizes the first perimeter reaching each cell into the common arrival-time grid.
- Crown-fire and spotting behavior remain disabled because calibrated canopy inputs are unavailable.

**Use it when:** perimeter evolution and changing weather are important, and five-minute temporal precision is acceptable.

---

## Slide 8 — QUIC-Fire

### Best for detailed local fire and flow studies

- Represents a three-dimensional fuel field and local wind/fire behavior.
- Supports constant weather and uploaded surface-weather series.
- The platform detects the first significant fuel consumption anywhere in each vertical fuel column.
- Requires a separately licensed QUIC-Fire executable; the repository provides only the open wrapper and input tooling.
- The current WorldCover conversion creates illustrative fuel load, depth, and vertical distribution rather than field-calibrated vegetation.

**Use it when:** local three-dimensional effects matter and licensed software, suitable data, and substantial compute are available.

---

## Slide 9 — WRF-SFIRE

### Best for fire-atmosphere research

Two profiles are available:

- **Coupled idealized:** uses constant scenario controls to initialize an idealized atmosphere and enables two-way fire-atmosphere coupling.
- **Standalone series:** uses uploaded time-varying winds as one-way forcing and does not feed fire effects back into those supplied winds.

The platform derives first arrival from the first output time where the WRF-SFIRE level-set variable `LFN` reaches zero or below. It also preserves optional fire-area, wind, and heat-flux artifacts.

**Use it when:** atmospheric interaction is central to the question and a validated MPI/NetCDF runtime or Slurm cluster is available.

---

## Slide 10 — Choosing an engine

| Goal | Recommended starting option | Reason |
|---|---|---|
| Immediate interactive result | **Python MTT** | Lowest runtime and no external dependency |
| Many deterministic ensemble members | **Python MTT or Cell2Fire** | Good throughput for repeated runs |
| Time-varying weather and clear perimeter history | **FARSITE** | Native five-minute perimeter series |
| Local three-dimensional fuel and wind interaction | **QUIC-Fire** | Detailed fuel-column and flow representation |
| Fire-atmosphere feedback | **WRF-SFIRE coupled** | Represents two-way atmospheric coupling |
| Compare structural model uncertainty | **Engine comparison mode** | Keeps each engine separate and reports agreement without treating engines as probability samples |

---

## Slide 11 — Ensembles and comparisons

### Parameter ensembles

- **Quick:** three deterministic members using nominal and bounding wind conditions.
- **Standard:** nine members combining wind-speed factors of 0.8, 1.0, and 1.2 with direction offsets of −15°, 0°, and +15°.
- Results include member grids, P10/P50/P90 arrival, fire-reach probability bands, and road-exposure probability.

### Engine comparisons

- Runs two or more available engines from the same shared scenario.
- Shows one map at a time for clarity.
- Compares burned area, exposed-road count, runtime, temporal resolution, and pairwise area agreement at the selected minute.
- Does not combine different engines into a probability estimate.

---

## Slide 12 — Reproducibility and transparency

Every completed result records:

- Engine and profile version.
- Container image digest or executable checksum.
- Input checksum and generated input files.
- Weather source and fuel-conversion assumptions.
- Runner, command, runtime, and output interval.
- Native spatial and temporal resolution.
- Model limitations and warnings.

All native outputs and logs are preserved, and missing geographic coverage remains explicitly marked as unknown.

---

## Slide 13 — Final recommendation

Use the engines as a progression rather than selecting one universal winner:

1. Start with **Python MTT** for rapid exploration.
2. Use **Cell2Fire** for fast repeated simulation and ensembles.
3. Use **FARSITE** when perimeter development and changing weather are important.
4. Use **QUIC-Fire** for detailed local three-dimensional studies.
5. Use **WRF-SFIRE** for research questions requiring fire-atmosphere coupling.

The next step for improving confidence is not another engine. It is collecting and validating local fuel, canopy, moisture, and weather inputs against observed Portuguese fire behavior.

### Closing statement

The platform makes model differences visible while preserving one common road-exposure workflow. Faster engines support exploration; more detailed engines support deeper analysis; calibrated local data determines whether either can support real decisions.

