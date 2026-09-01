# PB&J Product and Implementation Plan

**Status:** Recipe Engine v1 — PBJ timeline preparation retained; former PBJ editor removed
**Last updated:** August 30, 2026
**Source of truth:** This document governs product scope, architecture, learning behavior, and implementation priorities.

## 1. Product goal

PB&J should let a user describe the video they want, optionally provide finished reference videos, upload their own raw footage, and receive a useful, prefilled first-cut timeline that reflects the requested editing direction. The normal workflow must not begin with an empty timeline.

The product must make this feel simple. Users communicate in natural language; the application handles style inference, recipe retrieval or creation, footage understanding, timeline planning, validation, preview preparation, and final export in the background.

The North Star is:

> AI creates the first timeline. The user refines it. PB&J learns from the difference so future first timelines require less work.

The long-term product question is:

> Can PB&J consistently infer the editing approach requested by a user, understand the user's supplied footage, and produce a strong first timeline that requires progressively less correction through controlled evidence and feedback?

## 2. Correct product model

The spaghetti analogy defines the system:

- finished spaghetti dishes = finished reference videos;
- recipe = an internal representation of editing style;
- ingredients = raw footage plus permissioned user-supplied audio;
- Twelve Labs or Gemini = the food analyst that records observable evidence;
- OpenAI = the chef and planner that infers recipes and creates project-specific assembly decisions;
- canonical timeline = the assembled decision package before final cooking;
- OpenReel = the planned external interaction surface governed through PBJ's adapter;
- FFmpeg = kitchen equipment that inspects ingredients, prepares separate proxies, and cooks the final approved dish;
- exported MP4 = the finished spaghetti.

Video analyzers provide timestamped observations. OpenAI compares those observations to infer reusable editing principles. For a project, OpenAI combines internal recipe knowledge, user preferences, and project instructions into a structured timeline. Application code owns the authoritative timeline, validates every operation, and compiles the approved snapshot into controlled FFmpeg operations only at export.

FFmpeg does not make creative decisions, and provider analysis alone is not the recipe. Before export, FFmpeg may create separate proxies, thumbnails, waveforms, and metadata, but it must not combine the project into a first-cut video.

## 3. User experience and invisible recipes

The approved target user journey is:

1. Describe the desired video in ordinary language.
2. Optionally upload finished reference videos.
3. Upload raw footage.
4. Receive a validated populated timeline package created by PBJ.
5. After the governed OpenReel handoff is live, refine it in OpenReel while PBJ saves complete project snapshots.
6. After integration, select Export & Approve to render and accept the result.

Recipes are internal infrastructure. Users do not browse, purchase, manage, or select recipes. There is no recipe marketplace.

When a prompt matches known editing knowledge, the system should retrieve the strongest relevant recipe or compatible recipe traits. It may blend compatible traits when needed. When confidence is insufficient, optional reference videos can support a new private draft recipe. An internal operator may review recipe evidence and versions, but that machinery stays outside the normal creative workflow.

## 4. Implemented foundation and current gap

The earlier feasibility work established the complete technical chain, and that chain is now the foundation of Recipe Engine v1:

- finished reference videos can be uploaded and analyzed;
- multiple raw files can be analyzed separately and combined into a content map;
- provider-specific analysis can be normalized;
- OpenAI can synthesize an evidence-backed recipe and create a structured edit plan;
- invalid source ranges and timeline instructions can be validated or repaired;
- FFmpeg can render a playable 1080×1920 H.264/AAC rough cut;
- revisions can reuse cached video analysis and create new plans and renders;
- approved projects, revision history, feedback, and plan provenance can be retained locally.

The active question is no longer basic feasibility or whether an editable timeline can be produced. It is whether governed learning, retrieval, recipe versions, and timeline feedback can produce consistently stronger first timelines across users and editing directions.

Recipe Engine v1 foundation implemented on August 26, 2026:

- uniform evidence-backed recipe rules with classifications, recurrence, conditions, exceptions, conflicts, renderer support, confidence, and timestamp provenance;
- local rejection of invented evidence or inconsistent reference counts;
- draft recipe versions and immutable validated version files;
- exact recipe snapshots pinned into new projects and edit plans;
- every reference upload and synthesis, raw-footage project, completed cut, recipe correction, recipe approval, project revision, rating, and approved project recorded as a scoped learning signal; signals inform future planning immediately, while shared recipe promotion remains versioned and evidence-weighted;
- one shared checksum-addressed copy of identical reference media.
- recipe evidence that cites the correct analyzer segment is safely clamped to that segment's real boundaries, while unknown files or segments remain hard failures;
- every rough-cut run now stores deterministic source-time decision records and a semantic plan diff against the preceding run;
- every completed render now stores a canonical receipt containing plan, compiled-command, source, output, renderer-version, verification, and media-policy provenance;
- rendered outputs now pass fail-closed structural scanning for black intervals and frozen video, while long silence is retained as non-blocking evidence because original recorded pauses may be intentional;
- approved examples now retain their decision, diff, receipt, plan, recipe, and feedback artifacts for later retrieval and recipe-version evaluation;
- every completed first cut and revision now records compact run evidence in the learning stream, including change summaries, selected-source coverage, hashes, QA outcomes, feedback, and exact artifact paths; these technical/context events are retrieval evidence but cannot independently count as stylistic support or promote a recipe overlay;
- successful analysis is reusable across identical source checksums only when purpose, provider, model, analysis-prompt version, and permission boundary match; cache hits create no new provider-cost estimate and do not duplicate remote-asset ownership;
- shared Recipe Lab candidates require an explicit authorized-contribution confirmation, while shared revision, validation, archival, and other governance actions require owner access; project-private recipes and project-derived learning remain device-isolated;
- the old in-app analyzer switch, manual rough-cut action, and A/B comparison endpoints are removed so the product has one canonical prompt-first path.

