# Learn System API (FastAPI + Async SQLAlchemy + PostgreSQL)

## Quickstart

1. Create and activate venv

```powershell
python -m venv .venv
. .\.venv\Scripts\Activate.ps1
```

2. Install dependencies

```powershell
pip install -r requirements.txt
```

3. Configure environment

Copy `.env.example` to `.env` and update values:

```powershell
Copy-Item -Path .env.example -Destination .env
```

Set `DATABASE_URL` to your PostgreSQL instance, e.g.:

```
postgresql+asyncpg://postgres:postgres@localhost:5432/learn_system
```

4. Run the app

```powershell
uvicorn app.main:app --reload --port 8000
```

Open http://127.0.0.1:8000/docs

## Models Overview

- User (teacher/student) 1-1 UserProfile
- Teacher 1-N ExamPaper; ExamPaper 1-N Question
- Student N-Attempts ExamAttempt; Attempt 1-N ExamAnswer

Virtual foreign keys used (no DB-level FK constraints), with indices and unique constraints for integrity.
