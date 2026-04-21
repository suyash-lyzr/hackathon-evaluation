"""FastAPI server: landing page + evaluation API.

Endpoints
---------
GET  /                         — landing page (static HTML)
POST /api/parse                — upload xlsx, returns parsed rows (no scoring)
POST /api/evaluate             — upload xlsx, fetch app data, score all rows with OpenAI
GET  /api/app/{app_id}         — debug: return extracted context for one app
GET  /api/health               — health check
GET  /api/sample-excel         — download a sample submissions xlsx
"""
import asyncio
import os
import logging
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

load_dotenv()

from .bootstrap import bootstrap_runtime
from .db import fetch_app
from .extractor import build_evaluation_context
from .parser import parse_submissions_xlsx
from .scorer import score_submission, normalize_batch, RUBRIC
from . import store

bootstrap_runtime()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("hackathon-eval")

ROOT = Path(__file__).resolve().parent.parent
FRONTEND_DIR = ROOT / "frontend"
SAMPLE_XLSX = ROOT / "sample_submissions.xlsx"

app = FastAPI(title="Hackathon Evaluation", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def on_startup():
    await store.init_db()


@app.get("/api/health")
async def health():
    return {
        "ok": True,
        "db_url_configured": bool(os.getenv("DB_URL")),
        "openai_configured": bool(os.getenv("OPENAI_API_KEY")),
        "model": os.getenv("OPENAI_MODEL", "gpt-4.1"),
    }


@app.get("/api/rubric")
async def rubric():
    return {"rubric": RUBRIC, "max_total": 100}


@app.get("/api/app/{app_id}")
async def get_app_context(app_id: str):
    doc = await fetch_app(app_id)
    if not doc:
        raise HTTPException(status_code=404, detail=f"app not found: {app_id}")
    ctx = build_evaluation_context(doc)
    return ctx


@app.post("/api/parse")
async def parse(file: UploadFile = File(...)):
    contents = await file.read()
    try:
        rows = parse_submissions_xlsx(contents)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"could not parse xlsx: {e}")
    return {"count": len(rows), "submissions": rows}


async def _evaluate_one(submission: dict) -> dict:
    app_id = submission.get("app_id", "").strip()
    app_ctx = None
    fetch_error = None
    if app_id:
        try:
            doc = await fetch_app(app_id)
            if doc:
                app_ctx = build_evaluation_context(doc)
            else:
                fetch_error = "app_id not found in database"
        except Exception as e:
            fetch_error = f"db error: {type(e).__name__}: {e}"
    else:
        fetch_error = "no app_id provided"

    result = await score_submission(submission, app_ctx)

    return {
        "submission": submission,
        "app_context": app_ctx,
        "fetch_error": fetch_error,
        **result,
    }


@app.post("/api/evaluate")
async def evaluate(file: UploadFile = File(...)):
    if not os.getenv("OPENAI_API_KEY"):
        raise HTTPException(status_code=500, detail="OPENAI_API_KEY not configured in .env")

    contents = await file.read()
    try:
        submissions = parse_submissions_xlsx(contents)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"could not parse xlsx: {e}")

    if not submissions:
        raise HTTPException(status_code=400, detail="no rows found in xlsx")

    logger.info(f"Evaluating {len(submissions)} submissions")

    # Bounded concurrency so we don't hammer OpenAI or Mongo
    sem = asyncio.Semaphore(5)

    async def bounded(sub: dict):
        async with sem:
            return await _evaluate_one(sub)

    results = await asyncio.gather(*(bounded(s) for s in submissions))
    results = normalize_batch(results)
    # Final: sorted by rank
    results.sort(key=lambda r: r.get("rank", 9999))

    payload = {
        "count": len(results),
        "rubric": RUBRIC,
        "results": results,
    }
    run_id = await store.save_run(file.filename, payload)
    payload["run_id"] = run_id
    return payload


@app.get("/api/runs")
async def list_runs():
    return {"runs": await store.list_runs()}


@app.get("/api/apps-leaderboard")
async def apps_leaderboard(limit: int = 100):
    return {"apps": await store.apps_leaderboard(limit)}


@app.get("/api/runs/{run_id}")
async def get_run(run_id: int):
    r = await store.get_run(run_id)
    if not r:
        raise HTTPException(status_code=404, detail="run not found")
    return r


@app.delete("/api/runs/{run_id}")
async def delete_run(run_id: int):
    ok = await store.delete_run(run_id)
    if not ok:
        raise HTTPException(status_code=404, detail="run not found")
    return {"ok": True}


@app.get("/api/sample-excel")
async def sample_excel():
    if not SAMPLE_XLSX.exists():
        raise HTTPException(status_code=404, detail="sample xlsx not generated yet. Run: python -m backend.make_sample")
    return FileResponse(str(SAMPLE_XLSX), filename="sample_submissions.xlsx",
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


# Static frontend (mounted last so API routes win)
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8010"))
    uvicorn.run("backend.main:app", host="0.0.0.0", port=port, reload=True)
