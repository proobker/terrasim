# terrasim --- Complete Project Context & Master Specification

> **Building Resilient Areas for Climate & Emergencies**
>
> **Tagline:** *Simulate today's risks. Plan tomorrow's resilient
> cities.*
>
> **Hackathon Track:** Climate Change, Resilience & Sustainability

------------------------------------------------------------------------

## 0. Purpose of This Document

This document is the complete working context for the terrasim project.

It is intended to be given to another AI/model, teammate, designer,
developer, or judge-preparation assistant so that they understand the
project without needing the earlier conversation.

It consolidates:

-   the original concept
-   how the idea evolved
-   the final project definition
-   the two operating modes
-   the disaster simulation concepts
-   the new-city planning concept
-   the existing-city assessment concept
-   satellite/Earth-observation integration
-   AI possibilities
-   emergency routing ideas
-   building/photo concepts
-   technical architecture
-   data sources
-   algorithms and modeling assumptions
-   MVP vs stretch goals
-   hackathon constraints
-   demo strategy
-   presentation strategy
-   visual/design identity
-   scientific limitations
-   judge objections and defenses
-   uniqueness/differentiation
-   future roadmap
-   implementation priorities
-   terminology and claims to avoid

The goal is not to claim that every feature below must be implemented in
the first hackathon version. Features are explicitly separated into
**MVP**, **stretch**, and **future** where appropriate.

------------------------------------------------------------------------

# 1. Project Identity

## Name

**terrasim**

Full name:

**Building Resilient Areas for Climate & Emergencies**

## Tagline

**Simulate today's risks. Plan tomorrow's resilient cities.**

Alternative short message:

**Test a city before a disaster does.**

## Track

**Climate Change, Resilience & Sustainability**

The project is primarily about disaster resilience, climate-related
risk, geospatial planning, and safer urban development.

## Core One-Sentence Description

terrasim is a geospatial disaster-risk simulation and urban-planning
platform that lets users stress-test existing cities against
hypothetical disasters and design safer future developments by
simulating scenarios, identifying weaknesses, and improving the proposed
layout.

## Core Concept

terrasim is built around a simple loop:

**PLAN → SIMULATE → IDENTIFY RISK → IMPROVE → SIMULATE AGAIN**

The central idea is not merely to create another disaster map.

The important workflow is:

> **Use simulation as a feedback loop for urban planning.**

------------------------------------------------------------------------

# 2. Why terrasim Exists

Cities are often built first and analyzed for vulnerabilities afterward.

A traditional sequence can look like:

``` text
BUILD
  ↓
DISASTER
  ↓
DISCOVER VULNERABILITY
  ↓
RESPOND
```

terrasim proposes a complementary approach:

``` text
ANALYZE
  ↓
SIMULATE
  ↓
PLAN
  ↓
IMPROVE
```

This produces two important use cases:

### Existing city

> "What could happen to this city under a hypothetical disaster
> scenario?"

### New/planned city

> "Where should we place important infrastructure before we build the
> city?"

The second use case is particularly important to terrasim's identity
because it turns the system from a passive risk visualization tool into
an interactive planning and validation workflow.

------------------------------------------------------------------------

# 3. The Two terrasim Modes

## Mode 1 --- Existing City

### Name

**Simulate & Assess**

### Purpose

Analyze an already built or developed area.

The user selects a real location and creates a hypothetical disaster
scenario.

Possible scenarios:

-   Flood
-   Earthquake
-   Future additional hazards

The system then visualizes estimated exposure and affected
infrastructure.

### Typical workflow

``` text
Select location
      ↓
Load terrain + map data
      ↓
Select disaster
      ↓
Configure scenario
      ↓
Run simulation
      ↓
Generate estimated impact/exposure layer
      ↓
Overlay buildings / roads / critical infrastructure
      ↓
Show exposed assets
```

### Example

User selects Kathmandu or another city.

They select:

-   Earthquake
-   Magnitude 7.2
-   Chosen epicenter
-   Chosen depth

terrasim produces a scenario-based shaking/exposure visualization.

It then overlays:

-   buildings
-   roads
-   hospitals
-   schools
-   other critical facilities

The system can report things such as:

-   number of mapped buildings in a scenario zone
-   roads crossing a high-exposure area
-   hospitals within an estimated high-exposure zone
-   schools within an estimated high-exposure zone

The system must NOT claim that a particular building will definitely
collapse.

Correct framing:

> "This facility falls within the estimated high-exposure zone under
> this scenario."

Incorrect framing:

> "This hospital will be destroyed."

------------------------------------------------------------------------

# 4. Mode 2 --- New / Planned City

## Name

**Plan & Validate**

This is the most distinctive part of the terrasim concept.

Instead of analyzing an existing city, the user selects an empty,
undeveloped, or developing area and asks:

> "How should we build here?"

The system analyzes available geographic information and creates a
conceptual suitability/risk layer.

### Possible outputs

-   relatively suitable zones
-   conditional zones
-   higher-risk zones
-   flood exposure
-   earthquake scenario exposure
-   terrain constraints
-   proximity/access considerations
-   existing infrastructure context

A simple visualization can use:

``` text
GREEN  = relatively suitable
YELLOW = conditional / investigate
RED    = relatively higher risk
```

These are **relative planning indicators**, not guarantees of safety.

------------------------------------------------------------------------

# 5. New-City Planning Workflow

The proposed workflow is:

``` text
Select undeveloped area
        ↓
Load terrain/elevation data
        ↓
Load hazard/environmental context
        ↓
Generate suitability/risk layer
        ↓
User proposes city layout
        ↓
Place hospital
Place school
Place housing
Place emergency facilities
Place roads
        ↓
Run disaster simulation
        ↓
Identify exposed facilities
        ↓
Modify layout
        ↓
Run simulation again
        ↓
Compare the plans
```

The key concept is:

> **The user can iterate on the city design based on simulated risk.**

------------------------------------------------------------------------

# 6. Signature terrasim Differentiator

## PLAN → SIMULATE → IMPROVE

Example:

### First plan

A hospital is placed in a relatively high-risk zone.

### Simulation

A hypothetical flood or earthquake is run.

### Result

The hospital falls within an estimated high-exposure area.

### Intervention

The user moves the hospital to another candidate location.

### Second simulation

The new location has lower estimated exposure under the selected
scenario.

### Result

The user has improved the proposed layout using simulation.

This is the conceptual "money moment" of terrasim.

The project should not be described simply as:

> "A disaster map."

It should be described as:

> **"An interactive simulation-to-planning feedback loop."**

------------------------------------------------------------------------

# 7. Disaster Simulation

terrasim is a hackathon prototype.

The simulation should therefore be explicitly framed as:

-   hypothetical
-   scenario-based
-   estimated
-   simplified
-   decision-support oriented

It is not intended to replace professional engineering or validated
government hazard models.

------------------------------------------------------------------------

# 8. Flood Simulation

## Goal

Create a terrain-based hypothetical flood extent.

## Basic concept

Use a digital elevation model (DEM).

A simplified approach:

1.  Obtain an elevation grid.
2.  User selects a water source or flood origin.
3.  User specifies a hypothetical water-level increase.
4.  Determine terrain cells that could be connected to the source and
    lie below the relevant water surface.
5.  Render the connected flooded region as an overlay.
6.  Intersect the flood extent with roads/buildings/facilities.

## Simplified algorithm

Conceptually:

``` text
DEM
 ↓
Select flood source
 ↓
Determine source elevation
 ↓
User selects hypothetical water level
 ↓
Generate candidate cells below water surface
 ↓
Connectivity / flood-fill from source
 ↓
Flood extent
 ↓
Overlay infrastructure
```

## Important limitation

This is NOT a full hydrodynamic flood model.

It does not automatically account for every factor such as:

-   rainfall dynamics
-   river discharge
-   drainage networks
-   hydraulic structures
-   flow velocity
-   infiltration
-   sediment
-   detailed channel hydraulics
-   time-dependent water movement

The flood engine is **flow-routed and volume-conserving**: a D8
steepest-descent direction raster routes water downhill, and a rise is
converted into a conserved volume released as a transient triangular
hydrograph over simulated hours. The wave travels along the selected
river's flow path (upstream floods first), spills onto connected low
ground until its volume is spent, and mapped waterlines whose basins drain
into that river contribute volume as tributaries, lagged by their distance
to the junction. Extent and depth are the peak state of the whole run;
timings and peak discharge are hypothetical, derived from assumed flow
speeds, never a forecast. Different rivers give different extents.

Therefore, call it:

> **Terrain-based hypothetical flood extent**

Do not call it:

> "Exact flood prediction."

------------------------------------------------------------------------

# 9. Earthquake Simulation

## Goal

Generate a simplified scenario-based shaking/exposure layer.

## User inputs

Potential inputs:

-   epicenter
-   magnitude
-   depth

## Basic model

A simplified attenuation-style model can estimate decreasing intensity
with distance from the epicenter.

Conceptually:

``` text
Epicenter
   ↓
Distance calculation
   ↓
Magnitude/depth adjustment
   ↓
Estimated intensity
   ↓
Intensity zones
```

Example output:

``` text
HIGH
MEDIUM-HIGH
MEDIUM
LOW
```

The exact scientific model should be chosen carefully and described
honestly.

## Infrastructure exposure

The resulting zones can be intersected with:

-   buildings
-   roads
-   hospitals
-   schools
-   emergency facilities

## Important limitation

Real earthquake damage depends on much more than magnitude and distance.

Factors include:

-   soil conditions
-   geology
-   structural design
-   building materials
-   construction quality
-   building age
-   foundation
-   number of floors
-   local amplification
-   fault characteristics

Therefore terrasim should NOT claim:

> "This building will collapse."

Instead:

> "This building lies within the estimated high-intensity scenario
> zone."

------------------------------------------------------------------------

# 10. Building Data

The preferred initial approach is to use existing geospatial building
footprints where available.

Possible data source:

**OpenStreetMap**

Possible building information:

-   building footprint
-   mapped building type where available
-   location
-   surrounding roads
-   nearby facilities

Not every building will have complete attributes.

This is acceptable for an MVP.

------------------------------------------------------------------------

# 11. Optional Building Photo → Box Concept

A previous terrasim concept explored allowing a user to upload a photograph
of a specific building.

The idea was deliberately simplified.

## Pipeline

``` text
User uploads building photo
        ↓
AI vision model
        ↓
Estimate approximate:
- footprint dimensions
- height
- floor count
        ↓
User confirms location
        ↓
Create generic building bounding box
        ↓
Assign default/average resistance profile
        ↓
Run scenario
        ↓
Return estimated exposure/severity
```

## Why this was simplified

The original idea of trying to infer:

-   concrete vs brick
-   structural system
-   foundation
-   actual strength
-   earthquake resistance

from a single photograph is unreliable and inappropriate for a two-day
hackathon.

Therefore the deliberate design choice is:

> **Use the photo only for rough geometry, not for pretending to perform
> structural engineering.**

