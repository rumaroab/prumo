# Fire and Road Exposure Platform — Build Plan

This project follows the approved eight-stage plan in `ideas/06-fire-aware-road-access.md` and the implementation request from 19 October 2026.

1. Foundation and persistent checkpoints
2. Leaflet map interface
3. OpenStreetMap roads and topology
4. Terrain and fuel landscape preparation
5. Cell2Fire adapter
6. Fire-to-road exposure analysis
7. Interactive runs and Python MTT
8. Saved demonstrations and local handoff

Every stage must leave reusable artifacts under `data/` and update `PROGRESS.md`. Cell2Fire and Python MTT share the contracts in `backend/app/models.py`. Source datasets are never silently replaced: illustrative bundled data is labelled as such, while real preparation requires source files or an explicit network fetch.