The first auditable implementations of prompt interpretation, invisible approved-recipe matching, approved-example retrieval, conservative feedback classification, and first-cut outcome measurement were added on August 26, 2026. Matching and classification are deliberately deterministic and conservative at this stage. Automatic trait blending, account-level preference confirmation, recipe-version replay, and aggregate performance reporting remain subsequent Recipe Engine milestones.

The Editing Agent boundary now repairs model-provided source identifiers only
when they resolve to one unique project-owned file (including the single-source
case), and records the alias repair in the plan. When exactly one analyzer
segment exists, an empty model shortlist retains that sole candidate with a
warning. Ambiguous or foreign source identifiers remain rejected.

The implemented application follows the preparation-only contract in `UI_FLOW.md` and ends at Timeline Ready. The former PBJ editor was removed on August 30, 2026; historical Review, Revision, and Approval routes are compatibility redirects only.

The OpenAI decision layer is implemented as three bounded, auditable roles behind one Responses API gateway:

- **Editing Agent:** selects footage, creates the first populated timeline, and proposes reversible typed revisions from the original assets and cached analysis;
- **Timeline Repair Agent:** receives an exact validation failure and makes the smallest possible correction, with at most two attempts before a truthful failure;
- **Learning Agent:** synthesizes reference-backed recipes and classifies revision and successful-approval evidence into project, preference, recipe, or platform candidates without directly promoting shared knowledge.

All three roles currently use `gpt-5.6-luna` at medium reasoning. Every call records role version, model, reasoning effort, response ID, prompt version, and usage. Model choice remains independently configurable per role for later evaluation. Agents never render, approve, mutate shared recipes, reanalyze unchanged footage, or bypass deterministic application validation.

## 5. Delivery strategy

### Stage 1 — Recipe Engine v1

Build an evidence-backed internal recipe system that can become stronger as it sees more representative reference videos and reviewed project outcomes.

The immediate milestone is one recipe that:

- is inferred from several representative references;
- distinguishes repeated patterns from one-off choices;
- links important rules to source evidence and timestamps;
- is versioned and explicitly approved;
- is tested across multiple compatible raw-footage projects;
- produces measurably better first cuts as it is revised.

### Stage 2 — PBJ-to-OpenReel handoff (implemented; compatibility hardening continues)

Create a validated first timeline and project it into OpenReel while preserving PBJ's media, permission, approval, and learning boundaries.

Implemented Gate B foundation: PBJ exposes an OpenReel-compatible project projection with stable IDs, timing provenance, proxy URLs, revision, and timeline hash. The pinned OpenReel evaluation app can opt in with `?pbjProject={project_id}` and loads that projection through OpenReel's existing `loadProject` store method. A store-level bridge saves the complete serializable OpenReel project after debounced changes. PBJ keeps immutable snapshots and a latest pointer without mutating the source first timeline. Reopening automatically restores the latest snapshot when its source identity and media permissions still match, otherwise it safely falls back to the first timeline. The local launcher starts both PBJ and the pinned OpenReel host, waits for readiness, and shuts them down as one process group.

The first full browser walkthrough passed on August 30, 2026: Timeline Ready opened a real supplied clip in OpenReel, an OpenReel project change produced an accepted whole-project snapshot, and reopening restored that changed project. The walkthrough also added fractional media-frame-rate parsing and suppressed OpenReel's standalone recovery prompt during PBJ sessions.

Representative compatibility testing began on August 30, 2026. OpenReel's native **Trim end to playhead** operation shortened a supplied clip from 18.87 seconds to 10.00 seconds; PBJ saved and restored the complete changed project, and the restored project rendered a playable 10.07-second H.264/AAC MP4. The ongoing matrix is recorded in `docs/OPENREEL_COMPATIBILITY_MATRIX.md`.

The next representative test used OpenReel's native **Split** operation at 5.00 seconds. PBJ restored both resulting clips after reopen, the final MP4 retained the expected 10.07-second duration with video and audio, and the learning comparison recorded one retained clip, one added clip, and one changed clip.

Native **Ripple delete** and inspector transform tests also passed. Ripple delete removed the second split, restored a five-second project, and produced a playable 5.08-second H.264/AAC MP4. A subsequent 80-pixel horizontal position transform restored exactly and appeared visibly in the rendered output. These remain OpenReel behaviors stored as complete projects, not PBJ-owned editor commands.

