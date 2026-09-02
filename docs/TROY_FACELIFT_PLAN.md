# Troy Facelift Implementation Plan

**Branch:** `troy-facelift`
**Status:** Phase 7 reopened September 1, 2026 after visual acceptance failure
**Last updated:** September 1, 2026

## Objective

Implement Troy's reviewed mobile screens with presentation-level fidelity while
preserving PBJ's existing backend, canonical routes, project data, privacy model,
learning system, and governed OpenReel integration. PBJ must use Troy's actual
screen compositions and shared presentation components; applying his tokens to
PBJ's former markup does not satisfy this objective.

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

**Status:** Completed September 1, 2026

- Create a visually continuous transition from PBJ into the governed OpenReel
  route.
- Align safe areas and shell-level presentation where compatible.
- Do not import Troy's Studio, timeline, editor tools, or export behavior.

**Gate:** snapshot restore, media hydration, Export & Approve, and OpenReel tool
ownership pass regression testing.

Implemented:

- added a PBJ-session presentation boundary at OpenReel's application root so
  PBJ's warm cream, white, black, and purple visual system continues into the
  editor without changing standalone OpenReel;
- aligned the compact editor toolbar, editing surface, and bottom tool tray with
  iPhone top, side, and bottom safe areas and set a matching PBJ session browser
  theme color;
- restyled the existing PBJ-governed **Export & Approve** action as the same
  black rounded primary action used throughout the facelift, while leaving
  OpenReel's renderer and PBJ's two explicit confirmations unchanged;
- added a restrained PBJ marker in the editor toolbar without importing Troy's
  Studio, timeline, editor tools, export behavior, state, or services;
- preserved OpenReel ownership of every manual editing operation and PBJ
  ownership of handoff, media permission, snapshots, approval, and learning.

Verification: OpenReel's complete web test suite passes (863 tests, 7 skipped),
including PBJ projection, snapshot lifecycle, media hydration, export receipt,
and compatibility coverage. The production TypeScript/Vite build succeeds. The
complete PBJ suite and Phase 5 boundary tests pass, and the reproducible patch
applies cleanly to the pinned OpenReel revision.

### Phase 6 — iPhone and system QA

**Status:** Completed September 1, 2026

- Test representative iPhone viewport sizes, safe areas, keyboard behavior,
  rotation resilience, touch targets, sheets, reduced motion, and accessibility.
- Verify PWA relaunch, interruption recovery, upload behavior, and lifecycle saves.
- Run PBJ tests, route-contract tests, and OpenReel type/build checks.

**Gate:** no critical mobile, accessibility, privacy, route, or integration defect
remains.

Implemented:

- tested the authenticated PBJ shell at representative iPhone portrait and
  landscape viewports and verified 44–56 pixel primary touch targets, semantic
  navigation, and no portrait horizontal overflow;
- found and fixed a rotation defect where 844×390 crossed into the desktop
  sidebar and desktop OpenReel toolbar; short phone-landscape viewports through
  900×500 now retain the mobile PBJ and OpenReel presentations;
- removed PBJ's portrait-only PWA lock while preserving responsive detection
  without user-agent sniffing, and kept mobile uploads sequential after rotation;
- versioned the changed mobile styles in both HTML shells and the service-worker
  cache so installed PWAs receive the corrected layout instead of a stale asset;
- retained reduced-motion behavior, four-sided safe areas, dynamic viewport
  height, abortable proxy hydration, lifecycle snapshot flush, authority-checked
  Home Screen resume, and the existing accessibility labels and live regions.

Verification: live browser checks pass at 390×844 and 844×390, including a
visual confirmation that rotation keeps the compact header and then-current
navigation presentation. PBJ's complete suite passes 138 tests. OpenReel's complete web suite
passes 863 tests with 7 skipped, and its TypeScript/Vite production build
succeeds. The reproducible patch applies to the pinned OpenReel revision.

