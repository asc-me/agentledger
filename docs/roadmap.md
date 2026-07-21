# Roadmap

A phased roadmap with progress rolled up from milestones, plus a **shareable read-only
public link**.

## Phases

Milestones are grouped into three phases with fixed metadata:

| Phase | Window | Color |
| --- | --- | --- |
| **MVP** | 2–4 weeks | `#c6f24e` |
| **Post-MVP** | Q3 2026 | `#7ca2ff` |
| **Later** | exploring | `#a78bfa` |

Each phase shows an `x / y shipped` count and a progress bar computed from its milestones'
`done` flags. Each milestone has a title, a tag, and a done state (a green check).

## Public roadmap

- The Roadmap view has a **Copy public link** button that copies `…/embed/roadmap`.
- `/embed/roadmap` is an unauthenticated, read-only page (its own branded header) backed by
  `GET /api/public/roadmap`.
- The in-app view and the public page share one `RoadmapBoard` component.

## How it works

- Data: the `milestones` table (added by Alembic migration `0003`), seeded from the design.
- Service: `backend/app/services/roadmap.py` — `list_roadmap` groups milestones by phase and
  computes progress.
- Frontend: `web/src/features/roadmap/` (`RoadmapView`, `EmbedRoadmapPage`, `RoadmapBoard`).

## API

| Method | Path | Auth | Purpose |
| --- | --- | --- | --- |
| GET | `/api/roadmap` | JWT | Phases with milestones + progress |
| GET | `/api/public/roadmap` | **public** | Same, read-only, for the share link |
