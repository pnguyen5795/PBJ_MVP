# PB&J Project Instructions

Read `GOAL.md`, `PROJECT_PLAN.md`, and `UI_FLOW.md` before planning or implementing material product changes. `PROJECT_PLAN.md` governs the product and learning system; `UI_FLOW.md` is the canonical screen-and-route contract.

## Current objective

PB&J is in Recipe Engine v1. Its former PBJ-owned editor was removed on August 30, 2026. The current product prepares a validated first-timeline package while strengthening evidence-backed internal recipes, multi-reference synthesis, versioning, invisible prompt-to-recipe inference, controlled feedback classification, approved-example retrieval, and measurable first-timeline improvement. The combined launcher, OpenReel handoff, supplied-media hydration, snapshot saving/restore, frozen-snapshot export intent, render-receipt validation, backend final-approval learning, and pinned OpenReel user-facing Export & Approve path are implemented and have passed a complete supplied-media browser walkthrough. Representative desktop tool compatibility is verified; the narrow-screen OpenReel shell keeps Preview and a compact native Timeline together, fixes its playhead at center while the padded timeline scrolls beneath it, presents Assets and Inspector in sheets, and exposes existing selected-clip tools in a bottom tray. Pointer-based OpenReel clip move/trim adaptation, desktop-blocker bypass for PBJ sessions, Safari-safe dynamic viewport, lifecycle snapshot flush, authority-revalidated Home Screen last-project resume, sequential abortable mobile-proxy hydration, and browser-validated portrait/landscape phone layouts are implemented. Physical iPhone touch, memory pressure, interruption timing, and Home Screen PWA acceptance remain pending for final user acceptance.

The `troy-facelift` branch is approved to implement the iPhone-first screen
compositions from `Swag420Money/PB-J` commit `10c8efd` with presentation-level
fidelity. Do not merely apply Troy-like tokens to PBJ's former layouts. Follow
`docs/TROY_FACELIFT_PLAN.md`. Import presentation only: exclude Troy's Studio,
mock data, simulated rendering, Clerk authentication, alternate services, and
application state. PBJ's route, backend, privacy, learning, and OpenReel
contracts remain authoritative.

The OpenAI layer has three bounded roles: Editing Agent, Timeline Repair Agent, and Learning Agent. Their current default is `gpt-5.6-luna` with medium reasoning. Keep role prompts, output contracts, provenance, and evaluation responsibilities separate even when they share a model and runtime.

## Product rules

- Recipes are invisible internal infrastructure.
- Do not add a recipe marketplace, public recipe catalog, or a normal workflow that requires users to select or manage recipes.
- Users describe the desired edit in natural language and may optionally upload references.
- The normal project flow must infer an approved internal recipe from the brief and must not require visible recipe selection. Internal recipe-lab controls are operator infrastructure only.
- Keep platform guardrails, recipe knowledge, user preferences, and project instructions separate.
- Capture every reference, project, revision, rating, and approval as a scoped learning event. Immediate learning uses reversible overlays and relevant retrieval; never let one project directly rewrite source-backed shared rules.
- Revision feedback applies to its project immediately. Wider recipe, preference, or platform scope is only a classified suggestion until confirmation and governance thresholds are satisfied.
- Promote learned overlays only after repeated cross-project support, retain contradictory evidence, record thresholds and influenced plans, and preserve rollback.
- Preserve provenance, permissions, recipe versions, prompt versions, model versions, and approved examples.
- Reuse a successful video analysis only when source checksum, purpose, provider, model, and analysis-prompt version match. A cache hit must not be reported as new provider cost or create duplicate remote-asset ownership.
- Shared Recipe Lab candidates may be contributed and viewed by beta users only after explicit authorized-contribution confirmation, but only an owner may revise, validate, archive, or otherwise govern shared recipes. Project-private reference recipes and project-derived learning remain isolated to their originating device until account-level consent exists.
- Do not train a custom model until measurement shows general models are the bottleneck and a sufficient permissioned dataset exists.
- The canonical future first cut is a validated, prefilled timeline created by AI from the user's prompt, optional references, and raw footage. The normal user must not begin with an empty timeline.
- OpenReel owns manual editing actions, editing-session state, and undo/redo. PBJ must not translate each OpenReel tool action into its retired editor command system; it stores complete OpenReel project snapshots tied to the source first timeline.
- Capture first-timeline proposals, saved OpenReel snapshots, exports, and approvals as scoped evidence. Only a successful approved outcome is positive project evidence; intermediate working snapshots never directly rewrite a shared recipe.
- Agents return schema-valid proposals only. The Editing Agent cannot render or mutate a timeline without the application command path; the Repair Agent acts only on a concrete validation failure and gets at most two attempts; the Learning Agent produces advisory candidates and cannot promote or rewrite shared recipes.
- Normalize a model-provided source name only when it resolves to exactly one project-owned media ID, and record that repair. Never guess across multiple files; ambiguous and foreign IDs remain validation failures. If the analyzer produced exactly one candidate, an empty model shortlist may retain that sole candidate with a warning.

