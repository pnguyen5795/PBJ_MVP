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

## OpenReel integration overlay

PBJ's read-only project loader is adapted against OpenReel Video revision
`5f3c85e5fc223c86060bf4b12e1b4dec58e9b8a9`, licensed under MIT. The exact
upstream and PBJ paths and modification summary are recorded in
`docs/third_party_sources.json`. This adapter loads PBJ project data through
OpenReel's existing project store; it does not recreate OpenReel editing features.
The complete MIT notice is preserved in
`integrations/openreel/LICENSE.openreel`. The reproducible PBJ modifications are
stored in `integrations/openreel/openreel-pbj.patch` and are applied to the
pinned source revision by `scripts/setup_openreel.command`.
