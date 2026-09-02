# PB&J — AI Rough-Cut Preparation and Learning

PBJ turns a natural-language request, optional finished references, and supplied
raw footage into a validated first-timeline package. Its invisible Recipe Engine
learns from permissioned, approved outcomes without exposing recipes or allowing
one project to rewrite shared knowledge.

## Current product state

The `troy-facelift` branch contains the approved phased plan to implement Troy's
iPhone-first screen compositions faithfully while retaining PBJ's real backend and governed
OpenReel editor. Black primary actions are balanced with purple highlights and
progress states. Troy's Studio, mock data, simulated rendering, authentication,
and alternate backend are explicitly excluded. See
[docs/TROY_FACELIFT_PLAN.md](docs/TROY_FACELIFT_PLAN.md).

The former PBJ-owned timeline editor has been permanently removed. PBJ currently:

1. captures the desired edit and optional references;
2. accepts only permissioned project media;
3. analyzes footage with a provider-neutral video-understanding layer;
4. retrieves or creates an evidence-backed internal recipe;
5. asks bounded OpenAI agents for schema-valid timeline proposals;
6. validates and stores a populated canonical Timeline v1; and
7. prepares per-source proxies and a handoff package without creating a combined video.

The live journey ends at `/projects/{project_id}/ready`. A read-only OpenReel
project projection, loader, and debounced whole-project snapshot bridge are
implemented for Gate B, and reopening the handoff restores the latest valid
snapshot automatically. Timeline Ready now links through the canonical live
handoff route. The frozen-snapshot export-intent, render-receipt validation,
and deliberate final-approval learning gates are implemented. The pinned OpenReel
app now connects them through a PBJ-specific Export & Approve action. A complete
supplied-media browser walkthrough has verified playback, download, receipt,
approval, approved-example creation, and governed learning evidence. The governing screen contract is
[UI_FLOW.md](UI_FLOW.md); the isolation boundary is
[docs/OPENREEL_ADAPTER_CONTRACT.md](docs/OPENREEL_ADAPTER_CONTRACT.md).
Representative editor-tool verification is tracked in
[docs/OPENREEL_COMPATIBILITY_MATRIX.md](docs/OPENREEL_COMPATIBILITY_MATRIX.md).
The narrow-screen OpenReel shell now keeps its Preview and compact native
Timeline visible together, opens its Assets and Inspector as sheets, and shows
existing clip tools in a contextual bottom tray. Its mobile playhead remains
centered while the padded timeline scrolls underneath it. OpenReel's existing clip move
and trim interactions accept pointer input with larger narrow-screen trim targets.
PBJ sessions also bypass OpenReel's inherited desktop-only overlay and use an
iPhone-safe dynamic viewport with unlocked portrait and landscape orientation.
Representative 390×844 portrait and 844×390 landscape browser checks now keep
the mobile PBJ/OpenReel shell active; short phone-landscape viewports no longer
fall into desktop navigation or desktop toolbar presentation.
Pending OpenReel changes flush immediately when Safari hides or backgrounds the
page, while PBJ's latest immutable snapshot remains the recovery source.
Home Screen relaunch resumes only the last successfully loaded PBJ project and
reruns PBJ's session, permission, snapshot, and media validation before opening.
PBJ's mobile-safe per-source proxies load sequentially, report their actual
hydrated sizes, and stop loading if the page closes or is replaced.
The app shell enforces Safari's dynamic viewport so the timeline and tool tray
remain above browser chrome.
Physical iPhone touch, memory-pressure, interruption, and Home Screen acceptance
testing is still required before the mobile editor receives final user approval.

The local browser walkthrough is verified end to end: a PBJ timeline opens in
OpenReel, an OpenReel project change creates a PBJ snapshot, and reopening the
handoff restores that edited project without showing a competing local-recovery
prompt. The same walkthrough verified a real 1080×1920 H.264/AAC MP4 rendered
from PBJ-supplied footage rather than an empty or flattened timeline.

OpenReel will supply the editor, playback experience, and existing feature
implementations—including move, trim, split, crop, reorder, speed, and audio
controls. PBJ will not recreate or individually translate those features. Its
adapter loads the prepared project once and saves the complete OpenReel project
as the user works, while PBJ retains media, privacy, approval, and learning boundaries.

## Preserved integration infrastructure

PBJ still owns the backend capabilities required to connect safely to OpenReel:

- canonical integer-frame timeline data and stable media identifiers;
- typed, validated first-timeline and AI proposal infrastructure;
- immutable OpenReel snapshots tied to the source timeline revision and hash;
- unique-only normalization of model-provided source names to project-owned
  media IDs, while ambiguous or foreign identifiers remain rejected;
- project-private media ownership and permission boundaries;
- a governed export-intent boundary that freezes the exact validated OpenReel snapshot;
- a metadata-only render receipt that verifies snapshot identity, output integrity, delivery, and QA without silently approving the result;
- an explicit post-render approval gate that stores one governed whole-project initial-to-final learning outcome;
- provenance, recipe versions, prompt/model versions, and governed learning events.

These are not a second editing interface or duplicate feature implementation.
They form the authority boundary that prevents OpenReel from bypassing PBJ's
privacy, validation, export, or learning rules.

## Running the combined local app

After a fresh clone, run `./scripts/setup_openreel.command` once. That setup
downloads the reviewed OpenReel revision, applies PBJ's versioned integration
patch, installs its packages, and verifies the editor.

Double-click `start_app.command`. It starts PBJ on port 8000 and the pinned
OpenReel host on port 5173, waits for both to become ready, and then opens PBJ.
Keep that Terminal window open while editing; Control-C stops both services.
`stop_pbj.command` can stop both later if the launcher window was closed.

The launcher uses the pinned checkout at `.evaluations/openreel-video`. It does
not download dependencies silently. If Node.js, pnpm, the checkout, or installed
OpenReel packages are missing, it stops with a specific setup message.

## OpenAI roles

PBJ keeps three bounded roles separate even when they share a model:

- Editing Agent: proposes first timelines and project revisions.
- Timeline Repair Agent: receives a concrete validation failure and gets at most two attempts.
- Learning Agent: synthesizes reference-backed recipes and advisory learning candidates.

Their default is `gpt-5.6-luna` with medium reasoning. Agents return structured
proposals only; application code owns mutation, validation, persistence, approval,
and rendering.

## PBJ-only backend setup

For backend development without the OpenReel editor, run:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload
```

Open <http://127.0.0.1:8000>. This backend-only command does not start OpenReel.
The ignored `.env` holds provider keys, access codes, and optional per-agent
model overrides.

## Non-negotiable media boundary

PBJ uses only media supplied and permissioned for the project. It does not
generate or fetch video, images, voices, music, sound effects, or B-roll. FFmpeg
may inspect media and prepare separate proxies, thumbnails, and waveforms; it
must not create a combined first cut during PBJ preparation.

## Product authority

- [GOAL.md](GOAL.md) defines the objective and boundaries.
- [PROJECT_PLAN.md](PROJECT_PLAN.md) governs product, learning, privacy, and stage gates.
- [UI_FLOW.md](UI_FLOW.md) governs the implemented screens and routes.