Native crop, speed, and volume tests now pass as well. A square crop on portrait media exposed an upstream normalized-aspect bug, which the pinned adaptation corrects by calculating crop presets in source pixel space; the crop restores and appears in final output. The 2× speed preset restored a 2.50-second timeline and rendered a 2.58-second MP4. A 50% volume setting restored as `0.5`, retained AAC audio, and measurably reduced output level relative to the 100% reference.

Timeline move now passes the same boundary: a clip shifted from 0 to 1.0 seconds restored exactly, and the 3.58-second output contained the expected one-second opening gap. The pinned editor also exposes OpenReel's existing move operation through Option/Alt + Left/Right for keyboard accessibility; this is not a PBJ editor command.

The iPhone-width shell is implemented and browser-validated in representative portrait sizes and at 844×390 landscape. At 767px and below, plus short phone-landscape viewports through 900×500, OpenReel's Preview and compact native Timeline remain visible together; its existing Assets and Inspector panels open as dismissible sheets; and clip selection reveals a bottom tray for its existing Split, Delete, Speed, Crop, and Volume paths. The mobile playhead is fixed at the horizontal center while the timeline scrolls beneath it, with half-viewport beginning/end padding so both timeline boundaries can reach the cursor. Timeline scrolling scrubs OpenReel's current time and playback advances the content beneath the fixed cursor. The compact toolbar keeps the project name and Export & Approve visible. This replaces the first one-panel workspace scaffold after a physical iPhone run showed that it obscured the editor and could place controls beneath Safari chrome. OpenReel's existing clip move and trim paths use pointer events with larger narrow-screen trim hit areas, and PBJ process-restart snapshot restoration has explicit automated coverage. PBJ project sessions bypass OpenReel's inherited Desktop Only overlay; the shell opts into iPhone safe areas, dynamic viewport height, standalone display, and unlocked portrait/landscape orientation without user-agent sniffing. Dirty projects flush immediately when Safari hides or backgrounds the page, using keepalive only for safely sized snapshot requests. A Home Screen standalone launch may resume the last successfully loaded PBJ project ID from device-local storage, but it refetches the complete projection so PBJ revalidates session, permission, snapshot identity, and media access; failures show a recovery state. The handoff hydrates PBJ's already-prepared mobile-safe per-source proxies sequentially, including after rotation, records their actual loaded byte sizes, and aborts outstanding projection/media requests when the page closes or is replaced. Type-check and production build pass for the current shell, alongside automated width, rotation, lifecycle, recovery, launch, and loader gates. Physical iPhone touch, memory pressure, interruption timing, and Home Screen PWA acceptance remain required for final user approval.

The deleted PBJ editor is not a fallback. OpenReel owns the editor, playback, project state, undo/redo, and its existing implementations of move, trim, split, crop, reorder, speed, volume, and other approved editing features. PBJ does not recreate or individually translate them. PBJ supplies the initial project and stores whole-project snapshots. Features that bypass PBJ media permissions or cannot survive snapshot restore and final export remain disabled.

### Stage 3 — OpenReel export, timeline learning, and approval (implemented; measurement continues)

The three backend boundaries are implemented. PBJ validates the latest OpenReel snapshot, requires deliberate export confirmation, rejects stale state, invalid timing, empty projects, and unapproved media, then freezes the exact snapshot into an immutable export-intent record. PBJ next accepts a metadata-only OpenReel render receipt, verifies the frozen snapshot hash and identity, output hash, nonempty delivered MP4, renderer revision, and required QA checks, then records `render_complete_pending_approval`. A separate final gate requires post-render confirmation of that exact output before storing one device-private approved example, one governed candidate signal, and an advisory Learning Agent assessment. The comparison uses PBJ's projected first OpenReel project and the exact frozen approved OpenReel project; it does not recreate individual editor commands. OpenReel remains the render owner and PBJ remains the approval owner.

The pinned OpenReel app now connects these gates through one PBJ-only Export & Approve action. It uses OpenReel's existing standard H.264 MP4 renderer, streams the output to the user's destination, mirrors muxer writes temporarily in OPFS for incremental SHA-256 verification, deletes the mirror after receipt creation, and requires a distinct post-render approval confirmation. Alternate native OpenReel export choices remain available only to standalone projects until matching receipt contracts exist. Automated tests cover the client contract. The complete supplied-media walkthrough passed on August 30, 2026: PBJ media hydrated into OpenReel for playback and rendering, the browser downloaded a playable 1080×1920 H.264/AAC MP4, PBJ validated its receipt, and explicit approval persisted the final comparison and governed learning evidence.

Record every first-timeline proposal, saved OpenReel snapshot, export intent, completed render, and approval. Compare the initial AI timeline with the latest successfully approved OpenReel project while keeping intermediate activity separate from positive recipe evidence.

The first measured representative edit retained the initial clip identity while changing its duration: clip retention `1.0`, changed clips `1`, and approved duration change `-8.866667` seconds. Reapproval reused the project's single approved-example identity and single governed approval signal, so repeated exports from one project do not inflate cross-project support.

### Stage 4 — Controlled private beta

