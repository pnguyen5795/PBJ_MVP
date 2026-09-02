# PB&J Third-Party Notices

This file records third-party software reviewed or used by PB&J. Source-review
provenance is tracked in `docs/third_party_sources.json`.

## Retired PBJ frontend dependencies

| Package | Purpose | License |
|---|---|---|
| React | Retired timeline user-interface runtime | MIT |
| React DOM | Browser rendering for React | MIT |
| Vite | Frontend development and production bundling | MIT |
| @vitejs/plugin-react | React integration for Vite | MIT |
| TypeScript | Static type checking | Apache-2.0 |
| @types/react | React type definitions | MIT |
| @types/react-dom | React DOM type definitions | MIT |

The old PBJ frontend and its package installation were removed on August 30,
2026. These entries remain only as historical notice records.

## Reviewed editor sources

PB&J reviewed several open-source video editors and media tools while designing
its timeline architecture. Exact reviewed revisions and their current reuse
status are recorded in `docs/third_party_sources.json`. Any adapted files,
original revision, license, modifications, and required notices must be recorded
before integration.

## Troy PB&J frontend visual source

The PBJ owner confirmed permission on September 1, 2026 to use and modify the
code, design, and artwork in `https://github.com/Swag420Money/PB-J.git` at
revision `10c8efdf2f2187604a934d082d038db8729a75d9`. The source repository does
not contain a license file. The approved use is limited to the visual adaptation
described in `docs/TROY_FACELIFT_PLAN.md`. PBJ translated the reviewed visual
tokens and shared-control patterns into `app/static/troy-foundation.css` and
copied the approved sandwich logo and four sandwich layers into
`app/static/brand/`. Exact upstream paths, checksums, PBJ paths, exclusions, and
modifications are recorded in `docs/third_party_sources.json`. No Troy Studio,
application state, mock project, Clerk authentication, simulated renderer,
alternate service, or backend code was imported.