## Default resistance concept

A single average/default assumption could be used in a demo.

For example:

``` text
default_residential_profile
```

The user could optionally override assumptions if they know more about
the building.

## Important limitation

A photograph cannot reliably establish the actual structural safety of a
building.

The feature should therefore be treated as:

-   experimental
-   approximate
-   optional
-   future/stretch

It should not be part of the critical MVP unless the team can implement
it reliably.

------------------------------------------------------------------------

# 12. Satellite / Earth Observation Technology

## Does terrasim cover satellite technology?

Yes.

Satellite/Earth-observation data can be integrated into terrasim, but
satellite imagery should support the platform rather than exist only as
a buzzword.

Potential applications:

### Existing cities

-   land-cover analysis
-   development detection
-   flood extent observation
-   vegetation/environment context
-   change detection
-   settlement expansion

### New cities

-   terrain/context visualization
-   land-cover constraints
-   water bodies
-   development context
-   environmental planning

### Future versions

-   satellite change detection
-   historical hazard analysis
-   post-disaster assessment
-   automated land-use classification
-   monitoring of urban expansion

Satellite data can therefore become part of terrasim's broader
Earth-observation layer.

Important:

> Do not claim that terrasim uses satellites to directly predict
> earthquakes.

Satellite technology should be framed around observation, mapping,
monitoring, and environmental/geospatial context.

------------------------------------------------------------------------

# 13. AI in terrasim

AI should be used where it provides meaningful decision support.

Potential AI capabilities include:

## 13.1 AI-assisted planning

The user could say:

> "Place a hospital, school and residential zone while minimizing
> exposure."

The AI could suggest candidate locations based on the available
risk/suitability layers.

The output should remain a recommendation, not an authoritative planning
decision.

------------------------------------------------------------------------

## 13.2 AI photo interpretation

The optional building-photo feature can estimate:

-   approximate footprint
-   approximate height
-   approximate floors

It should not claim accurate structural strength from a photograph.

------------------------------------------------------------------------

## 13.3 AI explanation layer

After simulation, AI could translate geospatial results into
understandable language.

Example:

> "The proposed hospital is inside the higher-exposure zone for this
> scenario. A candidate area 350 m northeast has lower modeled exposure
> while remaining close to the main road."

The exact distance and risk claims must come from actual computed data,
not hallucinated AI text.

------------------------------------------------------------------------

# 14. Safe Route / Emergency Routing Concept

A future terrasim feature is scenario-aware routing.

Instead of simply finding the shortest route:

``` text
A → B
```

terrasim could consider:

-   hazard zones
-   flooded roads
-   blocked/exposed roads
-   elevation
-   critical facilities
-   road accessibility

and generate a route that minimizes exposure subject to reasonable
travel constraints.

Potential users:

-   emergency responders
-   municipalities
-   residents
-   hospitals
-   relief organizations

## Important distinction

This is not simply:

> "AI finds the safest road."

It should be:

> **"Risk-aware candidate emergency route."**

The system can rank candidate routes according to modeled exposure.

This is a strong future feature but should not distract from the core
MVP.

------------------------------------------------------------------------

# 15. Existing-City + New-City Combination

The final terrasim concept combines both.

## Existing city

### Question:

> "What happens if a disaster strikes here?"

### Output:

-   estimated hazard
-   exposure
-   affected infrastructure
-   vulnerable roads
-   critical facilities in risk zones

## New city

### Question:

> "How should we build here?"

### Output:

-   suitability/risk zones
-   candidate facility locations
-   proposed layout
-   simulation results
-   iterative improvement

This gives terrasim a clear lifecycle:

``` text
EXISTING CITY
    ↓
UNDERSTAND RISK
    ↓
LEARN FROM RISK
    ↓
PLAN FUTURE DEVELOPMENT
    ↓
SIMULATE
    ↓
IMPROVE
```

------------------------------------------------------------------------

# 16. Data Sources

Potential open/free sources discussed for the project include:

## OpenStreetMap

Use for:

-   roads
-   buildings
-   hospitals
-   schools
-   points of interest
-   other mapped infrastructure

OpenStreetMap is open data, subject to its attribution and licensing
requirements.

Official source:

https://www.openstreetmap.org/about

------------------------------------------------------------------------

## DEM / Elevation Data

Use for:

-   terrain
-   flood simulation
-   slope
-   elevation context
-   future suitability calculations

Potential datasets can include open digital elevation models.

The exact dataset should be selected based on geographic coverage and
resolution.

------------------------------------------------------------------------

## USGS Earthquake Data

Use for:

-   recent earthquake observations
-   earthquake locations
-   magnitudes
-   depth
-   historical/real-time context

USGS provides earthquake feeds including GeoJSON formats suitable for
programmatic applications.

Official feed:

https://earthquake.usgs.gov/earthquakes/feed/

------------------------------------------------------------------------

## Weather / Environmental Data

Potential use:

-   current weather
-   forecasts
-   rainfall context
-   environmental indicators

A service such as Open-Meteo was considered for weather data.

This is optional for the core MVP.

------------------------------------------------------------------------

## Satellite / Earth Observation

Potential sources include open Earth-observation datasets and satellite
imagery.

Potential uses:

-   land cover
-   change detection
-   environmental context
-   development monitoring
-   flood observation

Satellite imagery should be an enhancement rather than a dependency for
the first demo.

------------------------------------------------------------------------

# 17. Proposed Technical Stack

## Frontend

Possible:

-   React
-   Next.js
-   TypeScript
-   MapLibre GL JS

