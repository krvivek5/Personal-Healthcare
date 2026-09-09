# Personal Healthcare Intelligence

> Foundational personal health experience that unifies health information, establishes longitudinal understanding, and provides context-aware intelligence.

## Project Structure

```text
/
├── backend/    # FastAPI Python service (domain logic, auth validation, data isolation)
├── frontend/   # React + TypeScript + Vite + Vitest (reference web client)
├── doc/        # Core product concepts, architecture (DESIGN.md), roadmap, specs
├── phases/     # Phase specifications and milestones (PHASE-01.md)
└── docker-compose.yml # Local infrastructure (PostgreSQL)
```

## Getting Started

### Prerequisites
- Python >= 3.11
- Node.js >= 20, npm
- Docker (for local PostgreSQL)

### 1. Database
Start local PostgreSQL:
```bash
docker compose up -d
```

### 2. Backend Setup
```bash
cd backend
python -m venv .venv
# On Windows:
.venv\Scripts\activate
# On Unix:
source .venv/bin/activate

pip install -r requirements.txt
cp .env.example .env

# Run tests
pytest

# Linting and formatting check
ruff check .

# Start development server
uvicorn app.main:app --reload --port 8000
```

### 3. Frontend Setup
```bash
cd frontend
npm install
cp .env.example .env

# Run tests
npm test

# Linting
npm run lint

# Start Vite dev server
npm run dev
```
