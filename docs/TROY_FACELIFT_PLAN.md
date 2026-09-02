# Troy Facelift Plan

**Source:** `Swag420Money/PB-J` commit `10c8efdf2f2187604a934d082d038db8729a75d9`
**Scope:** Presentation only
**Status:** Implemented foundation; final physical-iPhone acceptance remains open

## Goal

Use Troy's actual iPhone-first screen compositions, visual hierarchy, controls, spacing, black-and-purple balance, restrained motion, and approved sandwich artwork while retaining PBJ's real backend, routes, privacy, media, jobs, and learning system.

Do not import Troy's Studio, Clerk authentication, mock projects, application state, simulated renderer, alternate services, or backend logic. PBJ has no manual editing Studio. Its terminal creative screen is the rendered rough-cut review.

## Canonical screen mapping

| Troy presentation | PBJ route/state |
|---|---|
| Access composition | `/access` |
| Home | `/` |
| Projects | `/projects` |
| New project prompt | `/projects/new` |
| Teach It / references | `/projects/new/references` |
| Upload footage | `/projects/new/footage` |
| Final details | `/projects/{id}/brief` |
| Cooking | `/projects/{id}/production-progress` |
| Ready | `/projects/{id}/ready`, with the real rendered video and approval/revision actions |
| Settings | `/settings` |
| Studio | Excluded |

## Visual contract

- Warm cream-to-white background.
- Black primary actions and restrained purple active/progress accents.
- Troy's typography scale, generous spacing, rounded cards, and tactile controls.
- One clear primary action per sequential screen.
- iPhone safe areas, dynamic viewport units, minimum 44-pixel targets, and reduced-motion support.
- Desktop expands the same composition rather than creating a separate desktop product.
- No persistent bottom navigation bar.

## Seven phases

### Phase 1 — Source inventory and tokens

Pin the source commit, record permission/provenance, inventory screens/assets, and establish Troy-derived tokens without importing application logic. **Successful.**

### Phase 2 — Shared shell

Implement typography, background, buttons, inputs, cards, safe areas, and restrained motion. **Successful.**

### Phase 3 — Entry and project creation

Translate Access, Home, Projects, Describe, References, Footage, and Final Details into PBJ-native templates wired to real routes and forms. **Successful.**

### Phase 4 — Cooking and rough-cut review

Use Troy's Cooking and Ready compositions with PBJ's truthful analysis, planning/validation, FFmpeg rendering, playable MP4, explicit approval, and request-changes states. Never simulate progress or output. **Implemented; end-to-end supplied-media acceptance remains required.**

### Phase 5 — Secondary screens

Translate Settings, More, Recipe Lab, and owner/operator screens without exposing machinery in the normal project journey. **Successful.**

### Phase 6 — Responsive and accessibility hardening

Verify portrait, short landscape, safe areas, keyboard focus, reduced motion, upload concurrency, failure recovery, and media playback. **Browser-validated; physical-iPhone acceptance remains open.**

### Phase 7 — Final acceptance

Run the complete automated suite, launch PBJ without external editor dependencies, complete a real supplied-media project, request one revision, approve the result, download it, and verify portrait/landscape behavior on a physical iPhone. **Awaiting explicit owner acceptance. Do not mark complete until the owner accepts the physical-iPhone result.**

## Acceptance gates

- Troy's screen compositions are recognizable rather than merely token-inspired.
- PBJ uses only real routes, project records, media, progress, errors, and renders.
- No Troy Studio, Clerk, fake data, mock backend, or simulated rendering exists in runtime code.
- No OpenReel dependency, route, documentation, or launcher process exists.
- The rough-cut review plays the latest real MP4 and separates rendering success from approval.
- Request Changes creates a new validated timeline and rendered version.
- The complete PBJ test suite passes.
- Physical-iPhone portrait, landscape, playback, upload, interruption, and revision acceptance passes.
