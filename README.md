# Book Ninja Monorepo

This repository is a monorepo with separate backend and frontend apps.

For daily cluster checks and application debugging, see
[Common commands](docs/COMMON_COMMANDS.md). Infrastructure setup is documented
in the [manual Floci provisioning runbook](docs/FLOCI_MANUAL_PROVISIONING.md).

## Repository Structure

- `apps/backend` - FastAPI + LangGraph backend
- `apps/frontend` - Vite + React frontend

## Setup (One Time)

### 1. Install frontend workspace dependencies

```bash
npm install
```

### 2. Set up backend Python environment

```bash
cd apps/backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Then fill the values in `apps/backend/.env`.

## Run Apps Separately

### Start backend only

```bash
npm run dev:backend
```

Backend runs at `http://localhost:8000`.

### Start frontend only

```bash
npm run dev:frontend
```

Frontend runs at `http://localhost:5173`.

## Run Backend + Frontend Together

```bash
npm run dev
```
