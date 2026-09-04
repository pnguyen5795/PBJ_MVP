# PBJ Canonical User Flow

**Status:** Required product contract
**Last updated:** September 4, 2026

## Presentation contract

The `troy-facelift` branch uses the approved Troy iPhone screen compositions documented in `docs/TROY_FACELIFT_PLAN.md`. It imports presentation only. Troy's Studio, mock state, fake projects, simulated progress, Clerk authentication, and alternate backend are excluded.

## Current project journey

```text
Demo launcher (hosted only) → Private access → Home → Describe → Optional references → Raw footage
  → Final details → Analyze, plan, validate, and render → Rough cut review
  → Approve OR request changes → Replan and render a new version
```

PBJ creates a validated structured timeline and automatically renders it with FFmpeg from project-supplied originals. PBJ has no manual editing screen. The user reviews a playable MP4, approves it, or describes a revision in natural language.

## Required screens

| State | Canonical route | Required outcome |
|---|---|---|
| Demo launcher | Launcher `/` and `/start` | In hosted-demo mode, accept the same exact private code, ask Render to resume PBJ, show truthful startup progress, and open the PBJ URL only after its public health check succeeds. The Render credential must never reach the browser. |
| Private access | `/access` | Authorize the browser for seven days with an exact code. In hosted-demo mode, authorized browsers enter the same private workspace. Repeated failures are throttled. |
| Home | `/` | Resume work or start a project. |
| Workspace controls | `/more` | Reach projects/operator tools and explicitly log out. |
| Describe | `/projects/new` | Capture the desired edit in natural language within the private demo's bounded signed-session draft. |
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

- `POST /projects/new/fresh` deliberately clears the current browser draft and upload pointer before redirecting to `/projects/new`. `GET /projects/new` is read-only with respect to an existing draft, so a cross-site navigation cannot discard in-progress setup.
- `POST /projects/{project_id}/approve` requires explicit confirmation and approves only a QA-passed completed render whose saved timeline hash still matches the current working edit.
- Raw-footage uploads preserve every fully received file in a device-owned upload session. If iOS suspends the browser, reopening the same project draft resumes that session and asks only for unfinished files; a different draft never inherits the earlier batch. Unreadable staged copies are removed while readable files remain available for retry. A partially transmitted individual file may still require reselection. Post-upload FFprobe inspection runs outside the web event loop so health checks and normal pages remain responsive during large batches.
- `POST /projects/{project_id}/revise` requires nonempty feedback, replans from cached analysis, validates the new timeline, and renders a new version.
- `POST /projects/{project_id}/retry` rebuilds either current or legacy saved-plan artifacts with frame-safe boundaries before retrying a failed or incomplete export. A failed revision reuses its exact saved request; an initial preparation retry invents no revision instruction. Failures show their recorded cause rather than a generic dead end.
- `POST /projects/new/references-retry` retries failed recipe synthesis from saved eligible analysis without requiring a replacement upload.
- Completed videos download from `/projects/{project_id}/exports/{export_id}/download`.
- Saved project-owned Twelve Labs evidence and PBJ's combined content map download as one ZIP from `/projects/{project_id}/analysis-data/download`.
- The rough-cut review links to a read-only analysis viewer; it does not restore analyzer selection or an approval gate before rendering.
- Every completed render remains independently playable in one version player with Previous/Next navigation and the prompt that produced that cut; approval and revision actions stay attached to the latest cut.
- When a newer edit fails, the project opens its truthful failure page. An older completed cut remains available through an explicitly labeled link and cannot be mistaken for or approved as the failed edit.
- Historical `/review`, `/revision`, and `/approval` links resolve into the current rough-cut review experience.
- `/projects/{project_id}/editor` and `/projects/{project_id}/openreel` do not exist.
- Direct `/api/projects/...` timeline transaction, undo/redo, proposal, editor-asset/proxy, and export-control routes do not exist. Timeline state is application-internal.
- Retired analyzer selection, manual rough-cut, and comparison endpoints remain removed or redirects.
- `POST /diagnostics/client` accepts only allowlisted, bounded operational fields; `/diagnostics/download` requires owner access and never contains filenames, media, prompts, credentials, or raw exception text.
- `POST /logout` clears access, owner privilege, the current draft, and upload pointers; local mode preserves only the device identity needed to find that device's projects after signing in again.
- Hosted state-changing requests must come from the same origin. Access/owner form bodies are rejected above 1 KiB before parsing; project names, descriptions, and the complete prospective signed session are bounded so accepted cookies remain below 4 KiB. The Home Screen shell requires a network connection and does not register a service worker or retain an offline cache. When an older installation reconnects, current pages unregister the retired worker and delete only its legacy `pbj-shell-*` cache.
- Visible authorized PBJ pages report activity at a bounded interval. After 10 minutes without visible activity, PBJ may request suspension through the separate launcher only when no request, upload inspection/promotion, project or recipe job, export, deletion, FFprobe, or FFmpeg process remains active. Health checks and automatic progress polling do not count as user activity. A suspended demo is reopened from the launcher, not directly from the PBJ URL.

## Current boundaries

- Recipes remain invisible throughout the normal journey.
- PBJ never exposes raw provider machinery in the normal workflow.
- PBJ does not provide move, trim, split, crop, or other manual timeline controls.
- Recipe Engine v1 uses original audio carried by uploaded source video; a separate audio-upload control is not exposed in this flow.
- Revision is prompt-driven and produces a new version from the same validated media and cached analysis.
- Rendering uses original project assets only and produces a verified H.264/AAC MP4.
- Approval remains separate from successful rendering and is the only positive outcome signal.
- The shared shell has no persistent bottom navigation bar.
- Every sequential screen has an obvious Back action and one context-specific primary action where truthful.
- Local mode keeps projects isolated to their originating device. Explicit hosted-demo mode maps every authorized browser to one shared private workspace; it is not a multi-user beta.
- The hosted demo runs on a 1 CPU / 2 GB Render web service but still uses disposable storage: project media and results may vanish after suspension, restarts, or redeploys. Important projects require the later persistent-storage upgrade.

Any intentional flow change requires matching updates to this file, `PROJECT_PLAN.md`, live routes/templates, and route-contract tests.
