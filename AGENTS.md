# PB&J Project Instructions

Read `GOAL.md`, `PROJECT_PLAN.md`, and `UI_FLOW.md` before planning or implementing material product changes. `PROJECT_PLAN.md` governs the product and learning system; `UI_FLOW.md` is the canonical screen-and-route contract.

## Current objective

PB&J is in Recipe Engine v1 and uses an automatic rendered rough-cut workflow. A user supplies a prompt, optional finished references, and raw footage. Twelve Labs analyzes the supplied media, OpenAI proposes a structured edit, application code validates and repairs it, and FFmpeg renders a playable MP4. The user approves the result or requests a prompt-driven revision. PBJ has no OpenReel integration and no manual timeline editor.

The `troy-facelift` branch implements the iPhone-first presentation from `Swag420Money/PB-J` commit `10c8efd`. Follow `docs/TROY_FACELIFT_PLAN.md`. Import presentation only: exclude Troy's Studio, mock data, simulated rendering, Clerk authentication, alternate services, and application state.

The OpenAI layer has three bounded roles: Editing Agent, Timeline Repair Agent, and Learning Agent. Their current default is `gpt-5.6-luna` with medium reasoning. Keep role prompts, output contracts, provenance, and evaluation responsibilities separate.

## Product rules

- Recipes are invisible internal infrastructure. Do not add a recipe marketplace or normal recipe-selection workflow.
- Users describe the edit in natural language and may optionally upload references.
- Keep platform guardrails, recipe knowledge, user preferences, and project instructions separate.
- Capture references, projects, revisions, ratings, exports, and approvals as scoped learning events.
- Project feedback applies immediately to that project. Wider scope remains a classified suggestion until governance thresholds are met.
- Preserve provenance, permissions, recipe versions, prompt versions, model versions, render receipts, and approved examples.
- Reuse analysis only when checksum, purpose, provider, model, prompt version, and permission boundary match.
- Only an explicitly approved successful render is positive project evidence.
- Agents return schema-valid proposals only. Application code validates and renders. The Repair Agent receives concrete failures and gets at most two attempts. The Learning Agent cannot promote shared recipes.
- Normalize a model-provided source name only when it resolves to exactly one project-owned media ID. Never guess between files.
- Repair an unknown recipe-evidence segment label only when its named reference and timestamp interval identify exactly one analyzer segment, and record the repair. Ambiguous citations remain failures.

## Private-beta UX rules

- Design the hosted PWA for iPhone first; desktop is an expanded version of the same flow.
- Keep Troy's warm cream-to-white canvas, black primary actions, purple active/progress states, generous spacing, and plain language.
- The private beta uses a server-validated access code and seven-day secure session. Never expose codes in client or committed files.
- Keep projects private to the originating device in local mode. When `PBJ_SHARED_WORKSPACE=true`, treat all authorized browsers as one intentionally shared private-demo permission boundary; do not describe it as multi-user isolation.
- Accept resumable upload batches up to 2 GB and do not proxy large video bodies through the web process.
- Show truthful job progress and failures.
- Keep client diagnostics privacy-safe and bounded. Never record filenames, media, prompts, access codes, secrets, or raw exception messages; diagnostic downloads require owner access.
- Do not reintroduce a manual timeline editor. Users watch rendered versions, approve, or request changes in natural language.
- Give sequential screens an obvious Back control and one context-specific primary action.

## Media boundaries

- Use only project-supplied media.
- Do not generate or fetch video, images, voices, music, sound effects, or B-roll.
- Original recorded audio and permissioned uploaded audio are allowed and remain private.
- OpenAI returns structured timelines; it never controls the shell or emits executable FFmpeg commands.
- Validate source ownership, source ranges, timeline continuity, and supported operations before rendering.
- FFmpeg inspects media, prepares technical assets, and renders validated decisions. It never makes creative decisions.
- Newly added video is analyzed only when AI understanding is requested and no matching authorized cache exists.

## Current delivery stages

1. Preserve and validate Recipe Engine v1.
2. Operate the complete Twelve Labs → OpenAI → validated timeline → FFmpeg first-cut workflow.
3. Measure revision burden and initial-to-approved improvement.
4. Complete hosted infrastructure and run a controlled private beta.
5. Prepare public release only after quality, privacy, security, and operational gates pass.

## Documentation discipline

Update `GOAL.md`, `README.md`, `PROJECT_PLAN.md`, and this file whenever a decision materially changes the goal, learning policy, media boundary, UX, or stage gate. Update `UI_FLOW.md` and route-contract tests together for flow changes. Preserve the distinction between implemented and planned behavior.

Keep external visual-source provenance pinned and documented. Do not restore retired analyzer selection, manual rough-cut, A/B comparison, OpenReel, or a PBJ-owned timeline editor without an explicit new product decision and matching governing-document changes.

The `codex/hosted-demo` branch packages the current app as one Dockerized Render web service with FFmpeg. The live service uses 1 CPU and 2 GB RAM, with normal FFmpeg encoding restored, but storage remains ephemeral and sample media must remain disposable. Attach persistent storage before keeping real projects. Durable workers, object storage, and multi-user accounts are not yet implemented.
