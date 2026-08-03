---
name: ftk2-local-open-build-test
description: Set up the local environment for this FTK2 save editor, build/install it, run tests, and launch the GUI for manual testing.
version: 1.0.0
author: GitHub Copilot
license: MIT
platforms: [linux]
---
# FTK2 Local Open/Build/Test Skill

## When to use

Use this skill when you want to quickly verify the current project state on this machine by:
- creating or reusing the local virtual environment,
- installing/building the package,
- running tests,
- opening the GUI editor.

## Preconditions

- Workspace root is this repository.
- Python 3.10+ is installed.
- Linux desktop session is available for GUI launch.

## Commands

Run from repository root:

```bash
# 1) Create venv if missing
[ -d .venv ] || python -m venv .venv

# 2) Build/install project in editable mode
.venv/bin/python -m pip install -e .

# 3) Run tests
.venv/bin/python -m pytest -q

# 4) Launch GUI (manual test)
.venv/bin/ftk2-gui
```

## One-liner variant

```bash
[ -d .venv ] || python -m venv .venv && .venv/bin/python -m pip install -e . && .venv/bin/python -m pytest -q && .venv/bin/ftk2-gui
```

## Expected results

- Tests report all passing.
- GUI window opens and allows selecting/reading `.ftk2` save files.

## Notes

- If the environment is externally managed (PEP 668), always use `.venv`.
- Close the GUI window to end the foreground process.