Known acceptance boundary: automated and representative browser QA cannot
reproduce a specific physical iPhone's touch hardware, Safari memory pressure,
interruption timing, or Add to Home Screen prompts. Those checks remain the
user's physical-device walkthrough in Phase 7 and are not represented as passed.

### Phase 7 — Acceptance and merge readiness

**Status:** Acceptance candidate prepared September 1, 2026; awaiting explicit
physical-iPhone acceptance and merge approval

- Complete user walkthrough and visual acceptance.
- Remove unused imported code and confirm no Troy mock/backend logic remains.
- Finalize provenance, notices, screenshots, and implementation documentation.
- Create a final facelift checkpoint for review before merging into `main`.

**Gate:** the user explicitly accepts and approves the facelift and all required
checks pass.

Prepared:

- audited every file changed from `main` and confirmed the branch contains no
  tracked project data, media, provider keys, `.env`, evaluation checkout, or
  package installation;
- confirmed runtime code contains no Troy Studio, mock-project, Clerk,
  simulated-rendering, alternate-service, or alternate-backend implementation;
- reconciled the readable OpenReel overlay sources with the tested reproducible
  patch and retained the pinned OpenReel revision and MIT notice;
- finalized Troy permission, source paths, asset checksums, exclusions,
  modifications, and third-party notices;
- reran the complete PBJ and OpenReel suites, production build, clean patch
  application, route/authority gates, and representative phone browser checks;
- recorded the remaining physical-device steps in
  `docs/FACELIFT_ACCEPTANCE.md` without representing them as passed.

Acceptance adjustment requested September 1, 2026:

- removed the shared Home / Projects / More bottom navigation from the rendered
  shell at every viewport size;
- reclaimed its reserved safe-area and sticky-action space while retaining the
  desktop sidebar and each screen's explicit Back and forward actions;
- advanced the PWA shell cache so installed copies receive the removal rather
  than retaining the prior cached navigation.

Merge boundary: the previous candidate is rejected and this branch is not ready
for merge. Do not mark Phase 7 complete or merge `troy-facelift` into `main`
until the faithful-screen remediation passes verification and the owner explicitly
accepts the visual walkthrough and authorizes the merge.

Acceptance failure recorded September 1, 2026:

- the owner rejected the candidate because it visibly adapted Troy's styling to
  PBJ's former screen compositions instead of using Troy's screens faithfully;
- Phase 7 is reopened and the prior candidate is not merge-ready;
- remediation must compare every PBJ-owned user screen against Troy's pinned
  source and 390×844 captures, reuse his exact composition and shared component
  structure wherever a counterpart exists, and connect only PBJ's real state and
  actions;
- PBJ's canonical route order remains authoritative, Troy's Studio remains
  excluded, and unmatched PBJ states must reuse the closest Troy composition
  without creating another visual system.

Faithful-screen remediation in progress September 1, 2026:

- removed the inherited PBJ mobile workspace header, four-step progress rails,
  explanatory hero cards, desktop-like side notes, and recent-project Home feed;
- replaced those adapted layouts with Troy's actual Home, Projects, Recipe,
  Teach It, Upload, Settings, Cooking, and Ready composition classes while
  keeping PBJ's real forms, routes, privacy boundary, jobs, and OpenReel handoff;
- added `app/static/troy-screens.css` as the isolated presentation mapping and
  advanced the PWA cache so installed copies cannot retain the rejected shell;
- verified the corrected Recipe and Home compositions in the iPhone 17 Pro
  simulator and fixed a stale-cache and inherited serif-button defect found
  during that walkthrough;
- PBJ's complete suite passes 143 tests; OpenReel's complete suite passes,
  including 863 web tests with 7 skipped, and the OpenReel production build
  succeeds;
- Phase 7 remains open. Provider-backed analysis and a real-media end-to-end run
  are not included because no user-supplied file has yet been authorized for
  transmission to the configured external providers.

## Progress reporting

At the end of each phase, update this document with its status, implemented file
list, verification results, known gaps, and the next phase. Commit and push each
accepted phase to `troy-facelift`; do not merge into `main` until Phase 7.
