# PB&J Project Goal

## North Star

PB&J is a self-improving AI rough-cut preparation and learning system.

> PBJ creates the first timeline and prepares it for OpenReel. Approved outcomes teach PBJ how to make future first timelines stronger.

## Product outcome

A user describes the desired video in natural language, optionally supplies finished reference videos, and uploads raw footage. PBJ analyzes the supplied media, invisibly retrieves or creates the relevant internal editing recipe, and produces a validated, populated timeline package using only project-supplied media.

The timeline—not a rendered MP4—is the authoritative first cut. PBJ hands that populated timeline to OpenReel once; OpenReel then owns the editing project, tools, playback, and undo/redo. PBJ stores complete OpenReel project snapshots instead of translating every editor action into a PBJ command. FFmpeg may inspect media and create separate proxies, thumbnails, and waveforms, but it does not create a combined first cut during preparation.

## Current objective

Strengthen Recipe Engine v1 and build a governed PBJ-to-OpenReel handoff. PBJ must continue improving through evidence-backed recipes, multi-reference synthesis, invisible prompt-to-recipe inference, approved-example retrieval, controlled feedback classification, versioning, and measurable initial-to-approved timeline learning.

On the `troy-facelift` branch, PBJ is also adopting the approved iPhone-first
visual system from Troy's frontend at pinned commit `10c8efd`. This is a visual
adaptation only: PBJ's backend, canonical routes, real project state, privacy and
learning boundaries, and OpenReel ownership remain authoritative. Troy's Studio,
mock logic, alternate backend, fake data, and simulated progress are excluded.
The phased implementation and acceptance gates are recorded in
`docs/TROY_FACELIFT_PLAN.md`.

The live preparation journey is documented in `UI_FLOW.md`; the OpenReel isolation boundary is documented in `docs/OPENREEL_ADAPTER_CONTRACT.md`.

Three bounded OpenAI roles support that journey: the Editing Agent creates first timelines and reviewable revisions, the Timeline Repair Agent receives exact deterministic validation failures and may make at most two repair attempts, and the Learning Agent synthesizes reference-backed recipes and classifies approved-outcome evidence. All three currently run on `gpt-5.6-luna` with medium reasoning. They return structured proposals only; application code still owns validation, persistence, governance, approval, and rendering.

## Delivery path

1. Preserve and validate Recipe Engine v1.
2. Operate the live, one-launch PBJ-to-OpenReel handoff without rebuilding OpenReel editing features inside PBJ.
3. Measure timeline-level improvement through the now-validated supplied-media OpenReel Export & Approve experience.
4. Complete hosted storage, durable jobs, privacy, security, and recovery infrastructure.
5. Run a controlled iPhone-first private PWA beta, then prepare public release only after the documented quality gates pass.

## Success condition

PB&J succeeds when users receive useful first timelines and the work required to approve them measurably decreases across recipe versions. Primary signals include first-timeline approval, AI-selected clip and duration retention, opening and ending retention, manual command count, AI revision count, time to approval, instruction compliance, and user rating.

Every reference, first-timeline proposal, saved OpenReel project snapshot, export, and approval remains auditable evidence. Only successful approved outcomes provide positive project evidence; one project never directly rewrites a shared source-backed rule. Promotion still requires repeated cross-project support, contradictions remain visible, and every learned overlay remains reversible.

Model-provided media names may be normalized only to a uniquely matching
project-owned source, with the repair recorded in the plan. PBJ never guesses
between multiple files and continues to reject foreign source identifiers.

## Non-negotiable boundaries

- Recipes remain invisible internal infrastructure; there is no recipe marketplace or normal recipe-selection workflow.
- Use only media supplied and permissioned for the project.
- Original recorded audio and permissioned user-uploaded audio are allowed.
- Do not generate or fetch video, images, voices, music, sound effects, or B-roll.
- Twelve Labs analyzes media; OpenAI makes structured first-timeline decisions; OpenReel owns editing-session state and compatible rendering; PBJ owns permissions, snapshots, approval, and learning. The connected final export path is validated for the standard H.264 MP4 contract, and OpenReel's existing move and trim interactions now share pointer input across desktop and the mobile PWA surface without the inherited desktop-only blocker. Pending snapshots flush at the Safari backgrounding boundary while PBJ remains the durable recovery authority, Home Screen relaunch revalidates PBJ authority before resuming its device-local last-project pointer, and mobile-safe proxies hydrate sequentially with abortable requests. The mobile OpenReel presentation keeps Preview and a compact native Timeline together, fixes the playhead at center while the timeline scrolls beneath it, moves Assets and Inspector into sheets, and exposes existing selected-clip tools in a bottom tray above Safari chrome. Portrait and short-landscape phone layouts are browser-validated; final physical-iPhone acceptance remains a user gate.
- Do not train a custom model until measurements show general models are the bottleneck and a sufficient permissioned dataset exists.
- Preserve provenance, permissions, versions, contradictions, reproducibility, rollback, and device/account isolation.
