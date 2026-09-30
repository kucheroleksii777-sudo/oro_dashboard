# ORO dashboard

Python (Django) API backend + React TypeScript frontend with Material UI.

App data (keys, race extras) is stored in MongoDB. Django still uses a local SQLite file only for its own tables.

## Run (development)

MongoDB:

```bash
cd oro_dashboard
docker compose up -d
```

Backend:

```bash
cd oro_dashboard
source .venv/bin/activate
python backend/manage.py runserver 0.0.0.0:8000
```

Frontend (in another terminal):

```bash
cd oro_dashboard/frontend
npm run dev
```

Open http://65.108.196.50:5173/

The Vite dev server proxies `/api` to Django on port 8000. Vite hot-reloads the UI when you save files.
# oro_dashboard