## Mapping

**MapLibre GL JS**

Use for:

-   interactive maps
-   vector layers
-   hazard overlays
-   terrain visualization
-   building/road layers
-   facility markers
-   map interactions

MapLibre GL JS is an open-source TypeScript library for interactive web
maps and supports terrain, 3D buildings, raster/satellite layers,
heatmaps, and other visualization techniques.

Official:

https://maplibre.org/projects/gl-js/

------------------------------------------------------------------------

## Backend

Possible:

-   Python
-   FastAPI

Responsibilities:

-   simulation requests
-   geospatial processing
-   data preparation
-   scenario calculations
-   route calculations
-   API endpoints

------------------------------------------------------------------------

## Geospatial Processing

Possible:

-   NumPy
-   Rasterio
-   GeoPandas
-   Shapely

Responsibilities:

### NumPy

Numerical array processing.

### Rasterio

Raster/DEM processing.

### GeoPandas

Vector geospatial processing.

### Shapely

Geometry operations/intersections.

------------------------------------------------------------------------

## Database

Optional:

-   PostgreSQL
-   PostGIS

For a two-day hackathon, PostGIS may be unnecessary if the dataset is
small and can be processed in memory or with simpler storage.

------------------------------------------------------------------------

# 18. High-Level Architecture

``` text
                    terrasim FRONTEND
                         |
             +-----------+-----------+
             |                       |
       EXISTING CITY             NEW CITY
       Simulate & Assess         Plan & Validate
             |                       |
             +-----------+-----------+
                         |
                     API SERVER
                         |
          +--------------+--------------+
          |              |              |
          ↓              ↓              ↓
      Elevation       Buildings      Hazard Data
        / DEM         / Roads       / Environment
          |              |              |
          +--------------+--------------+
                         |
                  SIMULATION ENGINE
                         |
             +-----------+-----------+
             |                       |
             ↓                       ↓
        Flood Model           Earthquake Model
             |                       |
             +-----------+-----------+
                         |
                  EXPOSURE ENGINE
                         |
          +--------------+--------------+
          |              |              |
       Buildings       Roads        Facilities
                         |
                         ↓
                    MAP OUTPUT
                         |
                         ↓
                 PLAN / MODIFY / RETEST
```

------------------------------------------------------------------------

# 19. MVP

The MVP should be small enough to finish under severe hackathon time
constraints.

The known team constraint discussed was:

-   3 coding members
-   2 days

Therefore the MVP should prioritize a polished vertical slice rather
than many incomplete features.

## Recommended MVP

### Must Have

1.  Interactive map
2.  Location selection
3.  Existing-city mode
4.  One strong disaster simulation
5.  Hazard/exposure overlay
6.  Building/road layer
7.  Critical facility markers
8.  New-city mode
9.  Basic suitability/risk zones
10. Place at least one facility
11. Run simulation on proposed layout
12. Show a before/after change

## Strongly recommended

Support both:

-   flood
-   earthquake

But if time is extremely limited, one fully working simulation is better
than two unreliable ones.

------------------------------------------------------------------------

# 20. MVP Demo Scenario

A reliable demo is more important than supporting every possible
location.

Prepare one known area in advance.

## Existing city demo

``` text
1. Open prepared city
2. Select earthquake
3. Select magnitude/depth/epicenter
4. Run simulation
5. Show estimated intensity/exposure
6. Toggle buildings/roads
7. Select hospital
8. Show exposure status
```

## New city demo

``` text
1. Switch to New City
2. Open prepared undeveloped area
3. Show green/yellow/red suitability zones
4. Place hospital
5. Place school
6. Place housing
7. Run scenario
8. Show hospital in higher-risk area
9. Move hospital
10. Run again
11. Show improved result
```

The final moment should communicate:

> **"We didn't just simulate the disaster. We used the simulation to
> improve the city."**

------------------------------------------------------------------------

# 21. Suggested Build Order for 2 Days

## Day 1

### Developer 1 --- Frontend/map

-   React/Next.js
-   MapLibre
-   map UI
-   location selection
-   layers
-   facility markers

### Developer 2 --- Simulation

-   DEM handling
-   flood model or earthquake model
-   scenario parameters
-   exposure calculation

### Developer 3 --- Data/backend

-   OSM data
-   API
-   facility data
-   data preprocessing
-   integration

By the end of Day 1:

> One complete existing-city simulation should work.

------------------------------------------------------------------------

## Day 2

### Developer 1

-   New-city UI
-   placement tools
-   visual polish

### Developer 2

-   suitability model
-   proposed-city simulation
-   before/after comparison

### Developer 3

-   integration
-   demo data
-   bugs
-   presentation screenshots
-   deployment

Final hours:

-   polish
-   test
-   rehearse
-   prepare fallback demo

------------------------------------------------------------------------

# 22. What Should NOT Be Built for the MVP

Avoid spending the hackathon on:

-   full hydrodynamic modeling
-   professional earthquake engineering
-   perfect structural damage prediction
-   complicated 3D city reconstruction
-   fully automated AI city design
-   perfect satellite segmentation
-   complex database infrastructure
-   real-time global disaster prediction
-   complicated authentication
-   mobile app before web prototype is stable
-   photo-based structural analysis

The MVP needs to demonstrate the central concept, not every possible
feature.

------------------------------------------------------------------------

# 23. Stretch Features

If the MVP is working:

## Stretch 1

Both flood and earthquake.

## Stretch 2

3D terrain.

## Stretch 3

Satellite layer.

## Stretch 4

AI-assisted planning.

