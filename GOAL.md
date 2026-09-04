# PB&J Project Goal

## North Star

PB&J is a self-improving AI rough-cut creation and learning system.

> PBJ turns a creative brief, optional finished references, and supplied raw footage into a finished first-cut video. Approved outcomes teach PBJ how to make future cuts stronger.

## Product outcome

A user describes the desired video, optionally supplies finished reference videos, and uploads raw footage. Twelve Labs analyzes the supplied media. PBJ invisibly retrieves or creates the relevant internal editing recipe. The Editing Agent creates a structured timeline using only project media, application code validates it, and FFmpeg renders a playable MP4.

The user watches the result and deliberately chooses either **Approve this cut** or **Request changes**. Revision feedback creates a new structured timeline and a newly rendered version without repeating matching paid media analysis. Successful approval records the exact timeline, render receipt, quality results, recipe version, and initial-to-approved comparison as governed evidence.

PBJ does not include OpenReel or a manual timeline editor. The retired direct editor API, proxy, proposal, and transaction/undo stack are also removed; timeline state is internal to the automatic workflow. The canonical product is an AI-created rendered rough cut with a conversational revision loop.

## Current objective

Restore and harden the proven Twelve Labs → OpenAI → validated timeline → FFmpeg workflow while retaining Recipe Engine v1, Troy's approved iPhone-first presentation, versioned recipes, approved-example retrieval, bounded repair, and controlled learning.

Three bounded OpenAI roles support the journey: the Editing Agent plans cuts, the Timeline Repair Agent receives exact validation failures and gets at most two attempts, and the Learning Agent classifies reference and approved-outcome evidence. When a synthesized recipe cites nonexistent analyzer evidence, the Learning Agent may receive that concrete validation failure for at most two citation-repair attempts; completed media analysis is reused. Agents return structured proposals only; application code owns validation, persistence, rendering, approval, and governance.

The current hosting milestone is a single, access-code-protected private demonstration workspace on Render. It deliberately shares one workspace across authorized browsers so PBJ can be demonstrated from an iPhone while the development laptop is off. A separate minimal launcher can wake the paid PBJ service, and PBJ requests suspension only after 15 minutes without a visible authorized browser and with no upload, analysis, render, export, deletion, or media process active. This is cost control for a disposable demo, not durable job infrastructure. Hosted startup fails closed on weak session or lifecycle configuration; codes match exactly, failed login attempts are throttled, browser mutations are same-origin, and users can log out. A controlled 15-video/60-second run completed without a restart, but saturated the one CPU; a later denser 30-second metrics query found a 96.157% peak of the 2 GB memory limit. The `/tmp` project storage and in-process jobs remain disposable, and the measured run is a narrow demo-capacity result rather than multi-user or durable release architecture.

## Delivery path

1. Operate the complete automatic first-cut and revision loop locally.
2. Measure first-cut quality and revision burden across approved projects.
3. Validate the single-workspace hosted demo, then complete durable jobs, private object storage, identity, privacy, security, and recovery.
4. Run a controlled iPhone-first PWA beta.
5. Prepare public release only after documented quality and safety gates pass.

## Success condition

PB&J succeeds when users receive useful rendered first cuts and the work required to approve them measurably decreases across recipe versions. Primary signals include first-cut approval, selected-source and duration retention, opening and ending retention, revision count, time to approval, instruction compliance, and user rating.

## Non-negotiable boundaries

- Recipes remain invisible internal infrastructure.
- Use only media supplied and permissioned for the project.
- Original recorded audio and permissioned uploaded audio are allowed.
- Do not generate or fetch video, images, voices, music, sound effects, or B-roll.
- Twelve Labs analyzes media; OpenAI proposes structured editorial decisions; application code validates; FFmpeg renders deterministically.
- Twelve Labs is the sole supported media analyzer; PBJ does not select among or silently fall back to alternate analyzers.
- FFmpeg executes decisions but never makes creative choices.
- Only a successful, explicitly approved output becomes positive project evidence.
- One project never directly rewrites a shared source-backed recipe rule.
- Preserve provenance, permissions, versions, contradictions, reproducibility, and rollback.
- Operational diagnostics must be privacy-safe: record bounded technical events, never filenames, media, prompts, access codes, secrets, or raw exception text.
- Do not train a custom model until measurement shows general models are the bottleneck and sufficient permissioned data exists.