Release a simple user experience to friends, family, and a small group of selected users. Users can describe the desired edit, optionally upload references, upload footage, revise outputs, and approve results.

The approved `troy-facelift` work precedes broader private-beta expansion. It
adopts the visual system from Troy's frontend at pinned commit `10c8efd` while
preserving PBJ's route, backend, media, privacy, learning, and OpenReel contracts.
Its phased gates are defined in `docs/TROY_FACELIFT_PLAN.md`. Troy's Studio,
mock state, simulated jobs, Clerk authentication, alternate services, and fake
projects are not part of PBJ.

The beta exists to test whether people other than the original owner can receive useful results and to collect permissioned evidence that improves recipe creation, matching, planning, and personalization.

User activity may propose learning. It must never silently rewrite shared recipes.

### Stage 5 — Public product

Open the product more broadly only after the private beta demonstrates reliable first cuts, controlled learning, acceptable costs and latency, and safe handling of user media.

The public product continues to infer editing direction from natural-language prompts. Recipes remain invisible. More usage creates more evidence, but recipe changes remain versioned, tested, and governed.

## 6. Recipe Engine v1

Recipe v1 is an evidence-backed editing specification. Current work must strengthen its matching, learning overlays, evaluations, version comparisons, and governance rather than reverting to a loose style summary.

### Required recipe content

- plain-English style description;
- narrative structure, hook, progression, and ending behavior;
- pacing and expected shot-duration ranges;
- talking-head, dialogue, reaction, and B-roll behavior;
- shot-selection and sequencing principles;
- cut, transition, crop, punch-in, zoom, and speed behavior;
- original-audio treatment;
- text, graphics, music, or effects observed in references, including whether the renderer can reproduce them;
- conditions that determine when a rule applies;
- exceptions and behaviors the style normally avoids;
- compatibility requirements and known limitations;
- supporting reference IDs and timestamp ranges;
- observation frequency and confidence;
- schema version, recipe version, status, ownership, and visibility.

### Rule classifications

Each meaningful observation should be classified as:

- **core:** consistently defines the editing approach;
- **common:** frequently used but not mandatory;
- **conditional:** used when a documented situation occurs;
- **optional:** compatible with the style but not required;
- **one-off:** observed without enough evidence to generalize.

### Evidence standard

Every important recipe rule should record:

- how many references support it;
- how many references were evaluated;
- confidence;
- supporting video and timestamp evidence;
- conflicts or counterexamples;
- whether PB&J can currently execute the behavior.

The system should prefer several representative references. The first practical target is three to five videos for a recipe, but evidence quality matters more than an arbitrary count.

## 7. Recipe lifecycle and governance

Recipes move through controlled states:

```text
draft → testing → validated → published → superseded
```

- A published recipe is immutable.
- A proposed improvement creates a new draft version.
- Existing projects retain the exact recipe version used to create them.
- New versions are tested against prior approved projects and new representative footage.
- Operators can compare versions and roll back.
- Only validated versions may influence the shared production system.

Initial ownership and visibility values:

- ownership: `platform` or `user`;
- visibility: `private`, `internal`, or `published`.

These fields govern internal retrieval and learning permissions. They do not create a user-facing catalog.

## 8. Prompt-to-recipe inference

The missing bridge between a natural-language request and internal recipes is a retrieval and matching layer.

For each project, the system should:

1. Interpret the user's intent, format, audience, pacing, tone, and explicit constraints.
2. Search approved internal recipe knowledge for relevant patterns.
3. Return a match score and explanation for internal audit.
4. Retrieve one recipe, compatible traits from several recipes, or general editorial defaults.
5. Give project instructions priority where they intentionally differ from the retrieved recipe.
6. Use optional references to refine the interpretation or create a private draft when confidence is low.
7. Record what knowledge and versions influenced the final plan.

Users should not be asked to choose a recipe. The interface should use plain language throughout.

### Private-beta PWA experience

The private beta is an iPhone-first installable PWA. Desktop is “mobile plus”: it uses the same information architecture, language, components, and project states while adding a sidebar, wider review layouts, and operator detail where extra space is useful.

The target experience follows three unmistakable states:

```text
Create → Wait → Edit
```

Mobile navigation uses Home, Projects, and More. New-project actions live prominently on Home and Projects instead of occupying a permanent navigation destination. Active-job status appears on Home and through in-app banners or push notifications, so a separate Activity destination is unnecessary. Project creation is a focused full-screen flow: describe the desired edit, optionally add finished references, upload raw footage, provide optional final details, wait for analysis and timeline preparation, then refine the prefilled timeline and deliberately Export & Approve.

Every sequential project screen provides a clearly centered Back control and one purple, context-specific forward action. Labels should describe the real consequence—such as Next, Upload and continue, Create cut, View cut, or Create revision—instead of forcing generic navigation language onto processing and decision states.

Private-beta access and permissions:

- conventional accounts may be deferred for the small trusted beta;
- a case-insensitive beta access code is validated only on the server and grants a secure seven-day device session;
- projects are private to the originating device;
- Recipe Lab knowledge is visible to testers but is not required for project creation;
- shared-recipe approval, publication, deletion, merging, rollback, and other governance actions require a separate owner session;
- access and owner secrets are environment configuration and must never be committed or shipped to the client.