## Stretch 5

Building-photo → approximate footprint.

## Stretch 6

Risk-aware emergency routing.

## Stretch 7

Scenario comparison.

Example:

``` text
Plan A
vs
Plan B
vs
Plan C
```

with metrics such as:

-   facilities exposed
-   roads exposed
-   estimated affected area
-   average distance to critical services

------------------------------------------------------------------------

# 24. Future Vision

Long-term terrasim could evolve into a broader resilience planning
platform.

Potential modules:

### Multi-hazard simulation

-   flood
-   earthquake
-   landslide
-   wildfire
-   extreme heat
-   storm
-   drought
-   other hazards

### Earth observation

-   urban expansion
-   land-use change
-   post-disaster mapping
-   environmental monitoring

### AI planning assistant

Natural-language planning:

> "Design a residential development while minimizing flood and
> earthquake exposure."

### Emergency response

-   risk-aware routing
-   facility accessibility
-   evacuation planning
-   hospital accessibility

### Scenario comparison

``` text
Current plan
vs
Plan A
vs
Plan B
```

### Municipal planning

Potential users:

-   municipalities
-   urban planners
-   disaster-management agencies
-   NGOs
-   developers
-   researchers
-   communities

------------------------------------------------------------------------

# 25. Satellite Technology Positioning

terrasim can legitimately include satellite/Earth-observation technology.

However, avoid adding "satellite" only to make the project sound
advanced.

A meaningful implementation should answer:

> "What does satellite information allow terrasim to do better?"

Good answers:

-   observe land cover
-   identify development
-   monitor change
-   contextualize terrain/environment
-   observe flood extent
-   support post-disaster mapping

Weak answer:

> "We use satellites for earthquake prediction."

Do not make that claim.

------------------------------------------------------------------------

# 26. AI Location-from-Photo Question

One idea discussed was:

> "Can AI predict a location from just a photo?"

Technically, computer vision/geolocation models can sometimes infer
approximate geographic location from visual clues.

Possible clues include:

-   architecture
-   road markings
-   vegetation
-   mountains
-   signs
-   terrain
-   utility infrastructure
-   urban form

But performance can vary greatly.

For terrasim, this should not be a core dependency.

A safer implementation is:

``` text
Photo
 ↓
AI suggests possible location
 ↓
User confirms location
 ↓
terrasim continues
```

Never assume the AI's geolocation is correct.

------------------------------------------------------------------------

# 27. Emergency Routing

Potential terrasim route system:

``` text
Origin
  ↓
Destination
  ↓
Generate candidate routes
  ↓
Intersect routes with hazard layers
  ↓
Score exposure
  ↓
Rank candidate routes
```

Example scoring:

``` text
Route A:
Shortest distance
High hazard exposure

Route B:
Longer
Lower hazard exposure

Route C:
Moderate distance
Moderate exposure
```

The system can recommend Route B as a lower-exposure candidate.

This should be framed as:

> **Risk-aware routing**

not:

> **Guaranteed safe routing**

------------------------------------------------------------------------

# 28. What Makes terrasim Interesting

The strongest conceptual progression is:

### Traditional GIS

> "Here is the risk."

### terrasim

> "Here is the risk. Now change the plan and test it again."

This distinction should appear in the presentation and explanation.

------------------------------------------------------------------------

# 29. What terrasim Is NOT

terrasim is NOT:

-   a disaster prediction system
-   an earthquake predictor
-   a professional structural engineering tool
-   a certified evacuation system
-   a replacement for government planning
-   a guaranteed-safe city generator
-   a perfect digital twin
-   a complete hydrodynamic model
-   a perfect AI urban planner

terrasim is:

> **A scenario-based geospatial decision-support prototype for
> resilience planning.**

------------------------------------------------------------------------

# 30. Scientific Honesty Rules

Always use:

-   estimated
-   hypothetical
-   scenario-based
-   modeled
-   relative
-   candidate
-   exposure
-   decision support

Avoid:

-   guaranteed
-   exact
-   certain
-   will collapse
-   definitely safe
-   predicts the earthquake
-   prevents disasters

The project becomes more credible when its limitations are explicit.

------------------------------------------------------------------------

# 31. Likely Judge Objections

## Objection 1

> "Isn't this just GIS?"

### Answer

"The map itself isn't our innovation. The workflow is. terrasimsim connects
disaster simulation with an iterative future-city planning loop: plan,
simulate, identify weaknesses, change the plan, and simulate again."

------------------------------------------------------------------------

## Objection 2

> "Can you actually predict earthquakes?"

### Answer

"No. terrasim does not predict when an earthquake will occur. We use
hypothetical earthquake scenarios to estimate relative exposure across a
selected area."

------------------------------------------------------------------------

## Objection 3

> "How accurate is the flood model?"

### Answer

"The hackathon MVP uses a terrain-based hypothetical flood extent, not a
full hydrodynamic model. It is designed to demonstrate scenario analysis
and planning rather than replace professional flood modeling."

------------------------------------------------------------------------

## Objection 4

> "Can you really tell whether a building will survive?"

### Answer

"No. A photograph or basic map footprint cannot establish structural
integrity. Our building analysis is an exposure proxy, not a structural
engineering assessment."

------------------------------------------------------------------------

## Objection 5

> "Why would planners trust it?"

### Answer

"terrasim should be treated as a decision-support and scenario-exploration
tool. A production version would require validated hazard models,
authoritative datasets, engineering review, and calibration."

------------------------------------------------------------------------

## Objection 6

> "What is actually innovative?"

### Answer

