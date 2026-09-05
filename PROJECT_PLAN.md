# PB&J Product and Implementation Plan

**Status:** Recipe Engine v1 — automatic FFmpeg rough cuts
**Last updated:** September 3, 2026
**Source of truth:** This document governs product scope, architecture, learning behavior, and implementation priorities.

## 1. Product goal

PB&J lets a user describe the video they want, optionally provide finished reference videos, upload their own raw footage, and receive a useful rendered first cut that reflects the requested direction. The user watches the result, approves it, or requests changes in natural language.

> AI creates the first cut. The user directs revisions. PBJ learns from approved outcomes so future first cuts require less correction.

PBJ is not a recipe marketplace, a manual nonlinear editor, or a generative-media product.

## 2. Product model

- Finished reference videos provide observable style evidence.
- Internal recipes encode evidence-backed editing principles.
- Raw footage and permissioned uploaded audio are the available ingredients.
- Twelve Labs records timestamped semantic observations.
- OpenAI synthesizes recipes and proposes project-specific editorial decisions.
- The canonical timeline is the structured, validated edit decision package.
- FFmpeg deterministically renders the validated timeline from original project media.
- The exported MP4 is the reviewable cut.

Provider analysis is not itself a recipe. Twelve Labs is the sole supported analyzer; there is no analyzer selector or alternate fallback path. OpenAI never emits executable shell commands. FFmpeg never decides what is creative or important.

## 3. Canonical user journey

1. Describe the desired video in natural language.
2. Optionally upload one or more finished reference videos.
3. Upload raw footage PBJ may use.
4. Confirm the brief and target duration.
5. PBJ analyzes, plans, validates, repairs when necessary, and renders.
6. Watch the completed MP4.
7. Approve it or request specific changes.
8. A revision reuses matching cached analysis, creates a new timeline version, and renders a new MP4.

Recipes remain invisible. Provider choice is an internal concern. The normal user never starts from an empty timeline and never receives a manual timeline editor.

## 4. Implemented foundation

The repository contains the complete proven technical chain:

- finished-reference upload and separate analysis;
- separate analysis of each raw file;
- an optional read-only, timestamped footage-analysis viewer plus a downloadable project analysis package;
- provider-neutral normalized evidence and combined content maps;
- checksum/purpose/provider/model/prompt/permission-aware analysis reuse;
- evidence-backed recipe synthesis, immutable approved versions, and pinned project snapshots;
- deterministic recipe-evidence validation plus at most two Learning Agent citation-repair attempts that reuse completed analysis;
- prompt interpretation, invisible recipe matching, and approved-example retrieval;
- structured rough-cut planning with exact source identifiers and timestamp ranges;
- deterministic source ownership, range, duration, continuity, transition, and media-policy validation;
- recipe-evidence segment labels repaired only when the cited reference and timestamp interval identify exactly one analyzer segment, with the repair recorded;
- unique-only source-name repair and at most two bounded Timeline Repair Agent attempts;
- canonical timeline creation and versioned AI revisions;
- FFmpeg H.264/AAC rendering from original project assets;
- output inspection, structural QA, hashes, render receipts, and frozen timeline snapshots;
- separate explicit approval and initial-to-approved learning evidence;
- project-private feedback, recipe candidates, contradictions, thresholds, and rollback;
- Troy's iPhone-first presentation wired to PBJ's real routes and state.
- privacy-safe client diagnostics for upload, connectivity, visibility, and browser failures, with owner-only export and structured Render log output.

OpenReel and the former PBJ manual editor are removed. The retired direct timeline, editor-asset, proxy, proposal, transaction/undo, and API-export surfaces are removed as well. Timeline persistence remains internal to automatic planning, prompt-driven revisions, approval, and rendering.

## 5. Agent boundaries

### Editing Agent

Consumes the project brief, approved recipe snapshot, normalized content map, scoped learning signals, and relevant approved examples. Returns a schema-valid edit proposal only.

### Timeline Repair Agent

Receives the proposed plan plus a concrete deterministic validation failure. It makes the smallest correction and gets at most two attempts.

### Learning Agent

Classifies approved-outcome and feedback evidence into project, preference, recipe, or platform candidates. During reference synthesis, it may also repair invalid evidence citations after receiving the exact deterministic failure, with at most two attempts and no repeated media analysis. It cannot approve, promote, or rewrite shared knowledge.

All roles currently default to `gpt-5.6-luna` with medium reasoning and retain separate role, prompt, model, response, and usage provenance.

