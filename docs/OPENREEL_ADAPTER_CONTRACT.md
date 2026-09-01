# PBJ ↔ OpenReel Adapter Contract

**Status:** Gate B live handoff, whole-project snapshot saving, latest-snapshot restore, and browser walkthrough verified
**Pinned OpenReel revision:** `5f3c85e5fc223c86060bf4b12e1b4dec58e9b8a9`

The local `start_app.command` starts PBJ and this pinned OpenReel host together,
waits for both readiness endpoints, opens PBJ, and owns their shared shutdown.

## Product boundary

PBJ prepares the first timeline from the brief, references, raw footage, and its internal recipe system. It then opens that project in OpenReel. From that point through the editing session, OpenReel owns the editor, project state, playback, manual editing tools, and undo/redo history.

PBJ does not recreate or individually bridge OpenReel's move, trim, split, crop, reorder, speed, volume, effects, or other approved editing tools. A feature that OpenReel already implements remains an OpenReel feature.

The integration has two primary data movements:

1. **Initial handoff:** PBJ projects its validated first timeline into one OpenReel `Project`.
2. **Snapshot save:** after OpenReel project-store changes, the adapter saves a debounced copy of the complete OpenReel project back to PBJ.

There is no per-tool PBJ transaction requirement. OpenReel edits do not continuously rewrite PBJ's source first-timeline record.

## Ownership

| Concern | Owner |
| --- | --- |
| Brief, references, raw-media permissions, recipes, initial AI timeline | PBJ |
| Editing UI, playback, manual tool behavior, live project state, undo/redo | OpenReel |
| Initial PBJ-to-OpenReel mapping | Adapter |
| Whole-project autosave and restore record | PBJ snapshot boundary |
| Approval evidence, provenance, privacy, learning governance | PBJ |
| Final export orchestration | OpenReel standard H.264 MP4 renderer behind PBJ intent, receipt, and approval gates |

## Initial handoff

`GET /api/projects/{project_id}/openreel/project` returns schema `pbj-openreel-project-v1` with stable identities, project settings, timeline state, source timeline revision and hash, PBJ preview URLs, and snapshot endpoints.

The pinned OpenReel app opts in with `?pbjProject={project_id}` and loads the returned project through OpenReel's existing project store. On reopen, the same endpoint returns the latest valid snapshot when its project identity, source revision/hash, and media set still match. Otherwise it safely returns the original first-timeline projection. `authority.loadedFrom` identifies which state was loaded. PBJ's separate linked original-audio row is not projected because OpenReel plays the source video's audio with its video clip.

## Snapshot save

`POST /api/projects/{project_id}/openreel/snapshots` accepts schema `pbj-openreel-snapshot-v1` containing the complete serializable OpenReel project plus its source PBJ revision, hash, and project identity.

The browser bridge removes transient browser-only values such as blobs, file handles, waveform buffers, and `blob:` URLs. PBJ rejects stale source identities and snapshots containing media IDs that were not admitted to that PBJ project. Each accepted snapshot is immutable, and PBJ also maintains a latest pointer. `GET /api/projects/{project_id}/openreel/snapshots/latest` returns the newest saved record.

Snapshots are working-state evidence, not positive learning examples. The initial PBJ timeline remains unchanged while the user edits in OpenReel. OpenReel's own undo/redo stays local to its project store and requires no PBJ endpoint.

When `pbjProject` is present, PBJ's validated latest snapshot is the recovery
source. OpenReel's standalone local-recovery dialog is suppressed for that
session so two restore systems cannot compete. Standalone OpenReel use keeps
its native recovery behavior.

## Media and feature guardrails

- OpenReel may operate only on media already admitted to the PBJ project.
- Generated, remotely fetched, or otherwise unpermissioned media features remain disabled until they pass through a future PBJ intake flow.
- OpenReel code stays isolated behind the adapter overlay, pinned source revision, notices, and provenance record.
- PBJ-specific integration code must not alter the internal implementation of each editing tool.
- An adopted OpenReel feature must survive snapshot serialization, restore, validation, and the eventual export path before PBJ calls it supported.

