# Spotter ELD Assessment

Full-stack application built with:

- Django JSON API
- React + TypeScript
- OpenStreetMap
- ELD Log Generator
- HOS Trip Planner

## Local Development

Backend:

```bash
cd backend
venv/bin/python manage.py runserver 127.0.0.1:8000
```

Frontend:

```bash
cd frontend
npm install
npm run dev -- --host 127.0.0.1
```

Open `http://127.0.0.1:5173/`.

## Environment Variables

Frontend:

- `VITE_API_BASE_URL` - deployed Django API origin, for example `https://your-backend.example.com`. Leave unset locally to use the Vite `/api` proxy.

Backend:

- `DJANGO_SECRET_KEY` - required for production.
- `DEBUG` - use `false` in production.
- `ALLOWED_HOSTS` - comma-separated backend hosts, for example `your-backend.example.com`.
- `CORS_ALLOWED_ORIGINS` - comma-separated frontend origins, for example `https://your-vercel-app.vercel.app`.

## Validation

```bash
cd backend
venv/bin/python manage.py test planner
venv/bin/python manage.py check
```

```bash
cd frontend
npm run build
npm run lint
```
