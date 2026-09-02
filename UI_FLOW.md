# PBJ Canonical User Flow

**Status:** Required product contract
**Last updated:** September 1, 2026

## Presentation contract

The `troy-facelift` branch uses the approved Troy iPhone screen compositions documented in `docs/TROY_FACELIFT_PLAN.md`. It imports presentation only. Troy's Studio, mock state, fake projects, simulated progress, Clerk authentication, and alternate backend are excluded.

## Current project journey

```text
Private access → Home → Describe → Optional references → Raw footage
  → Final details → Analyze, plan, validate, and render → Rough cut review
  → Approve OR request changes → Replan and render a new version
```

PBJ creates a validated structured timeline and automatically renders it with FFmpeg from project-supplied originals. PBJ has no manual editing screen. The user reviews a playable MP4, approves it, or describes a revision in natural language.

## Required screens

| State | Canonical route | Required outcome |
|---|---|---|
| Private access | `/access` | Authorize the device for seven days. |
| Home | `/` | Resume work or start a project. |
| Describe | `/projects/new` | Capture the desired edit in natural language. |
| References | `/projects/new/references` | Optionally add finished examples or continue. |
| Footage | `/projects/new/footage` | Upload only media PBJ may use. |
| Final details | `/projects/{project_id}/brief` | Add optional requirements and start production. |
| Production | `/projects/{project_id}/production-progress` | Show truthful analysis, planning/validation, and FFmpeg rendering stages. |
| Rough-cut review | `/projects/{project_id}/ready` | Play the latest completed MP4 and offer Approve or Request Changes. |
| Cut comparison | `/projects/{project_id}/cuts` | Open the newest completed render in the version player. |
| Individual cut | `/projects/{project_id}/cuts/{export_id}` | Play one preserved cut on its own page. |
| Approval | `/projects/{project_id}/approval` | Return to the approved cut and expose download/home actions. |

## Route behavior

- `POST /projects/{project_id}/approve` requires explicit confirmation and approves only the latest completed render.
- `POST /projects/{project_id}/revise` requires nonempty feedback, replans from cached analysis, validates the new timeline, and renders a new version.
- `POST /projects/new/references-retry` retries failed recipe synthesis from saved eligible analysis without requiring a replacement upload.
- Completed videos download from `/projects/{project_id}/exports/{export_id}/download`.
- Every completed render remains independently playable in one version player with Previous/Next navigation and the prompt that produced that cut; approval and revision actions stay attached to the latest cut.
- Historical `/review`, `/revision`, and `/approval` links resolve into the current rough-cut review experience.
- `/projects/{project_id}/editor` and `/projects/{project_id}/openreel` do not exist.
- Retired analyzer selection, manual rough-cut, and comparison endpoints remain removed or redirects.

## Current boundaries

- Recipes remain invisible throughout the normal journey.
- PBJ never exposes raw provider machinery in the normal workflow.
- PBJ does not provide move, trim, split, crop, or other manual timeline controls.
- Revision is prompt-driven and produces a new version from the same validated media and cached analysis.
- Rendering uses original project assets only and produces a verified H.264/AAC MP4.
- Approval remains separate from successful rendering and is the only positive outcome signal.
- The shared shell has no persistent bottom navigation bar.
- Every sequential screen has an obvious Back action and one context-specific primary action where truthful.

Any intentional flow change requires matching updates to this file, `PROJECT_PLAN.md`, live routes/templates, and route-contract tests.
