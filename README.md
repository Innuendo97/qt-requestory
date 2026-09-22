# qtRequestory

Desktop tool (Windows) that mirrors the daily nginx request logs of a document-generator
service, indexes them, and lets you find and extract the JSON body of any call by FDI
(correlation id) and/or template key.

Status: v1 under construction. See `docs/DESIGN-core.md` and `docs/DESIGN-ui.md`.

## Development

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[ui,dev]"
.venv\Scripts\python -m pytest
.venv\Scripts\python -m qtrequestory            # GUI
.venv\Scripts\python -m qtrequestory --sync     # headless sync
```

Environment URLs are never committed: copy `environments.example.json` to
`environments.json` (git-ignored) next to the executable, or enter them in the first-run
wizard.