## 6. Rendering and review contract

- Rendering begins only after a populated timeline passes deterministic validation.
- The compiler accepts allowlisted timeline operations rather than raw model commands.
- Outputs use project originals only; proxies are never render inputs.
- The current output target is 1080×1920 H.264 video with AAC audio.
- Every render freezes the exact timeline, records source and command hashes, verifies media properties, and retains a QA report.
- A successful render is not automatically approved.
- The review screen must play the latest completed MP4 and expose one primary approval action plus a clear request-changes path.
- Approval applies only to the latest completed render and requires explicit confirmation.
- Revision feedback creates a new timeline and render version while retaining the initial baseline and prior artifacts.
- Completed renders remain visible as numbered cuts, each with its own playback page; only the newest cut exposes the active approval and revision journey.

## 7. Learning policy

- Every reference, recipe version, project, proposal, repair, render, revision, rating, and approval is scoped evidence.
- Immediate project feedback is reversible and project-specific.
- A single project cannot directly rewrite a shared recipe.
- Shared promotion requires repeated cross-project support and preserves contradictions.
- Only a successful explicitly approved output is positive outcome evidence.
- Failed renders and intermediate versions remain audit context, not positive learning.
- Approved examples remain permission-scoped and retain timeline, diff, receipt, recipe, prompt, and model provenance.
- Custom model training is deferred until measurement proves general models are the limiting factor and sufficient permissioned data exists.

## 8. Privacy and media policy

- Use only media supplied and permissioned for the project.
- Do not generate or fetch video, images, voices, music, sound effects, or B-roll.
- Original recorded audio and permissioned uploaded audio are allowed. Recipe Engine v1 currently uses audio embedded in uploaded source video; a separate audio-upload control is not part of the canonical flow.
- Project-private reference recipes and learning stay isolated to their device until account-level consent exists.
- Cache reuse never grants access across permission boundaries.
- Shared Recipe Lab governance requires owner authority and explicit contribution consent.
- Client diagnostics use a strict allowlist, bounded values, rotation and rate limits; they exclude filenames, media, prompts, access codes, secrets, and raw exception messages.
- The hosted checkpoint fails startup on a missing access code, a default/short session secret, or non-secure cookies. Access and owner codes match exactly with constant-time comparison; public login bodies are rejected above 1 KiB before form parsing, and a bounded in-process failure limiter slows guessing without retaining or logging raw client addresses or submitted codes. Cookie-held project drafts have character and full serialized-session limits that keep accepted cookies below 4 KiB.
- Hosted state-changing browser requests require same-origin metadata in addition to `SameSite=Lax`; beginning a distinct project is a protected POST, while opening the describe page cannot clear an existing draft. Responses carry restrictive framing, content-type, referrer, permission, transport, and cache headers, including privacy-safe unhandled errors. Render's platform marker forces hosted validation even if an application flag drifts. Logout clears authorization and owner state. Rotating the signing secret globally invalidates stateless demo sessions.
- Before broader beta: add durable jobs, authenticated per-user isolation, controlled object storage, encryption, deletion/retention controls, distributed rate limits, server-side revocation, and audit-ready authorization.

In local mode, project-private reference recipes and learning stay isolated to their originating device. The hosted-demo configuration is intentionally narrower than the broader beta: one access-code-protected workspace is shared across its authorized browsers. Its 1 CPU / 2 GB RAM web service still uses ephemeral storage, so every upload and result is disposable and may disappear after a restart or deploy. It runs one web process and uses the existing in-process jobs. It is suitable for controlled testing, not important media, simultaneous users, or public distribution.

The disposable demo uses manual Render controls. The owner resumes the paid PBJ service in the Render Dashboard before a demonstration and suspends it after confirming that uploads, analysis, rendering, exports, and deletions have finished. PBJ has no launcher, idle timer, browser activity heartbeat, or Render API credential. Manual suspension can still interrupt in-process work and discard `/tmp` state.

## 9. iPhone-first private-beta UX

- Troy's approved presentation is the visual baseline.
- Use a warm cream-to-white canvas, black primary actions, purple selected/progress states, generous spacing, and plain language.
- Desktop expands the same flow rather than becoming a separate product.
- Prefer responsive layout and input capability over user-agent sniffing.
- Keep the shared shell free of persistent bottom navigation.
- Support safe areas, dynamic viewport changes, reduced motion, resumable uploads, truthful progress, retryable failure states, and network-required Home Screen behavior. Offline caching is intentionally absent.
- Private beta may use an exact, server-validated access code remembered for seven days in a secure session and must offer logout.

