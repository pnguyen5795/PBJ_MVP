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

PBJ contains no OpenReel integration and no manual timeline editor. Recipes and provider machinery remain invisible in the normal user journey.

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

Local `.env` and project data are ignored by Git. Do not commit API keys, access codes, uploaded media, generated proxies, analyses, or rendered projects.

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