Mobile media behavior:

- support iPhone Photos and Files sources, including common MOV, HEVC/H.265, and H.264 inputs;
- upload directly to controlled object storage using resumable or multipart transfers;
- limit each upload batch to 2 GB and allow subsequent batches;
- show per-file and overall progress, retry only failed files, and clearly distinguish upload completion from analysis completion;
- after upload completes, server jobs continue when the browser or installed PWA closes;
- use in-app banners for all users and opt-in push notifications for installed Home Screen PWAs.

Approved timeline behavior:

- open the normal editor only after PB&J has created and validated a useful first timeline;
- prioritize responsive mobile playback and a focused touch timeline rather than a professional NLE feature surface;
- use a fixed center playhead with the timeline moving beneath it, real source thumbnails and waveforms, direct trim handles, press-and-hold magnetic reordering, and a contextual bottom tool tray that never permanently obscures the timeline;
- expose the private-beta rough-cut tools users can rely on: split, ripple delete, per-clip crop, fixed speed presets, per-clip or all-original-audio volume, video/audio addition, undo/redo, and reviewable AI changes; keep replacement, transitions, and unsupported professional controls out of the mobile surface for now;
- make manual refinement and plain-language AI revision proposals prominent;
- show deterministic before/after proposal summaries and require explicit apply or reject;
- autosave reversible operations and preserve undo/redo across refresh;
- make **Export & Approve** explicit and require confirmation before the immutable export snapshot is created;
- render one combined video only during Export & Approve;
- preserve failed export evidence without recording a positive approval;
- recover interrupted analysis, timeline preparation, and export jobs as truthful retryable states.

`UI_FLOW.md` remains the canonical contract for the implemented editable-timeline experience. It changes only with live routes, templates, compatibility redirects, and route-contract tests.

The visual direction is simple, premium, restrained, and Apple-like. White is the dominant canvas, jelly purple is used for primary action buttons, selected states, and small brand moments, and peanut-butter brown is a sparingly used secondary accent. A few selected headings or celebratory states may use tasteful emojis for personality, but navigation, primary controls, technical statuses, and operator-heavy views should remain restrained. Responsive behavior should be driven by viewport, input capability, orientation, and standalone display mode instead of brittle device-name checks.

Current implementation: the new-project flow asks for a natural-language brief and footage, ranks approved internal recipes behind the scenes, pins the chosen version, and records the interpretation, candidates, confidence, and reasons. The internal recipe lab remains an operator tool, not part of the ordinary project flow.

## 9. Decision hierarchy and guardrails

Every planning request must keep four instruction layers separate, in this order:

1. **Platform and renderer guardrails** — immutable media-safety and technical rules.
2. **Internal recipe knowledge** — the inferred editing approach and supported traits.
3. **User preference profile** — recurring preferences learned for this user with permission.
4. **Project brief** — instructions that apply to the current video.

The model has creative discretion only after honoring higher-priority safety and technical constraints.

Non-negotiable guardrails include:

- use only media supplied for the project;
- never generate video, images, voices, music, sound effects, or B-roll;
- allow original recorded audio and permissioned user-uploaded audio only;
- never reference nonexistent files or invalid source time ranges;
- never emit uncontrolled shell commands;
- return a structured initial timeline or typed revision operations using supported contracts;
- never open the normal editor with an empty timeline;
- never combine the project into one video before Export & Approve;
- preserve source provenance for every output segment;
- validate and repair timeline state before preview and final rendering;
- report unsupported requests rather than silently fabricating results.

## 10. Learning loop

Every project may produce useful evidence:

- the original prompt and interpreted intent;
- recipe versions and traits retrieved;
- analyzer evidence and content map;
- initial AI timeline and source-time decisions;
- manual commands, AI proposals, applications, rejections, and undo/redo activity;
- revision requests and timeline differences;
- clips retained, removed, shortened, reordered, or replaced;
- framing, transition, overlay, and audio adjustments;
- final approved timeline and export receipt;
- number of revisions;
- optional scores, issue categories, and comments;
- cost, latency, failures, and repair activity.

Feedback must be classified into one of four scopes:

- **project-only:** applies only to this video;
- **user preference:** applies to this user across projects;
- **recipe suggestion:** may improve a specific internal recipe;
- **platform suggestion:** may indicate a universal safety or planning rule.

The system may recommend a classification, but lasting changes require explicit confirmation and appropriate review. One user's taste must not automatically alter the experience for everyone else.

### Implemented continuous-learning policy