## 10. Delivery stages

### Stage 1 — Recipe Engine v1

Validate evidence-backed recipes, versions, prompt inference, retrieval, and conservative learning.

### Stage 2 — Automatic first-cut loop

Operate Twelve Labs analysis, OpenAI planning, validation/repair, FFmpeg rendering, video review, explicit approval, and prompt-driven revisions as one canonical flow.

### Stage 3 — Measurement

Measure first-cut approval, selected-source retention, duration retention, opening/ending retention, revision count, time to approval, instruction compliance, failures, cost, and latency.

### Stage 4 — Hosted private beta

Add durable jobs, cloud storage, authentication/authorization, consent, deletion, recovery, observability, and push notifications. Test on physical iPhones.

The first Stage 4 checkpoint uses a Render web service with an access code, generated secure session secret, HTTPS-only cookies, Dockerized FFmpeg, and explicitly disposable storage. After free-tier rendering exhausted the 512 MB memory ceiling, the service was vertically scaled to 1 CPU / 2 GB RAM. A later 14-source phone-footage test proved that a single complex FFmpeg graph could still create a sub-minute memory spike, so hosted renders now bound decoder, filter, and encoder concurrency while preserving the normal CRF 20/medium quality profile. A controlled 15-video/60-second acceptance then completed in 325.265 seconds with no restart or 5xx, but it reached 100% CPU. The original 60-second memory sample showed 89.888%; a later 30-second query captured 2,064,965,600 of 2,147,483,600 bytes, or 96.157%, leaving about 78.7 MiB. Treat that as a pass only for the measured disposable-demo envelope; larger workloads require a measured lower-memory render design or more capacity. The worktree bounds hung FFmpeg work with a 600-second floor and a 9x-output-duration slope. Repository checks gate Blueprint deploys and the service uses Render's maximum 300-second shutdown window; that window reduces avoidable interruption but does not make response-bound work durable. FFprobe and FFmpeg work remain off the web event loop. The retired proxy pipeline is gone, and canonical renders read original project media directly. Attach persistent storage before retaining real projects. Durable workers, object storage, accounts, and multi-user isolation remain later gates.

### Stage 5 — Public readiness

Proceed only after useful first cuts are consistent, privacy/security gates pass, and learning improves results without compromising user control.

## 11. Verification gates

### Planning

- Natural-language prompts infer useful recipe knowledge without visible selection.
- Every selected range belongs to a project-owned analyzed source.
- Revisions reuse eligible analysis and retain complete provenance.
- Invalid or ambiguous model output fails safely after bounded repair.

### Output

- A new project automatically reaches a playable MP4.
- The MP4 uses only supplied originals and allowed audio.
- Duration, codecs, resolution, source ranges, transitions, audio, and transforms pass deterministic checks.
- Render failures remain retryable without losing footage or completed analysis.

### Review and learning

- A user can watch, approve, download, or request changes on iPhone and desktop.
- Approval cannot occur before a successful render or without confirmation.
- Revision creates a genuinely new version and preserves the initial timeline.
- Only the approved version creates positive project evidence.
- Project feedback does not silently mutate shared recipes.

## 12. Explicitly out of scope

- OpenReel or another external manual editor;
- a PBJ-owned timeline editing interface;
- move, trim, split, crop, or other manual editing controls;
- analyzer selection or A/B comparison in the normal product;
- alternate media analyzers or silent analyzer fallback;
- recipe marketplace or public recipe catalog;
- generated media or fetched stock media;
- automatic publication of learned shared rules;
- social publishing, collaboration, and advanced professional NLE features;
- public launch before private-beta safeguards and quality gates pass.

## 13. Immediate next actions

1. Keep the `codex/hosted-demo` Blueprint aligned with the live 1 CPU / 2 GB Render web service and use only disposable sample footage.
2. Run a complete supplied-media walkthrough against the hosted URL and verify that FFmpeg finishes without a memory restart.
3. Verify access-code protection and physical-iPhone playback, then attach persistent storage before testing persistence or important projects.
4. Complete durable job and object-storage architecture before inviting multiple users.
5. Measure quality and revision burden across representative projects.

## Final product position

PBJ creates self-improving, evidence-backed rough cuts. Twelve Labs understands supplied video, OpenAI proposes structured editorial decisions, deterministic application code validates them, FFmpeg renders them, and the user directs improvement through approval or natural-language revision.