## Export & Approve boundary

The export-intent gate is implemented. `POST /api/projects/{project_id}/openreel/exports` requires deliberate approval confirmation and the latest saved snapshot. PBJ rejects stale source identities, empty projects, non-finite or invalid clip ranges, and media outside the PBJ project. An accepted request freezes the complete snapshot, records its canonical SHA-256, and stores schema `pbj-openreel-export-v1`, the exact snapshot ID, source revision/hash, referenced media, and the split ownership: OpenReel renders; PBJ approves.

Render completion receipt validation is implemented at `POST /api/projects/{project_id}/openreel/exports/{export_id}/complete`. The endpoint accepts only schema `pbj-openreel-render-receipt-v1`, verifies that the receipt matches the frozen snapshot, rechecks snapshot integrity, requires an identified OpenReel source revision, a nonempty delivered MP4 with a valid SHA-256, and passed render, output, project, and snapshot checks. The request carries metadata only; PBJ does not proxy the rendered video body. Identical retries are idempotent. A valid receipt moves the export to `render_complete_pending_approval` and cannot itself approve the project or create positive learning evidence.

The backend final-approval gate is implemented at `POST /api/projects/{project_id}/openreel/exports/{export_id}/approve`. It accepts only an export in `render_complete_pending_approval`, requires deliberate post-render confirmation and the exact rendered-output SHA-256, and is idempotent after success. Approval stores the frozen OpenReel project as the final state, compares it with PBJ's projected initial OpenReel project, records one device-private approved example and one governed style-candidate signal per project, asks the Learning Agent for advisory classification, and never promotes a recipe automatically. The current implementation measures whole-project clip retention, additions, removals, changed clip decisions, duration change, and time to approval; it does not reconstruct OpenReel actions as retired PBJ commands.

The user-facing Export & Approve path is connected in the pinned OpenReel evaluation app. A PBJ editing session replaces the primary export label with **Export & Approve**, requires confirmation before rendering, saves and freezes the complete project, and uses OpenReel's existing standard H.264 MP4 renderer. The output still streams directly to the user's selected destination. In parallel, an on-device OPFS mirror preserves random-access muxer writes; PBJ hashes that mirror incrementally without loading the full video into memory, submits the metadata-only receipt, then deletes the mirror. A separate post-render confirmation is required before the approval endpoint is called. Declining it leaves the saved render pending approval. Standalone OpenReel projects retain their native export interface.

The code path, automated contract tests, and complete supplied-media walkthrough are implemented. PBJ hydrates permitted media URLs into browser blobs when loading the project because OpenReel's existing renderer consumes blobs. The August 30, 2026 walkthrough verified live playback, a playable 1080×1920 H.264/AAC MP4 download, receipt persistence, deliberate approval, approved-example creation, and governed learning evidence. PBJ must not silently flatten unsupported OpenReel state into its retired editor command model.

Representative tool compatibility is tracked in `OPENREEL_COMPATIBILITY_MATRIX.md`. The first native trim test passed snapshot save, reopen restore, final-output parity, receipt, reapproval, and single-project learning deduplication.

## Gate B acceptance

Gate B is complete when:

1. a real PBJ first timeline loads into the pinned OpenReel editor;
2. OpenReel's existing editing tools and undo/redo remain OpenReel-owned;
3. arbitrary project-store changes produce one debounced whole-project snapshot save;
4. snapshot storage preserves the complete serializable project and source identity;
5. unpermissioned media is rejected;
6. no per-feature action bridge or PBJ-owned editing interface is introduced; and
7. the overlay, tests, pinned revision, license, and provenance remain reproducible.

## Next gate

Measure initial-to-approved improvement and verify representative OpenReel features on iPhone-sized touch surfaces against snapshot restore and final output. This is compatibility testing of one project format—not separate PBJ implementations of every editor tool.
