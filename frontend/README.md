# GradeOps Frontend

React + Vite + TypeScript + Tailwind. Talks to the FastAPI backend at `VITE_API_URL` (default `http://localhost:8000`).

## Quick start

```bash
cd frontend
npm install
npm run dev
```

Vite serves on http://localhost:5173. Make sure the backend is running:

```bash
# from project root
docker compose up
```

## Sign in

Use the seeded dev accounts (after running `docker compose exec backend python -m scripts.seed`):

| Role       | Email                       | Password         |
| ---------- | --------------------------- | ---------------- |
| INSTRUCTOR | instructor@gradeops.dev     | instructor123    |
| TA         | ta@gradeops.dev             | ta12345678       |

## Routes

| Path     | Access            | What                                                         |
| -------- | ----------------- | ------------------------------------------------------------ |
| `/login` | public            | Email + password sign-in                                     |
| `/`      | authenticated     | Role-aware home page                                         |

## Layout

```
frontend/
├── src/
│   ├── api/client.ts         # axios + token storage + login/me
│   ├── auth/AuthContext.tsx  # in-app auth state
│   ├── auth/PrivateRoute.tsx # gates routes by auth + optional role
│   ├── pages/LoginPage.tsx
│   └── pages/HomePage.tsx
├── vite.config.ts
├── tailwind.config.js
└── package.json
```

## Production build

```bash
npm run build       # outputs dist/
npm run preview     # serves dist/ locally
```