"Our focus is the closed-loop planning workflow. Instead of stopping at
risk visualization, terrasimsim lets users create a proposed development,
stress-test it, identify weaknesses, modify it, and test it again."

------------------------------------------------------------------------

# 32. Uniqueness / Competition Position

The idea is not globally unprecedented.

There are already:

-   GIS risk platforms
-   disaster simulators
-   flood models
-   earthquake hazard maps
-   urban planning tools
-   infrastructure exposure tools
-   resilience planning platforms

Therefore do NOT claim:

> "No one has ever built this."

The stronger claim is:

> "terrasim combines scenario simulation and future-development iteration
> into a simple, interactive workflow designed to be understandable and
> demonstrable in a hackathon."

The project is differentiated by the combination and workflow, not by
inventing the individual components.

------------------------------------------------------------------------

# 33. Main Competitive Weakness

A judge could say:

> "Existing professional GIS and disaster-planning platforms already do
> this."

This is a legitimate criticism.

terrasim's answer should be:

-   hackathon prototype
-   accessible interaction
-   simpler user experience
-   two-mode workflow
-   simulation-to-planning feedback loop
-   understandable visualization
-   future AI assistance
-   potential use by people who do not operate professional GIS software

Do not claim to replace professional systems.

------------------------------------------------------------------------

# 34. Strongest Feature vs Weakest Feature

## Strongest feature

**New-city iterative planning**

Why?

Because it demonstrates:

``` text
Plan
 ↓
Simulate
 ↓
Find problem
 ↓
Change
 ↓
Retest
```

It gives the judges a clear cause-and-effect demonstration.

## Second strongest

**Existing-city exposure simulation**

This provides an intuitive use case and establishes the foundation.

## Weakest / riskiest

**Photo → structural resistance**

It introduces scientific validity problems and should remain optional.

------------------------------------------------------------------------

# 35. Recommended Priority Ranking

For the hackathon:

  Priority   Feature
  ---------- -------------------------------------
  1          Existing-city map
  2          One working disaster simulation
  3          Exposure visualization
  4          New-city suitability map
  5          Facility placement
  6          Re-simulation after changing layout
  7          Second disaster type
  8          Satellite layer
  9          AI planning
  10         Photo-based building proxy
  11         Emergency routing
  12         Advanced 3D

------------------------------------------------------------------------

# 36. Presentation Strategy

The presentation is only **5 minutes**.

Therefore the pitch should have approximately **6 slides**.

Recommended timing:

  Section                Time
  ---------------- ----------
  Hook                 20 sec
  Problem              35 sec
  Solution             35 sec
  Core workflow        25 sec
  Live demo           \~2 min
  Impact/closing     \~40 sec

The demo should be the centerpiece.

------------------------------------------------------------------------

# 37. Slide Structure

## Slide 1 --- Hook

Headline:

> **WHAT IF WE COULD TEST A CITY BEFORE A DISASTER DOES?**

Show:

-   terrasim
-   tagline
-   environmental/geospatial visual

------------------------------------------------------------------------

## Slide 2 --- Problem

Headline:

> **WE BUILD FIRST. THEN DISCOVER THE RISK.**

Show:

``` text
BUILD
 ↓
DISASTER
 ↓
DISCOVER RISK
 ↓
RESPOND
```

Then:

``` text
ANALYZE
 ↓
SIMULATE
 ↓
PLAN
 ↓
IMPROVE
```

------------------------------------------------------------------------

## Slide 3 --- Solution

Headline:

> **ONE PLATFORM. TWO MODES.**

Two panels:

### Existing City

**Simulate & Assess**

### New City

**Plan & Validate**

------------------------------------------------------------------------

## Slide 4 --- Differentiator

Headline:

> **PLAN → SIMULATE → IMPROVE**

Show:

``` text
DESIGN
 ↓
SIMULATE
 ↓
FIND WEAKNESS
 ↓
CHANGE PLAN
 ↓
SIMULATE AGAIN
 ↓
BETTER PLAN
```

------------------------------------------------------------------------

## Slide 5 --- Demo

Show actual terrasim UI.

Demo:

``` text
Existing city
 ↓
Earthquake/flood
 ↓
Exposure
 ↓
Infrastructure
 ↓
New city
 ↓
Place hospital/school/housing
 ↓
Simulate
 ↓
Find weakness
 ↓
Move facility
 ↓
Simulate again
 ↓
Improvement
```

------------------------------------------------------------------------

## Slide 6 --- Impact / Closing

Headline:

> **SIMULATE TODAY'S RISKS. PLAN TOMORROW'S RESILIENT CITIES.**

Three areas:

### Existing Cities

Understand exposure.

### Future Cities

Reduce avoidable risk.

### Emergency Response

Identify lower-exposure candidate routes.

Final statement:

> **"We didn't just simulate the disaster. We used the simulation to
> improve the city."**

------------------------------------------------------------------------

# 38. Presentation Visual Identity

A major design direction was established using a reference image.

The desired visual style is:

**Premium cinematic pixel-art environmental world + modern geospatial
technology.**

The reference aesthetic contains:

-   pixel-art environment
-   lush forests
-   waterfall/water
-   stone structures
-   cyan sky/water
-   deep greens
-   dramatic lighting
-   dense natural foreground
-   atmospheric depth

The presentation should feel like:

> **A beautiful pixel-art exploration game meets climate-resilience
> technology.**

It should NOT feel like:

-   generic corporate PowerPoint
-   sterile GIS software
-   cyberpunk dashboard
-   children's cartoon
-   generic AI startup
-   flat business template

