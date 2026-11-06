# Repository Guidelines

## Project Structure & Module Organization
This monorepo has two apps. `apps/backend` is the FastAPI + LangGraph service; source lives in `src`, with routes in `api/routes`, agent logic in `agent`, models in `models`, database helpers in `db`, and utilities in `utils`. Backend tests are in `apps/backend/tests`. `apps/frontend` is the Vite + React app; UI code lives in `src/components`, `src/pages`, `src/store`, `src/api`, `src/assets`, and `src/test`.

## Code Flow
Frontend starts at `apps/frontend/src/main.tsx`, wrapping `AppRouter` with Google OAuth and React Router. `AppRouter.tsx` routes users to `/login`, `/login-success`, or protected `/chat`. `ProtectedRoute` verifies the stored Google token through `api/auth.ts` and `api/client.ts`; `store/useAuthStore.ts` persists auth state. `ChatPage.tsx` renders profile/logout controls, `WelcomeBanner`, and `ChatWindow`.

Backend starts at `apps/backend/src/main.py`. Lifespan builds the LangGraph graph with a Mongo checkpointer, then registers CORS and the `auth`, `chat`, `threads`, and `health` routers. `/chat` validates Google auth and prompt input, saves the user, streams graph node status events, saves the thread, and emits a final SSE payload. `agent/graph.py` routes `start_node` intent into search, purchase, ebook, audiobook, or audiobook validation nodes.

## Build, Test, and Development Commands
- `npm install`: install frontend workspace dependencies.
- `cd apps/backend && python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt`: create the backend env.
- `npm run dev:backend`: run FastAPI on `http://localhost:8000`.
- `npm run dev:frontend`: run Vite on `http://localhost:5173`.
- `npm run dev`: start backend and frontend together.
- `npm run test:backend`: run pytest.
- `npm run test:frontend`: run Vitest.
- `npm run build:frontend`: build the frontend.
- `cd apps/frontend && npm run typecheck`: check TypeScript.

## Coding Style & Naming Conventions
Backend targets Python 3.12 with Ruff, 100-character lines, sorted imports, and `E`, `F`, `W`, `I`, `UP` lint rules. Use 4-space indentation, `snake_case` for Python modules/functions, and `PascalCase` for Pydantic models. Frontend is TypeScript React; use `PascalCase` components and `camelCase` hooks/stores such as `useAuthStore`.

## Testing Guidelines
Backend tests use pytest with `asyncio_mode = auto`; discovery follows `test_*.py`, `Test*`, and `test_*`. CI runs `pytest --cov=src --cov-fail-under=60`. Frontend tests use Vitest, jsdom, and Testing Library. Cover route changes, agent nodes/tools, validation, auth flows, and user-facing React behavior.

## Commit, PR & Branching Guidelines
Use Conventional Commit-style subjects seen in history, such as `feat(frontend): add session persistence` or `ci(backend): adjust coverage threshold`. PRs should follow `.github/pull_request_template.md`, summarize scope, note breaking/API/env changes, and list exact tests run. Merge feature branches to `develop` first, then promote `develop` to `main`. When pulling from remote HEAD, rebase, for example `git pull --rebase origin develop`.

## Security & Configuration Tips
Copy `apps/backend/.env.example` and `apps/frontend/.env.example` to local `.env` files; never commit secrets. Backend config includes OpenAI, Tavily, HardCover, MongoDB, LangSmith, Google OAuth, fallback mirror, and frontend origin settings. Keep production behavior tied to explicit env config rather than local defaults.
