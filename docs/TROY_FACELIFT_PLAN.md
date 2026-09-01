# Troy Facelift Implementation Plan

**Branch:** `troy-facelift`
**Status:** Approved for phased implementation
**Last updated:** September 1, 2026

## Objective

Adopt the mobile visual system from Troy's PB&J frontend while preserving PBJ's
existing backend, canonical routes, project data, privacy model, learning system,
and governed OpenReel integration.

Troy's frontend is a visual source, not a replacement application architecture.
PBJ will not import Troy's mock state, simulated rendering, Clerk authentication,
alternate backend, fake projects, or Studio. OpenReel remains the only editing
surface.

## Source and permission

- Source repository: `https://github.com/Swag420Money/PB-J.git`
- Reviewed commit: `10c8efdf2f2187604a934d082d038db8729a75d9`
- Permission: the PBJ owner confirmed permission to use and modify Troy's code,
  design, and supplied artwork on September 1, 2026.
- The source repository has no license file. PBJ must retain this permission
  record and exact imported-file provenance.

## Approved visual direction

- iPhone-first application presentation; desktop receives only resilient fallback
  behavior during this phase.
- Warm cream-to-white canvas, Apple system typography, generous spacing, rounded
  controls, and restrained motion.
- Black primary calls to action balanced by purple highlights, progress, active
  states, and selected controls.
- Troy's sandwich logo and layered cooking artwork may be adapted.
- Recipes remain invisible. User-facing “recipe” language may describe the
  creative brief, but must never expose internal recipe selection or management.

## Screen mapping

| Troy visual | PBJ authority |
|---|---|
| Splash / Sign In | PBJ splash and server-validated private access code |
| Home | PBJ real projects, resume authority, and real job banners |
| New Project — Upload | PBJ permissioned footage upload |
| The Recipe | PBJ natural-language brief and optional project requirements |
| Teach Us Your Style | PBJ optional reference-video learning |
| Cooking | PBJ real analysis, planning, validation, and handoff progress |
| My Projects | PBJ device-private project records |
| Settings | PBJ real settings and operator boundaries |
| Studio | Excluded; PBJ proceeds through Timeline Ready to OpenReel |

The canonical route order in `UI_FLOW.md` remains authoritative. Visual grouping
must not collapse or reorder routes without an explicit contract and test update.

## Phases and gates

### Phase 0 — Contract and provenance lock

**Status:** Completed September 1, 2026

- Pin Troy's reviewed commit and record permission.
- Define the screen mapping, exclusions, and black/purple visual direction.
- Preserve PBJ's existing route and backend contracts.

**Gate:** governing documents agree on source, scope, exclusions, and authority.

**Verification:** `GOAL.md`, `PROJECT_PLAN.md`, `UI_FLOW.md`, `README.md`,
`AGENTS.md`, third-party provenance, and this plan now record the same approved
visual direction and authority boundaries.

### Phase 1 — Visual foundation

**Status:** Completed September 1, 2026

- Import approved artwork into PBJ-owned static paths.
- Establish color, type, spacing, radius, shadow, safe-area, and motion tokens.
- Build shared buttons, back controls, cards, inputs, sheets, progress elements,
  and mobile page shell without importing Troy's application state.
- Add source attribution and imported-file provenance.

**Gate:** shared components render consistently at 390×844 and existing route
tests still pass.

**Implemented:**

- Added `app/static/troy-foundation.css` with the approved black/purple tokens,
  system typography, 8-point spacing, buttons, inputs, cards, back controls,
  sheets, progress, safe-area behavior, and reduced-motion support.
- Copied Troy's sandwich logo and four cooking layers byte-for-byte into
  `app/static/brand/` and recorded their upstream checksums and provenance.
- Loaded and precached the foundation and artwork in both PBJ shells and the PWA
  service worker without adding a React runtime.
- Added PBJ-specific foundation contract tests.

**Verification:** 113 PBJ tests pass. At 390×844, the access surface has no
horizontal overflow, the primary button is a 56px black pill with a 17px label,
the input is 56px high with a 14px radius, the cream background is active, and
the browser reports no console warnings or errors. Every new static asset returns
HTTP 200.

**Known gap:** individual PBJ screens still use their existing markup and some
legacy layout selectors. Those are intentionally replaced phase-by-phase starting
with access, home, projects, and settings in Phase 2.

### Phase 2 — Access, home, projects, and settings

**Status:** Completed September 1, 2026

- Apply Troy's visual language to PBJ's private access screen.
- Restyle Home using real PBJ projects, resume behavior, and job status.
- Restyle project listings and settings without fake data or account claims.

**Gate:** access-code sessions, project privacy, resume authority, and destructive
project actions remain correct.

Implemented:

- replaced the legacy wordmark-led access layout with Troy's sandwich mark,
  restrained welcome hierarchy, bottom-anchored real access-code form, and
  preserved seven-day server-validated authorization;
- rebuilt Home around Troy's deliberately minimal mobile composition while
  retaining PBJ's real projects, truthful processing states, canonical New
  Project route, and device-local resume links;
- adapted Projects into Troy's two-column mobile card system using real PBJ
  project metadata and routes, while retaining deliberate confirmation for
  permanent local deletion;