- Every successful reference synthesis, raw-footage upload, cut revision, rating, and approval creates a provenance-linked learning signal.
- Signals are consolidated by recipe category into a reversible learning state containing project support, contradictions, average scores, confidence, and recent instructions.
- One or two projects produce an `emerging` insight; three distinct projects produce a `candidate`; five projects with at least three supporting projects, no more than one contradiction, and acceptable scores may produce a `promoted_overlay`.
- Promoted overlays influence future planning but do not rewrite the immutable reference-backed recipe version. They can be inspected, superseded, or rolled back independently.
- Planning retrieves only a small set of signals relevant to the current project, plus the consolidated learning state. Every plan records which signal IDs influenced it.
- Revision events are linked to later approval outcomes so the system can distinguish requested changes from changes that actually led to an accepted result.
- Every timeline interaction is retained for audit and context, but only the latest successful Export & Approve outcome contributes positive project evidence. Earlier exports from the same project cannot masquerade as independent cross-project support.
- Explicit requirements are extracted from the project prompt and revision instructions. Enforceable requirements such as named footage and supplied B-roll are checked against the selected source plan before rendering; semantic requirements such as chronological structure are recorded as planner-enforced until stronger deterministic verification exists.

## 11. Approved-example retrieval

Saving successful projects is not sufficient. The planning engine should retrieve a small number of relevant approved examples based on editing intent, footage type, recipe traits, format, and project constraints.

Retrieved examples may guide the planner, but they must not override platform guardrails, the current project brief, or the current approved recipe version. All example use must be recorded for reproducibility.

Current implementation retrieves up to three approved examples within the pinned recipe boundary using prompt similarity, duration proximity, and first-cut success. Their IDs and retrieval evidence are recorded. Cross-owner retrieval remains disabled until account permissions and consent are implemented.

## 12. Quality measurement

Owner and expert judgment remain important during Recipe Engine v1, but private beta requires repeatable signals.

Track at minimum:

- whether the first timeline was approved without changes;
- number of revisions before approval;
- AI-selected clips and initial timeline duration retained in the approved version;
- manual command count and AI proposal count;
- opening, ending, framing, ordering, and audio decisions retained;
- time from timeline opening to Export & Approve;
- requested duration versus rendered duration;
- invalid-plan and automatic-repair rates;
- recipe-version performance;
- user rating when supplied;
- analysis, planning, and rendering time;
- known API cost.

Current approval records compare the initial and approved canonical timelines using selected source-time overlap, opening and ending source-moment retention, manual operations, AI proposals, rejected proposals, and whether applied AI proposals still survive after undo/redo. These metrics join diffs, receipts, QA, prompt/model versions, and retrieved-example IDs in the learning record. Aggregate reporting and controlled recipe-version replay are still planned.

The first launch target is not a fixed number of recipe files. A better target is approximately 10–20 **validated internal recipes** that each have representative evidence, version history, multiple project tests, and recognizable first-cut performance.

## 13. Technical architecture

### Application

- Python and FastAPI for orchestration, routes, provider integrations, and validation.
- Existing server-rendered HTML, CSS, and JavaScript for the guided PWA shell.
- A planned selectively adapted OpenReel surface for touch-safe timeline interaction without restoring a separate PBJ editor.
- The mobile-first installable PWA shell, responsive desktop expansion, seven-day invitation session, device-scoped projects, owner tools, 2 GB batch enforcement, and local project deletion are implemented. Durable hosted jobs/storage, rate limiting, resumable multi-batch intake, Web Push delivery, cloud deletion guarantees, and multi-device recovery remain private-beta infrastructure work.
- Local JSON files during Recipe Engine v1.
- Checksum-addressed reference assets so identical videos are stored only once and recipes point to shared evidence.
- A proper database and controlled object storage before meaningful multi-user public access.

### Video understanding

- Twelve Labs Pegasus and Google Gemini remain replaceable analyzer adapters.
- Analyze original reference and raw files separately.
- Retain raw provider responses and normalize them into stable internal contracts.
- Cache successful analysis by source checksum, analysis purpose, provider, model, and prompt version. A matching cache hit must not trigger a new upload or analysis request.
- Keep cache reuse inside the same permission boundary. Before multi-user hosting, scope cache lookup and stored analysis to the owning account or to explicitly permissioned shared evidence; a checksum match alone never grants access to another user's analysis.
- Provider selection is an internal application concern, not a normal user choice. Any future analyzer comparison belongs in a separate evaluation harness rather than product routes.

### Planning

- OpenAI currently performs recipe synthesis, prompt interpretation, candidate selection, sequencing, and revision planning.
- The timeline milestone changes the first planner output to a canonical timeline and later revision output to typed command proposals.
- Models receive normalized structured data and return supported timelines or operations, never raw FFmpeg commands.
- Record model, prompt, recipe, example, and contract versions for every run.

### Rendering

- FFmpeg and ffprobe run locally during Recipe Engine v1.
- Application code compiles validated edit plans into controlled FFmpeg operations.
- Current target output is a 1080×1920 MP4 using H.264 video, AAC audio, and original project media only.
- In the timeline milestone, FFmpeg may inspect assets and generate separate proxies, thumbnails, and waveform inputs before export, but it must not create a combined first-cut preview.
- The adapted OpenReel application previews PBJ's projected canonical timeline. FFmpeg creates the combined finished video only from the immutable Export & Approve snapshot.

### OpenReel adaptation and external provenance

PBJ will selectively adapt OpenReel behind its own authority boundary rather than restoring the deleted editor or adopting the full outside application:

| Source | Planned contribution |
|---|---|
| OpenReel Video | Editing application, playback, timeline interactions, and compatible move, trim, split, crop, reorder, speed, and audio features behind the PBJ adapter. |
| Timeline Studio | Stable timeline IDs, source-time decisions, transaction preconditions, structural diffs, and selected interaction patterns. |
| Dawn Cut | Typed reversible command bus, schema-derived validation, deterministic reducers, invariants, and audit-chain design. |
| OpenKlip | Manual overrides, safe-area/focal logic, boundary-safe editing, source-time mapping, and acceptance tests. |
| Kinocut | Render receipts, hashes, preflight checks, and explicit QA states. |
| OpenChatCut | Multitrack interaction, shared manual/agent commands, proposal review, and transaction-level undo/redo. |
| Reels Engine | Phrase-anchored decisions, boundary-safe speech cuts, framing inspection, and measured QA heuristics. |
| Twelve Labs | Timestamped semantic understanding of reference and optionally analyzed project video. |
| OpenAI | Recipe inference, initial timeline planning, typed revision proposals, and learning classification. |
| FFmpeg/ffprobe | Inspection, per-source preview assets, final deterministic rendering, and technical QA. |

Every imported component must be pinned to a reviewed commit, attributed, isolated behind PBJ interfaces, recorded in third-party provenance, and covered by PBJ-specific tests. External code never bypasses PBJ media, privacy, validation, or learning rules. The governing boundary is in `docs/OPENREEL_ADAPTER_CONTRACT.md`.

## 14. Data and privacy requirements

Recipe Engine v1 may continue using local JSON and managed folders. Before a multi-user beta grows beyond trusted testers, add:

- authenticated accounts;
- per-user authorization and data isolation;
- controlled cloud video storage;
- encryption and secret management;
- upload limits and abuse protections;
- per-file raw-footage upload sessions with progress and a final media-validation step, avoiding a single giant multipart request that can overwhelm a browser;
- bounded concurrency for uploads and raw-footage analysis, initially capped at two simultaneous files and adjustable after observing provider limits;
- explicit consent for using references, revisions, or approved projects to improve shared systems;
- private-by-default user recipes and preferences;
- deletion and retention controls for local and provider-hosted assets;
- audit records for recipe provenance and learning decisions.

For the initial trusted PWA beta, a server-side invitation gate and device-private sessions may precede conventional accounts. This does not remove the requirements for authorization boundaries, rate limiting, secure cookies, object access controls, deletion, or abuse protection.

No user material may become shared recipe evidence without the required permission.

Current local storage separates reusable reference assets, internal recipes, projects, approved examples, user preferences, learning suggestions, and archived recipe records. Analyzer JSON is retained alongside normalized evidence, but it does not replace original media required for reanalysis, verification, rerendering, or benchmark evaluation.

## 15. Current and future model strategy

Do not train a custom model during Recipe Engine v1 or the initial private beta by default.

First improve:

- reference analysis prompts and normalization;
- recipe schema and synthesis;
- prompt-to-recipe matching;
- approved-example retrieval;
- decision prompts and guardrails;
- preference learning;
- validation and repair;
- evaluation quality.

Consider a specialized model only when a sufficiently large, permissioned dataset exists and measurements show that general models—not recipes, retrieval, prompts, validation, or product design—are the limiting factor.

The first likely custom model would be an editing planner, recipe matcher, feedback classifier, or candidate ranker. Training a video-understanding foundation model from scratch is not an early objective.

## 16. Implementation sequence

Milestones A–C have substantial implemented foundations. Milestones D and E are active. Milestones F and G are the approved editable-timeline work. Milestone H remains gated by hosted privacy and operational work. The list below remains the delivery checklist, not a claim that every item is finished.

### Milestone A — Recipe contract

1. Define a versioned Recipe v1 JSON contract.
2. Map legacy style records into the recipe contract without losing data.
3. Add rule classifications, evidence, conflicts, conditions, and capabilities.
4. Preserve a plain-English explanation for review.

### Milestone B — Multi-reference synthesis

1. Analyze each reference separately.
2. Compare observations across the full reference set.
3. Calculate recurrence and retain counterexamples.
4. Generate an evidence-backed draft recipe.
5. Add internal review, correction, and approval.

### Milestone C — Versions and lifecycle

1. Add recipe ownership, visibility, status, and semantic version fields.
2. Make approved versions immutable.
3. Pin every project and run to the exact version used.
4. Add diff, test, approval, rollback, and superseding behavior.

### Milestone D — Prompt inference

1. Interpret natural-language editing intent.
2. Retrieve relevant recipe knowledge invisibly.
3. Support compatible trait blending with provenance.
4. Fall back to general editorial rules or optional references when confidence is low.

### Milestone E — Controlled learning

1. Classify feedback by project, user, recipe, or platform scope.
2. Require confirmation before lasting changes.
3. Create recipe suggestions rather than direct mutations.
4. Retrieve relevant approved examples for future plans.
5. Add recipe and first-cut quality reporting.

### Milestone F — PBJ-to-OpenReel handoff