------------------------------------------------------------------------

# 39. Presentation Color Palette

Suggested:

``` text
Deep Forest Green  #123524
Dark Green         #071D18
Emerald            #287A45
Teal               #159A9C
Water/Cyan         #43C7D8
Sky                #8DD9E6
Stone              #65746B
Warm Highlight     #E6C66A

Risk Red           #E34B4B
Warning Orange     #E59B45
Safe Green         #55B86A
```

Green and cyan should dominate.

Red/orange should communicate risk rather than decoration.

------------------------------------------------------------------------

# 40. Typography

Recommended:

-   Inter
-   Space Grotesk
-   IBM Plex Sans

Use:

-   large headlines
-   short supporting text
-   generous spacing
-   high contrast

Avoid excessive use of pixel fonts for body text.

The pixel aesthetic should come from:

-   artwork
-   terrain
-   icons
-   textures
-   maps
-   environmental compositions

rather than making all text pixelated.

------------------------------------------------------------------------

# 41. Visual Presentation Principle

Do NOT make every slide pixel art.

Recommended progression:

### Slide 1

Cinematic pixel-art world.

### Slide 2

Pixel-art disaster + clean conceptual diagram.

### Slide 3

Pixel-art + GIS hybrid.

### Slide 4

Illustrated planning workflow.

### Slide 5

Actual terrasimsim UI / GIS product.

### Slide 6

Cinematic pixel-art resilient future city.

This creates a coherent visual language without making the project look
like a game.

------------------------------------------------------------------------

# 42. Presentation Generator Prompt

A presentation generator can be given this high-level instruction:

> Create a 6-slide, 5-minute hackathon pitch deck for terrasim --- Building
> Resilient Areas for Climate & Emergencies.
>
> Track: Climate Change, Resilience & Sustainability.
>
> Core message: terrasim lets us simulate disasters in existing cities and
> stress-test proposed future developments before they are built.
>
> Key differentiator: PLAN → SIMULATE → IMPROVE.
>
> The visual style should be inspired by premium cinematic pixel-art
> environmental scenes: lush forests, rivers, mountains, cyan water,
> deep greens, atmospheric lighting, detailed pixel textures, and cities
> integrated with nature.
>
> Combine that environmental identity with modern geospatial maps and
> clean typography.
>
> Avoid generic corporate, cyberpunk, sterile GIS, or children's-cartoon
> aesthetics.
>
> The six slides should be:
>
> 1.  Hook --- "What if we could test a city before a disaster does?"
> 2.  Problem --- we often discover risk after construction.
> 3.  Solution --- Existing City vs New City.
> 4.  Differentiator --- Plan → Simulate → Improve.
> 5.  Demo --- existing city simulation and new-city planning loop.
> 6.  Impact/closing --- "Simulate today's risks. Plan tomorrow's
>     resilient cities."
>
> Keep text minimal and make maps/visuals the dominant elements.
>
> Do not claim exact prediction or guaranteed safety.

------------------------------------------------------------------------

# 43. Five-Minute Pitch Script

A concise version:

> "What if we could test a city before a disaster does?
>
> Today, we often discover vulnerabilities after cities have already
> been built.
>
> terrasim is a geospatial disaster-risk simulation and planning platform.
>
> For existing cities, we can simulate hypothetical floods and
> earthquakes and visualize which buildings, roads and critical
> facilities fall within the estimated exposure.
>
> But terrasim goes one step further.
>
> For areas that haven't been developed yet, we can analyze the land,
> propose where hospitals, schools and housing should go, and then
> stress-test that proposed city.
>
> If the simulation exposes a weakness, we change the plan and simulate
> again.
>
> That's our core loop: Plan, Simulate, Improve.
>
> terrasim is not trying to predict earthquakes or replace professional
> engineering. It is a scenario-based decision-support tool for
> exploring risk and improving plans.
>
> We didn't just simulate the disaster. We used the simulation to
> improve the city."

------------------------------------------------------------------------

# 44. Recommended Demo Script

## Existing city

> "Let's start with an existing area."

Select scenario.

> "Suppose a hypothetical earthquake occurs here."

Run simulation.

> "terrasim generates a scenario-based exposure layer."

Toggle infrastructure.

> "Now we can see which roads and critical facilities fall inside the
> estimated higher-exposure area."

------------------------------------------------------------------------

## New city

> "But what if the city hasn't been built yet?"

Switch mode.

> "We can start with the land itself."

Show suitability zones.

> "Now let's place a hospital, school and residential area."

Run scenario.

> "Our proposed hospital falls inside a higher-exposure zone under this
> scenario."

Move hospital.

Run again.

> "We change the plan and test again."

Then:

> **"We didn't just simulate the disaster. We used the simulation to
> improve the city."**

------------------------------------------------------------------------

# 45. Technical Explanation for Judges

If asked:

> "What technologies are you using?"

Answer:

> "The frontend is built around React/Next.js and MapLibre for
> interactive geospatial visualization. Python/FastAPI handles the
> backend and simulation logic, with NumPy, Rasterio, GeoPandas and
> Shapely for geospatial processing. We use OpenStreetMap for
> infrastructure data and DEM/elevation datasets for terrain-based
> simulation, with Earth-observation data as an optional layer."

Short version for forms:

> **React/Next.js, TypeScript, MapLibre GL JS, Python, FastAPI, NumPy,
> GeoPandas, Rasterio, Shapely, OpenStreetMap, DEM/elevation data, and
> satellite/Earth-observation datasets.**

------------------------------------------------------------------------

