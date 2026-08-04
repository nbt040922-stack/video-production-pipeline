# Video Production Pipeline

Parent repository for a modular video-production workflow. It coordinates two production-ready engines without merging or duplicating their code or Git history.

## Purpose

The planned pipeline turns a YouTube URL into a composed final video:

```text
YouTube URL -> Downloader -> Hook Engine -> Review Engine -> Composer -> Final Video
```

- **Hook Engine** produces `final_hook.mp4`.
- **Review Engine** produces `review.mp4`.
- **Composer** will combine those outputs into the final video.
- **Orchestrator** will coordinate the stages in a future implementation.

See [docs/Architecture.md](docs/Architecture.md) for component boundaries and data flow.

## Repository layout

```text
video-production-pipeline/
|-- apps/
|   `-- orchestrator/
|-- composer/
|-- config/
|-- docs/
|   `-- Architecture.md
|-- engines/
|   |-- hook-engine/       # Git submodule
|   `-- review-engine/     # Git submodule
|-- tests/
|-- workspace/             # Ignored runtime files
|-- .gitignore
|-- .gitmodules
|-- README.md
|-- setup.ps1
`-- setup.sh
```

## Workspace

`workspace/` is the handoff area for downloaded media, intermediate files, logs, and generated videos. Its contents are intentionally ignored by Git. Keep source code and durable configuration outside it.

## Submodules

The engine repositories remain independent and retain their own histories:

- `engines/hook-engine`: <https://github.com/nbt040922-stack/AI_hook_engine.git>
- `engines/review-engine`: <https://github.com/nbt040922-stack/video-short-workflow.git>

Clone everything in one command:

```bash
git clone --recursive <video-production-pipeline-url>
```

If the parent was cloned without `--recursive`, initialize the engines afterward:

```bash
git submodule update --init --recursive
```

## Development workflow

1. Clone with submodules.
2. Run `./setup.sh` on macOS/Linux or `./setup.ps1` in PowerShell.
3. Develop each engine in its own repository and branch.
4. Commit parent-project changes separately from engine changes.
5. Keep generated media and temporary files under `workspace/`.

The setup scripts create `.venv`, initialize submodules, and install dependency manifests that the engines provide. The Hook Engine currently has no root dependency manifest, so the scripts make no assumptions about additional packages for it.

## Updating the Hook Engine

```bash
cd engines/hook-engine
git switch main
git pull --ff-only
cd ../..
git add engines/hook-engine
git commit -m "chore: update hook engine"
```

## Updating the Review Engine

```bash
cd engines/review-engine
git switch main
git pull --ff-only
cd ../..
git add engines/review-engine
git commit -m "chore: update review engine"
```

Updating a submodule changes only the commit pointer stored by this parent repository. Engine code changes must be committed and pushed in the engine's own repository first.

## Future orchestrator

No orchestrator is implemented yet. Its future entry point will be run as:

```bash
python -m apps.orchestrator
```
## Frontend prototype

The desktop-first React prototype runs entirely in mock mode. It does not call either engine or any external media service.

```bash
npm install
npm run dev
```

Validation commands:

```bash
npm test
npm run build
```

See [docs/FRONTEND_ARCHITECTURE.md](docs/FRONTEND_ARCHITECTURE.md) for the component model and future backend integration points.

No screenshot is stored yet. If one is added later, use `docs/screenshots/frontend.png`.