1. Introduce frame-safe canonical timeline, asset, track, clip, and command contracts.
2. Create separate mobile-safe proxies immediately and generate thumbnails or waveforms on demand, without a combined pre-export render.
3. Hand the project to OpenReel only after the first AI timeline is valid and populated.
4. Route the focused manual operation set and reviewable AI proposals back through PBJ commands.
5. Allow new video with optional analysis and permissioned user-uploaded audio.

### Milestone G — Export, approval, and timeline learning

1. Compile an immutable timeline snapshot into the allowlisted FFmpeg export graph.
2. Combine export and deliberate approval into one confirmed action.
3. Extend receipts and QA to timeline, asset, command-log, preview-parity, and output hashes.
4. Compare the initial AI timeline with the latest approved timeline.
5. Feed retained and corrected decisions into the governed learning system without treating one project as universal truth.

### Milestone H — Private-beta readiness

1. Add authentication, isolation, cloud storage, consent, and deletion controls.
2. Remove provider and recipe machinery from ordinary user screens.
3. Test failure recovery, cost limits, timeouts, and concurrent jobs.
4. Run the workflow with selected external users.
5. Review evidence and publish recipe improvements internally.

## 17. Verification plan

### Recipe verification

- Build a recipe from several finished references.
- Trace important rules to specific references and timestamps.
- Distinguish repeated traits, conditional traits, conflicts, and one-offs.
- Approve a version, create a new draft, compare it, and roll back safely.
- Confirm projects retain the exact recipe version used.

### Planning verification

- Infer useful recipe knowledge from a natural-language prompt without requiring visible recipe selection.
- Keep platform, recipe, user, and project instructions separate.
- Use only valid analyzed ranges from supplied files.
- Retrieve relevant approved examples without flooding or overriding the planner.
- Revise a project without repeating paid analysis unless explicitly necessary.

### Output verification

- Create a valid, populated first timeline without rendering a combined video.
- Preview the timeline using separate source proxies with edit-decision parity.
- Render a playable file from beginning to end only during Export & Approve.
- Use only supplied video, original audio, and permissioned user-uploaded audio.
- Preserve valid source provenance.
- Produce the requested format and approximately requested duration.
- Record timeline repairs and never hide failed, unanalyzed, or excluded inputs.

### Learning verification

- Keep project-only feedback out of user and shared recipes.
- Apply confirmed personal preferences only to the correct user.
- Route recipe suggestions into review rather than direct publication.
- Preserve permission and provenance for every shared learning record.
- Retain every proposal, command, rejection, undo, export, and approval without treating every gesture as positive evidence.
- Demonstrate that an approved newer recipe version improves measured first-timeline outcomes.

## 18. Stage gates

### Recipe Engine v1 complete when

- one evidence-backed recipe has multiple representative references;
- it has an approved version and at least one tested successor;
- multiple projects have tested it with compatible footage;
- feedback scopes and learning provenance are correct;
- newer versions demonstrate a meaningful first-cut improvement.

### OpenReel handoff ready when

- the normal first AI pass projects a populated canonical timeline referencing original assets into OpenReel;
- manual and AI changes use the same validated reversible command system;
- preview decisions and final FFmpeg output agree on cuts, timing, framing, layers, transitions, and audio behavior;
- combined rendering occurs only during Export & Approve;
- the latest approved timeline creates a complete initial-to-final learning comparison;
- iPhone interaction, recovery, invalid-range handling, and legacy-project migration pass the integration acceptance suite.

### Private beta ready when

- natural-language prompt inference works without visible recipe selection;
- private references and recipes are isolated;
- consent, retention, and deletion behavior is implemented;
- external testers can finish the workflow without developer assistance;
- errors, cost, latency, and job progress are understandable;
- learning suggestions cannot silently change shared behavior.

### Public release ready when

- approximately 10–20 recipes are validated rather than merely created;
- first cuts are consistently useful across representative users and projects;
- revision counts and failure rates are acceptable;
- multi-user infrastructure, privacy, security, and operations are production-ready;
- the prompt-to-recipe system reliably chooses or blends editing knowledge;
- the learning loop improves results without compromising user control.

## 19. Explicitly out of scope for the current phase

- a recipe marketplace or user-facing style catalog;
- requiring users to understand or manage recipe JSON;
- automatic publication of user-derived recipe changes;
- custom foundation-model training;
- generated footage, images, voices, music, sound effects, or B-roll;
- a full professional nonlinear editor with advanced keyframes, masking, grading, collaboration, interchange, or unrestricted tracks in the first beta;
- social publishing and collaboration features;
- public launch before private-beta safeguards and quality gates are met.

## 20. Immediate next action

On `troy-facelift`, complete the phased mobile visual adaptation in
`docs/TROY_FACELIFT_PLAN.md`, beginning with the shared design foundation and
continuing through real PBJ screens and governed OpenReel continuity. Keep
measuring initial-to-approved improvement and hardening iPhone touch, memory,
interruption recovery, and hosted private-beta infrastructure in parallel with
the visual work.

## Final product position

PBJ is not a recipe marketplace, a second editing interface, or a generative-video platform. It prepares self-improving AI rough cuts, hands them to a governed OpenReel integration for refinement, and retains validation, export, provenance, and learning authority.