# 46. Deployment Concept

Possible deployment:

``` text
Frontend
   ↓
Vercel / similar platform

Backend
   ↓
FastAPI server

Data / processing
   ↓
Preprocessed datasets / object storage

Optional database
   ↓
PostgreSQL + PostGIS
```

For a hackathon, precomputing or caching a small number of demo
locations is acceptable.

A stable demo is more valuable than attempting global real-time
computation.

------------------------------------------------------------------------

# 47. Reliability Strategy for the Demo

The demo should have a fallback.

## Primary

Live simulation.

## Secondary

Preloaded demo scenario.

## Emergency fallback

Screenshots/video of the working simulation.

The presenter should never depend on an internet API responding
perfectly during the pitch.

Prepare:

-   one known city
-   one known empty/planning area
-   one flood scenario
-   one earthquake scenario
-   preloaded OSM data if possible
-   cached results if necessary

------------------------------------------------------------------------

# 48. What Judges Should Remember

After the presentation, the judge should be able to repeat:

> **"terrasim lets you simulate a disaster, find what is exposed, change
> the city plan, and test it again."**

If they instead remember:

> "It uses Python, React, satellites, AI, GIS, APIs, DEMs, and
> earthquakes..."

the pitch has failed to communicate the central idea.

------------------------------------------------------------------------

# 49. Core Product Story

The entire project can be reduced to this:

``` text
A CITY
  ↓
A DISASTER SCENARIO
  ↓
A SIMULATION
  ↓
EXPOSURE
  ↓
A PLANNING DECISION
  ↓
A BETTER CITY
```

This is terrasim.

------------------------------------------------------------------------

# 50. Final Product Definition

## terrasim

**Building Resilient Areas for Climate & Emergencies**

terrasim is a scenario-based geospatial resilience platform with two modes:

### 1. Existing City --- Simulate & Assess

Simulate hypothetical disasters and visualize estimated exposure of
buildings, roads and critical infrastructure.

### 2. New City --- Plan & Validate

Analyze an undeveloped or developing area, propose a city layout, place
critical infrastructure, simulate disaster scenarios, identify
weaknesses, modify the layout, and test again.

### Central loop

> **PLAN → SIMULATE → IMPROVE**

### Primary value

> Help people understand current exposure and experiment with safer
> future development before decisions become physical reality.

### Primary limitation

> It is a prototype and should not be presented as a professional
> prediction, engineering, or guaranteed-safety system.

### Best hackathon demonstration

> Move a hospital from a higher-exposure candidate location to a
> lower-exposure candidate location, rerun the simulation, and visually
> demonstrate the improvement.

------------------------------------------------------------------------

# 51. Official / Technical Reference Notes

These are useful references for implementation and verification.

## OpenStreetMap

OpenStreetMap provides open map data covering roads, buildings, places
and other geographic features. Attribution and licensing requirements
must be respected.

https://www.openstreetmap.org/about

## USGS Earthquake Feeds

USGS provides earthquake feeds, including GeoJSON feeds suitable for
programmatic applications.

https://earthquake.usgs.gov/earthquakes/feed/

## MapLibre GL JS

MapLibre GL JS is an open-source TypeScript library for interactive web
maps. It supports vector maps, terrain, 3D buildings, raster/satellite
layers, heatmaps and other visualization approaches.

https://maplibre.org/projects/gl-js/

------------------------------------------------------------------------

# 52. Final Rules for Any Future AI Working on terrasim

When helping with terrasim:

1.  Preserve the two-mode structure.
2.  Preserve the Plan → Simulate → Improve loop.
3.  Do not turn terrasimsim into a generic disaster map.
4.  Do not overclaim prediction accuracy.
5.  Distinguish MVP features from future features.
6.  Prefer one reliable simulation over many broken simulations.
7.  Treat AI as decision support, not an oracle.
8.  Treat satellite imagery as meaningful Earth-observation data, not
    decoration.
9.  Treat routing as risk-aware candidate routing, not guaranteed-safe
    routing.
10. Treat building-photo analysis as approximate geometry/exposure
    assistance, not structural engineering.
11. Keep the hackathon demo simple.
12. Prioritize the new-city iterative planning workflow.
13. Use real data where possible.
14. Be transparent about assumptions.
15. If a judge challenges the novelty, acknowledge that individual
    components already exist and explain that terrasim's differentiation is
    the integrated interactive workflow.
16. Keep the presentation centered around one memorable message: **"We
    didn't just simulate the disaster. We used the simulation to improve
    the city."**

------------------------------------------------------------------------

# 53. terrasim in One Paragraph

terrasim (Building Resilient Areas for Climate & Emergencies) is a
scenario-based geospatial disaster simulation and urban-planning
platform for climate resilience. It has two modes: an Existing City mode
that lets users simulate hypothetical disasters such as floods and
earthquakes and visualize estimated exposure of buildings, roads,
hospitals and schools; and a New City mode that lets users analyze
undeveloped areas, propose infrastructure placement, simulate disasters
against the proposed layout, identify weaknesses, and modify the plan.
Its central workflow is **Plan → Simulate → Improve**. terrasim can combine
OpenStreetMap infrastructure data, DEM/elevation data, hazard feeds,
satellite/Earth-observation information, geospatial processing, and
eventually AI-assisted planning and risk-aware emergency routing. It is
deliberately framed as a decision-support prototype rather than a
disaster predictor or professional engineering system.

------------------------------------------------------------------------

# 54. One-Line Definition

> **terrasim lets you test the city you have --- and experiment with the
> resilient city you want to build.**
