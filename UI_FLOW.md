# PBJ Canonical User Flow

**Status:** Required product contract
**Last updated:** September 1, 2026

## Troy facelift presentation contract

The `troy-facelift` branch may restyle every PBJ-owned screen using the approved
iPhone-first visual system documented in `docs/TROY_FACELIFT_PLAN.md`. The route
order below does not change. Troy's Studio is excluded; Timeline Ready continues
to hand the project to OpenReel. Black primary actions balanced with purple
active and progress states are presentation changes, not new product authority.
Troy's mock state, fake projects, simulated progress, Clerk authentication, and
alternate backend must not enter this flow.

## Current project journey

```text
Private access → Home → Describe → Optional references → Raw footage
  → Final details → Analysis and timeline preparation → Timeline ready → OpenReel editor
```

PBJ analyzes supplied media and creates a validated, populated canonical timeline.
The former PBJ editor has been removed. Timeline Ready hands the populated
project to OpenReel, which owns the editing screen and full editing session.
PBJ does not render a combined first cut during preparation.

## Required screens

| State | Canonical route | Required outcome |
|---|---|---|
| Private access | `/access` | Authorize the device for seven days. |
| Home | `/` | Resume work or start a project. |
| Describe | `/projects/new` | Capture the desired edit in natural language. |
| References | `/projects/new/references` | Optionally add finished examples or continue. |
| Footage | `/projects/new/footage` | Upload only media PBJ may use. |
| Final details | `/projects/{project_id}/brief` | Add optional requirements and start analysis. |
| Preparation | `/projects/{project_id}/production-progress` | Distinguish footage analysis, timeline planning/validation, and handoff preparation. |
| Timeline ready | `/projects/{project_id}/ready` | Confirm that PBJ's validated timeline is ready and offer one clear Open in Editor action. |
| OpenReel editor | `/projects/{project_id}/openreel` | Enter the configured OpenReel host with the PBJ project identity; load the latest valid snapshot or the first timeline. |

## Current boundaries

- `/projects/{project_id}/editor` and its PBJ-owned browser interface do not exist.
- Historical `/review`, `/revision`, and `/approval` pages redirect to the timeline-ready screen or an already completed export.
- Canonical timeline data, typed operations, validation, history, proposals, export compilation, and learning evidence remain backend infrastructure.
- The OpenReel handoff route is implemented. OpenReel owns the editing interface, complete editing project, tools, playback, and undo/redo. PBJ supplies and hydrates the first project media, stores whole-project snapshots, and restores the latest valid snapshot on reopen. The pinned OpenReel app invokes PBJ's export-intent, completed-render receipt, and explicit final-approval learning gates through one Export & Approve action. A complete supplied-media playback, export, receipt, download, and approval walkthrough passed on August 30, 2026.
- At widths through 767px, and at short phone-landscape viewports through 900×500, the OpenReel editor route uses an implemented iPhone-first short-form layout: its Preview and compact native Timeline remain visible together, its existing Assets and Inspector panels open as dismissible sheets, and selecting a clip exposes a bottom tray for OpenReel's Split, Delete, Speed, Crop, and Volume paths. The mobile playhead stays fixed at the horizontal center while the padded timeline scrolls beneath it; scrolling scrubs OpenReel's current time and playback advances the timeline under the fixed line. Existing clip move and trim interactions accept pointer input with larger narrow-screen trim targets. PBJ sessions bypass OpenReel's standalone Desktop Only overlay and use safe-area-aware, enforced dynamic-height, unlocked-orientation PWA presentation so navigation, timeline, and contextual tools remain above Safari chrome. A dirty whole-project snapshot flushes immediately when Safari hides or backgrounds the page. Home Screen relaunch may use the last successfully loaded device-local PBJ project pointer, but the normal PBJ authority and media checks run again before the editor opens. Mobile-safe per-source proxies hydrate sequentially—including after phone rotation—and abandoned requests abort. This is a responsive presentation of the same OpenReel editor and project state, not a separate PBJ editor. Representative portrait and landscape browser QA passes; physical iPhone acceptance remains pending.
- PBJ must not recreate or individually bridge move, trim, split, crop, playback, or other OpenReel features. Features that violate PBJ media rules or cannot survive snapshot restore and export are disabled.
- Recipes remain invisible throughout the normal journey.
- Retired analyzer-first and rough-cut routes remain redirects only; historical downloads remain available.

Any intentional flow change requires matching updates to this file,
`PROJECT_PLAN.md`, live routes/templates, and route-contract tests.
