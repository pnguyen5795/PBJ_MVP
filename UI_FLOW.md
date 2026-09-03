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
| Private access | `/access` | Authorize the browser for seven days. In hosted-demo mode, authorized browsers enter the same private workspace. |
| Home | `/` | Resume work or start a project. |
| Describe | `/projects/new` | Capture the desired edit in natural language. |
| References | `/projects/new/references` | Optionally add finished examples or explicitly skip. A missing/failed file attachment must remain on this screen with a clear retry message; it must never be interpreted as Skip. |
| Footage | `/projects/new/footage` | Upload only media PBJ may use in a compact picker; infer target duration from the creative brief rather than showing a separate length control. |
| Final details | `/projects/{project_id}/brief` | Add optional requirements and start production. |
| Production | `/projects/{project_id}/production-progress` | Show truthful analysis, planning/validation, and FFmpeg rendering stages. |
| Rough-cut review | `/projects/{project_id}/ready` | Play the latest completed MP4 and offer Approve or Request Changes. |
| Analysis results | `/projects/{project_id}/analysis-results` | Optionally inspect each footage file's saved timestamped Twelve Labs findings without interrupting production. |
| Cut comparison | `/projects/{project_id}/cuts` | Open the newest completed render in the version player. |
| Individual cut | `/projects/{project_id}/cuts/{export_id}` | Play one preserved cut on its own page. |
| Approval | `/projects/{project_id}/approval` | Return to the approved cut and expose download/home actions. |
| Diagnostics export | `/diagnostics/download` | Let an owner download privacy-safe client operational events for support. |

## Route behavior

- `POST /projects/{project_id}/approve` requires explicit confirmation and approves only the latest completed render.
- Raw-footage uploads preserve every fully received file in a device-owned upload session. If iOS suspends the browser, reopening the footage route resumes that session and asks only for unfinished files; a partially transmitted individual file may still require reselection. Post-upload FFprobe inspection runs outside the web event loop so health checks and normal pages remain responsive during large batches.
- `POST /projects/{project_id}/revise` requires nonempty feedback, replans from cached analysis, validates the new timeline, and renders a new version.
- `POST /projects/{project_id}/retry` rebuilds either current or legacy saved-plan artifacts with frame-safe boundaries before retrying a failed or incomplete export; failures show their recorded cause rather than a generic dead end.
- `POST /projects/new/references-retry` retries failed recipe synthesis from saved eligible analysis without requiring a replacement upload.
- Completed videos download from `/projects/{project_id}/exports/{export_id}/download`.
- Saved project-owned Twelve Labs evidence and PBJ's combined content map download as one ZIP from `/projects/{project_id}/analysis-data/download`.
- The rough-cut review links to a read-only analysis viewer; it does not restore analyzer selection or an approval gate before rendering.
- Every completed render remains independently playable in one version player with Previous/Next navigation and the prompt that produced that cut; approval and revision actions stay attached to the latest cut.
- Historical `/review`, `/revision`, and `/approval` links resolve into the current rough-cut review experience.
- `/projects/{project_id}/editor` and `/projects/{project_id}/openreel` do not exist.
- Retired analyzer selection, manual rough-cut, and comparison endpoints remain removed or redirects.
- `POST /diagnostics/client` accepts only allowlisted, bounded operational fields; `/diagnostics/download` requires owner access and never contains filenames, media, prompts, credentials, or raw exception text.

## Current boundaries

- Recipes remain invisible throughout the normal journey.
- PBJ never exposes raw provider machinery in the normal workflow.
- PBJ does not provide move, trim, split, crop, or other manual timeline controls.
- Revision is prompt-driven and produces a new version from the same validated media and cached analysis.
- Rendering uses original project assets only and produces a verified H.264/AAC MP4.
- Approval remains separate from successful rendering and is the only positive outcome signal.
- The shared shell has no persistent bottom navigation bar.
- Every sequential screen has an obvious Back action and one context-specific primary action where truthful.
- Local mode keeps projects isolated to their originating device. Explicit hosted-demo mode maps every authorized browser to one shared private workspace; it is not a multi-user beta.
- The hosted demo runs on a 1 CPU / 2 GB Render web service but still uses disposable storage: project media and results may vanish after restarts or redeploys. The UI flow is unchanged, but important projects require the later persistent-storage upgrade.

Any intentional flow change requires matching updates to this file, `PROJECT_PLAN.md`, live routes/templates, and route-contract tests.
