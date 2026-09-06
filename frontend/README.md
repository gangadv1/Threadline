# Threadline Frontend Prototype

## Run it

**Quickest (no backend needed):** open `index.html` directly in a browser
(double-click it, or drag it into a tab). It runs entirely on local mock
data and every screen works.

**Connected to the real backend:** start the backend first (see
`backend/README.md` — `uvicorn app.main:app --reload`, runs on
`http://127.0.0.1:8000`), then serve this folder instead of opening the
file directly:

```bash
cd frontend
python3 -m http.server 5500
```

Open `http://localhost:5500/`. On load it checks `/health`, then fetches
or creates its demo goal on the backend and runs a real planning cycle.
A badge in the top-right corner shows which mode you're in:

- **● Live backend** — every action (status change, approve/reject,
  "reject transcript", "pull deadline forward") is a real API call to
  the FastAPI backend, and you'll see the actual feasibility engine's
  risk banner update.
- **○ Demo data (backend offline)** — same screens, but everything is
  computed locally in JS. Useful if the backend isn't running, e.g. for
  a demo on a machine without Python set up.

If `API_BASE` at the top of the `<script>` tag doesn't match where your
backend is running, edit that one line.

Opening `index.html` directly via `file://` while the backend is running
should also work (the backend allows the `null` origin browsers send for
local files), but serving it is more reliable across browsers.