- restyled More and owner-only Connections without importing Troy's account,
  Clerk, billing, mock project, or sign-out behavior;
- retained PBJ's canonical navigation and owner boundary, with black primary
  actions and purple used for active, ready, and operator-accent states.

Verification: the full PBJ suite passes with five Phase 2 facade-boundary tests.
The Access surface also passes a 390×844 browser check with no horizontal
overflow, a loaded sandwich asset, a 56-pixel action, and no console errors.
Route-contract behavior remains unchanged and no Troy Studio or mock state was
introduced.

### Phase 3 — Canonical project creation

**Status:** Completed September 1, 2026

- Restyle Describe, optional References, Footage, and Final Details.
- Preserve resumable supplied-media upload and permission boundaries.
- Use “recipe” only as friendly creative-brief language; internal recipe inference
  remains invisible.

**Gate:** the canonical route sequence and all upload/brief tests pass using real
PBJ data.

Implemented:

- added a shared mobile New Project header, four-step purple progress treatment,
  circular back control, restrained centered hierarchy, and bottom-priority
  black forward actions across all four canonical screens;
- adapted Describe around Troy's recipe-field composition while keeping the
  user-facing language natural and PBJ's internal recipe selection invisible;
- adapted optional References and raw Footage into the supplied-media picker
  treatment without importing presets, stock media, or generated assets;
- preserved real reference limits, private-project language, direct resumable
  upload sessions, the 2 GB batch boundary, sequential mobile upload behavior,
  source inspection, and device ownership checks;
- adapted Final Details with a direction recap and horizontally scrollable
  suggestion chips while keeping the real brief submission contract.

Verification: the complete PBJ suite passes with five additional Phase 3
facade-boundary tests. The canonical Describe → References → Footage → Final
Details route sequence and its existing tests remain unchanged. A live 390×844
walkthrough through Describe, References, and Footage has no horizontal
overflow or browser warnings; forward actions remain 56 pixels, secondary tap
targets are at least 44 pixels, and the mobile upload surface retains its
sequential-worker and 2 GB batch contracts. Final Details is covered through
the real upload-session route tests without creating disposable project media.

### Phase 4 — Preparation and Timeline Ready

**Status:** Completed September 1, 2026

- Apply the cooking presentation to real footage analysis, timeline planning,
  deterministic validation, and handoff preparation.
- Present truthful steps and available progress; never simulate completion.
- Restyle Timeline Ready with one clear Open in Editor action.

**Gate:** interruption, retry, error, and successful handoff states remain truthful
and recoverable.

Implemented:

- adapted optional-reference analysis and full project preparation to Troy's
  sandwich “cooking” composition using the approved layered artwork;
- retained PBJ's real elapsed timer and deterministic status-derived stages for
  footage understanding, story construction/validation, and per-file handoff
  preparation;
- explicitly excluded Troy's fake percentage, fake ETA, rotating placeholder
  narration, simulated completion, cancellation state, and notification mock;
- restyled analysis, timeline, interruption, and export failure presentation
  while preserving the real stored error, technical detail, retry, and creative
  brief recovery paths;
- adapted Timeline Ready to Troy's stamped-card celebration using only real
  project metadata, with one black Open in Editor action and a quiet Back link;
- preserved the validated-timeline prerequisite and canonical OpenReel handoff.

Verification: the complete PBJ suite passes with five additional Phase 4
facade-boundary tests. Existing route-contract tests continue to verify the
three preparation stages, interruption recovery, retired-route redirects, and
OpenReel destination. Live 390×844 checks of real-status timeline planning,
retryable timeline failure, and Timeline Ready have no horizontal overflow or
browser warnings. The failure retains its stored error and both recovery paths;
Timeline Ready exposes exactly one 56-pixel OpenReel action.

### Phase 5 — OpenReel continuity

**Status:** Pending

- Create a visually continuous transition from PBJ into the governed OpenReel
  route.
- Align safe areas and shell-level presentation where compatible.
- Do not import Troy's Studio, timeline, editor tools, or export behavior.

**Gate:** snapshot restore, media hydration, Export & Approve, and OpenReel tool
ownership pass regression testing.

### Phase 6 — iPhone and system QA

**Status:** Pending

- Test representative iPhone viewport sizes, safe areas, keyboard behavior,
  rotation resilience, touch targets, sheets, reduced motion, and accessibility.
- Verify PWA relaunch, interruption recovery, upload behavior, and lifecycle saves.
- Run PBJ tests, route-contract tests, and OpenReel type/build checks.

**Gate:** no critical mobile, accessibility, privacy, route, or integration defect
remains.

### Phase 7 — Acceptance and merge readiness

**Status:** Pending

- Complete user walkthrough and visual acceptance.
- Remove unused imported code and confirm no Troy mock/backend logic remains.
- Finalize provenance, notices, screenshots, and implementation documentation.
- Create a final facelift checkpoint for review before merging into `main`.

**Gate:** the user explicitly approves the facelift and all required checks pass.

## Progress reporting

At the end of each phase, update this document with its status, implemented file
list, verification results, known gaps, and the next phase. Commit and push each
accepted phase to `troy-facelift`; do not merge into `main` until Phase 7.