## Private-beta UX rules

- Design the hosted PWA for iPhone first. Desktop is an expanded version of the same flow, not a separate product.
- Prefer responsive layout, input capability, orientation, and standalone-display detection over user-agent sniffing.
- Keep the interface simple, premium, restrained, and Apple-like: a warm cream-to-white canvas, black primary action buttons balanced with purple highlights and progress states, one clear primary action, generous spacing, plain language, and minimal visible machinery.
- Use emojis sparingly as tasteful personality cues on selected headings or celebratory states. Do not place them throughout navigation, every button, technical status, or dense operator views.
- The temporary private beta may omit conventional accounts. Require a server-validated, case-insensitive access code and remember authorization for seven days using a secure session; never expose access or owner codes in client code or committed files.
- Keep projects private to the originating device. Shared Recipe Lab knowledge may be visible to beta users, but governance and destructive actions require a separate owner session.
- Accept direct resumable uploads in batches of up to 2 GB and allow additional batches. Do not proxy large video bodies through the web application process.
- Show in-app job banners and support opt-in push notifications for installed Home Screen PWAs.
- Do not reintroduce a PBJ-owned editing interface. Future refinement and **Export & Approve** belong in the governed OpenReel integration and must remain deliberate and confirmed.
- Do not rebuild or individually bridge editing features already implemented by OpenReel. Adapt the complete OpenReel project to PBJ's initial-handoff, snapshot, media-permission, approval, and learning boundaries; disable incompatible features instead of creating PBJ duplicates.
- Give every sequential project screen an obvious Back control and one black, context-specific forward action, using purple for selected, active, or progress emphasis. Root and terminal states may use truthful equivalents instead of misleading Back or Next labels.

## Media boundaries

- Use only media supplied for the project.
- Do not generate video, images, voices, music, sound effects, or B-roll.
- Original recorded audio and permissioned user-uploaded audio are allowed. User-uploaded audio must remain project-private and must never be generated or fetched by PB&J.
- OpenAI returns structured timelines or typed editorial operations; it never controls the shell.
- Validate all source ranges and supported operations before FFmpeg rendering.
- FFmpeg may inspect media and create separate proxies, thumbnails, and waveforms. It must not combine the project into one video before Export & Approve.
- FFmpeg executes decisions during final export; it does not make creative decisions.
- Newly added video is analyzed only when the user requests AI understanding and the checksum/provider/model/prompt/permission cache does not match. Unanalyzed video remains manually editable but unavailable for semantic AI selection.

## Current delivery stages

1. Preserve and validate Recipe Engine v1.
2. Build the PBJ-to-OpenReel handoff described in `docs/OPENREEL_ADAPTER_CONTRACT.md` without restoring the deleted PBJ editor.
3. Re-enable and measure Export & Approve and initial-to-approved timeline learning through that integration.
4. Complete hosted infrastructure for the iPhone-first PWA, then run a controlled private beta with permissioned learning.
5. Prepare a public product only after the quality, privacy, security, and operational gates in `PROJECT_PLAN.md` are satisfied.

## Documentation discipline

Update `GOAL.md`, `README.md`, `PROJECT_PLAN.md`, and this file whenever a decision materially changes the product goal, learning policy, media boundaries, user experience, or stage gates. Preserve the distinction between implemented behavior and planned behavior.

Do not collapse, reorder, or reintroduce screens in the normal project journey without updating `UI_FLOW.md` and its route-contract tests in the same change. Visual mockups are illustrations; the versioned UI-flow contract and passing tests govern the live app.

Keep implemented behavior distinct from approved planned behavior. `UI_FLOW.md` currently proceeds from Timeline Ready to the OpenReel handoff route; future route, template, or compatibility changes must update it and the route-contract tests together.

When adapting external editor code, pin the reviewed source commit, preserve all required notices, record the exact files and modifications in third-party provenance, isolate the code behind PB&J interfaces, and add PB&J-specific tests. Never allow imported code to bypass PB&J media, validation, privacy, or learning rules.

Do not restore the retired analyzer-switch, manual rough-cut, or A/B comparison endpoints inside the user application. Provider evaluation belongs in a separate controlled evaluation harness if it becomes necessary again.
