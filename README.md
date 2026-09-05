# PB&J

PB&J is an iPhone-first AI rough-cut application. A user describes an edit, optionally supplies finished reference videos, uploads raw footage, and receives a rendered first cut made only from that project media.

## How it works

1. Twelve Labs analyzes optional references and raw footage.
2. PBJ retrieves or creates an internal evidence-backed recipe.
3. OpenAI proposes a structured edit timeline.
4. PBJ validates source ownership, timestamps, duration, continuity, and supported operations.
5. A bounded repair agent may correct concrete validation failures.
6. FFmpeg renders the validated timeline into a verified H.264/AAC MP4.
7. The user watches the cut, approves it, or requests a natural-language revision.

PBJ contains no OpenReel integration and no manual timeline editor. Twelve Labs is its sole media analyzer; recipes and provider machinery remain invisible in the normal user journey.

## Start PBJ

Double-click `start_app.command`, or run:

```sh
./start_app.command
```

The launcher prepares the Python environment on first use, starts PBJ on port 8000, opens the local app, and prints the same-Wi-Fi address for iPhone testing.

To stop PBJ, double-click `stop_pbj.command`. It stops only PBJ processes belonging to this project and closes the relevant Terminal windows.

For direct development:

```sh
.venv/bin/uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Open <http://127.0.0.1:8000>.

## Local configuration

Copy `.env.example` to `.env` if the launcher has not already done so. Configure:

- `OPENAI_API_KEY`
- `TWELVE_LABS_API_KEY`
- `PBJ_ACCESS_CODE`
- `PBJ_OWNER_CODE`
- `PBJ_SESSION_SECRET`

Local `.env` and project data are ignored by Git. Do not commit API keys, access codes, uploaded media, analyses, or rendered projects.

## Private hosted demo

The `codex/hosted-demo` branch includes a Render Blueprint and Docker image for one private demonstration workspace. Render runs PBJ and FFmpeg independently of the development laptop. The paid web service uses 1 CPU and 2 GB RAM, while data remains ephemeral under `/tmp/pbj-data`: use disposable sample footage because uploads, analyses, and completed cuts can disappear after manual suspension, restart, or deploy. Hosted FFprobe and FFmpeg work run off the web event loop. FFmpeg preserves the normal CRF 20/medium quality profile while bounding decoder, filter-graph, and encoder concurrency. A controlled 15-video/60-second cut completed in 325.265 seconds without a restart and reached 100% CPU. A denser follow-up metrics query captured a 96.157% memory peak, leaving only about 78.7 MiB; treat that as the current disposable-demo envelope, not spare capacity for larger jobs. The worktree gives FFmpeg a measured hang deadline of at least 600 seconds, scaling at 9x output duration, and terminates/reaps a timed-out child. The retired editor-proxy pipeline is removed; the automatic rough-cut path renders directly from original project media.

This mode is deliberately access-code protected. Every authorized browser enters the same workspace, so it is appropriate for owner-controlled smoke testing but not for public or multi-user release. The paid instance remains a single web process, and unusually complex or concurrent jobs may still require more compute or a dedicated worker. Attach persistent storage before retaining real projects. Durable workers and object storage remain future private-beta work.

For intermittent demonstrations, manually resume `pbnj` in the Render Dashboard, wait for its health check to pass, and then open the PBJ URL. After the demonstration, first confirm that no upload, analysis, render, export, or deletion is still running, then manually suspend `pbnj`. The app does not start or stop its own Render service and does not require a Render API key.

Hosted startup fails unless an access code, a unique session secret of at least 32 bytes, and HTTPS-only cookies are configured; Render's platform marker keeps these checks fail-closed if the application mode flag drifts. Access and owner codes are exact, case-sensitive, and bounded to 256 UTF-8 bytes; their public form bodies are capped at 1 KiB before parsing. Repeated failures are throttled in the one web process, state-changing browser requests must be same-origin, security headers protect dynamic and unhandled-error responses, and **More → Log out** clears the current authorization. Starting a distinct project is a protected POST, so merely opening a link cannot discard an active draft. Cookie-held project drafts are bounded to keep accepted signed cookies below 4 KiB, including Unicode input. Sessions remain stateless in this checkpoint: rotating `PBJ_SESSION_SECRET` signs out every browser, while immediate per-session server-side revocation remains part of future account infrastructure. The Home Screen shell is network-only and intentionally has no service-worker/offline cache; connected pages remove the retired worker and its legacy `pbj-shell-*` cache from older installations.

The Blueprint waits for the repository's full test check before auto-deploying and requests Render's maximum 300-second shutdown window. That window is extra drain time, not durable job handling; a restart can still interrupt analysis or rendering and erase `/tmp` state.

PBJ records privacy-safe client diagnostics for upload progress, retries, connectivity, app visibility, and browser failures. Sanitized events are written to Render logs and to a rotating local JSONL file; an owner can download the current file from **More → Download Diagnostics**. These records deliberately exclude filenames, media, prompts, access codes, secrets, and raw exception messages. The downloadable copy remains ephemeral on the hosted service, while the structured Render log provides evidence across application restarts subject to Render's log-retention window.

Reference-video analysis is saved before recipe synthesis. If OpenAI returns a recipe citation that does not match a real Twelve Labs segment, PBJ first applies only uniquely provable timestamp repairs, then gives the Learning Agent the exact validation failure for at most two structured citation-repair attempts. Retrying reuses the completed Twelve Labs analysis instead of uploading or analyzing the reference again.

The Blueprint expects `PBJ_ACCESS_CODE`, `PBJ_OWNER_CODE`, `OPENAI_API_KEY`, and `TWELVE_LABS_API_KEY` to be entered in Render. `PBJ_SESSION_SECRET` is generated by Render. Never add these values to Git or `render.yaml`.

## Product contracts

- [GOAL.md](GOAL.md) defines the product outcome and non-negotiable boundaries.
- [PROJECT_PLAN.md](PROJECT_PLAN.md) governs architecture, learning, stages, and gates.
- [UI_FLOW.md](UI_FLOW.md) defines the canonical screens and routes.
- [docs/TROY_FACELIFT_PLAN.md](docs/TROY_FACELIFT_PLAN.md) records the approved visual-source adaptation.
- [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) and [docs/third_party_sources.json](docs/third_party_sources.json) preserve external-source provenance.

## Tests

The project uses Python's built-in unittest discovery:

```sh
.venv/bin/python -m unittest discover -s tests -p 'test_*.py'
```

FFmpeg/ffprobe are required for real render tests. Tests that call external analysis or OpenAI services use fakes unless explicitly running an integration walkthrough.

## Core boundaries

- Use only project-supplied, permissioned media.
- Do not generate or fetch video, images, voices, music, sound effects, or B-roll.
- OpenAI returns structured proposals, never executable FFmpeg commands.
- FFmpeg executes validated decisions and never makes creative choices.
- Rendering success and user approval are separate events.
- Only an explicitly approved successful output becomes positive learning evidence.
