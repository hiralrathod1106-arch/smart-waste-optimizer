"""Smart Waste Collection Optimizer - FastAPI backend (Supabase as database).

Run locally (from the project root):
    uvicorn backend.main:app --reload --port 8001
Render start command (root directory = repo root):
    uvicorn backend.main:app --host 0.0.0.0 --port $PORT
"""
import logging
import os
import time
from collections import defaultdict
from datetime import date, datetime, timezone
from functools import lru_cache
from typing import Optional

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, Field
from forecasting import forecast_from_history

# config.env is only used locally; on Render the values come from Environment variables.
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.env"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("waste-api")

COLLECT_THRESHOLD = 80
CRITICAL_THRESHOLD = 90

app = FastAPI(title="Smart Waste Collection Optimizer", version="2.0")


# ---------------------------------------------------------------- database
@lru_cache(maxsize=1)
def get_db():
    """Create the Supabase client lazily so a missing key gives a clear 503
    instead of crashing the whole app at import time."""
    url, key = os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY")
    if not url or not key:
        raise HTTPException(503, "SUPABASE_URL / SUPABASE_KEY are not configured on the server")
    from supabase import create_client
    return create_client(url, key)


def require_api_key(x_api_key: Optional[str] = Header(default=None)):
    """Write endpoints need the X-API-Key header when API_KEY is set in the environment."""
    expected = os.getenv("API_KEY")
    if expected and x_api_key != expected:
        raise HTTPException(401, "Invalid or missing X-API-Key")


# ---------------------------------------------------------------- observability
_metrics = {"started": time.time(), "requests": 0, "errors": 0,
            "by_path": defaultdict(int), "latency_ms_total": 0.0}


@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        _metrics["errors"] += 1
        log.exception("unhandled error on %s %s", request.method, request.url.path)
        raise
    ms = (time.perf_counter() - start) * 1000
    _metrics["requests"] += 1
    _metrics["latency_ms_total"] += ms
    _metrics["by_path"][request.url.path.split("/")[1] or "/"] += 1
    if response.status_code >= 500:
        _metrics["errors"] += 1
    log.info("%s %s -> %s (%.0f ms)", request.method, request.url.path, response.status_code, ms)
    return response


@app.get("/")
def home():
    return {"message": "Smart Waste Collection Optimizer API is running", "docs": "/docs"}


@app.get("/health")
def health(db=Depends(get_db)):
    db.table("bins").select("bin_id").limit(1).execute()
    return {"status": "ok", "database": "connected"}


@app.get("/metrics")
def metrics():
    n = max(_metrics["requests"], 1)
    return {"uptime_s": round(time.time() - _metrics["started"]), "requests": _metrics["requests"],
            "errors": _metrics["errors"], "avg_latency_ms": round(_metrics["latency_ms_total"] / n, 1),
            "requests_by_endpoint": dict(_metrics["by_path"])}


# ---------------------------------------------------------------- bins
@app.get("/bins")
def get_bins(db=Depends(get_db)):
    return {"bins": db.table("bins").select("*").execute().data}


@app.get("/bins/{bin_id}")
def get_bin(bin_id: str, db=Depends(get_db)):
    rows = db.table("bins").select("*").eq("bin_id", bin_id).execute().data
    if not rows:
        raise HTTPException(404, f"Bin {bin_id} not found")
    return {"bin": rows[0]}


@app.get("/dashboard")
def get_dashboard(db=Depends(get_db)):
    bins = db.table("bins").select("*").execute().data
    status = {s["bin_id"]: s["status"] for s in db.table("collection_status").select("*").execute().data}
    return {"bins": [{**b, "status": status.get(b["bin_id"], "Pending")} for b in bins]}


@app.get("/statuses")
def get_statuses(db=Depends(get_db)):
    return {"statuses": db.table("collection_status").select("*").execute().data}


@app.get("/smart-alerts")
def smart_alerts(db=Depends(get_db)):
    """Current + predicted overflow alerts with area names, most urgent first (used by the dashboard)."""
    bins = get_dashboard(db)["bins"]
    history = db.table("fill_history").select("*").order("date").execute().data
    alerts = classify_alerts(bins, history)
    return {"count": len(alerts), "alerts": alerts}



# ---------------------------------------------------------------- history & sensor intake
@app.get("/fill-history")
def get_all_fill_history(db=Depends(get_db)):
    """All histories in ONE call (the old app made one request per bin)."""
    return {"history": db.table("fill_history").select("*").order("date").execute().data}


@app.get("/fill-history/{bin_id}")
def get_fill_history(bin_id: str, db=Depends(get_db)):
    rows = db.table("fill_history").select("*").eq("bin_id", bin_id).order("date").execute().data
    return {"bin_id": bin_id, "history": rows}


class Reading(BaseModel):
    """One sensor reading (from the ESP32 / simulator)."""
    bin_id: str = Field(min_length=1, max_length=32)
    fill_level: float = Field(ge=0, le=100)
    battery_pct: Optional[float] = Field(default=None, ge=0, le=100)
    date: Optional[date] = None


@app.post("/readings", status_code=201, dependencies=[Depends(require_api_key)])
def ingest_reading(reading: Reading, db=Depends(get_db)):
    """Event intake: validate -> store in fill_history -> refresh the bin's current fill level."""
    if not db.table("bins").select("bin_id").eq("bin_id", reading.bin_id).execute().data:
        raise HTTPException(404, f"Unknown bin {reading.bin_id}")
    day = (reading.date or datetime.now(timezone.utc).date()).isoformat()
    db.table("fill_history").insert({
        "bin_id": reading.bin_id, "date": day, "fill_level": reading.fill_level,
        "battery_pct": reading.battery_pct, "source": "sensor"}).execute()
    db.table("bins").update({"fill_level": reading.fill_level}).eq("bin_id", reading.bin_id).execute()
    if reading.fill_level >= COLLECT_THRESHOLD:  # a new overflow event re-opens the collection task
        db.table("collection_status").upsert({"bin_id": reading.bin_id, "status": "Pending"}).execute()
    log.info("reading %s=%.1f%% battery=%s", reading.bin_id, reading.fill_level, reading.battery_pct)
    return {"stored": True, "bin_id": reading.bin_id, "fill_level": reading.fill_level,
            "alert": reading.fill_level >= CRITICAL_THRESHOLD}


# ---------------------------------------------------------------- collection workflow
@app.put("/bins/{bin_id}/collect", dependencies=[Depends(require_api_key)])
def mark_bin_collected(bin_id: str, db=Depends(get_db)):
    bins = db.table("bins").select("fill_level").eq("bin_id", bin_id).execute().data
    if not bins:
        raise HTTPException(404, f"Bin {bin_id} not found")
    row = db.table("collection_status").upsert({"bin_id": bin_id, "status": "Collected"}).execute()
    db.table("service_history").insert({
        "bin_id": bin_id, "fill_level_at_collection": bins[0]["fill_level"],
        "collected_at": datetime.now(timezone.utc).isoformat()}).execute()  # audit trail
    log.info("bin %s collected", bin_id)
    return {"message": f"{bin_id} marked as Collected", "status": row.data[0] if row.data else None}


@app.get("/service-history")
def service_history(bin_id: Optional[str] = None, db=Depends(get_db)):
    q = db.table("service_history").select("*").order("collected_at", desc=True)
    if bin_id:
        q = q.eq("bin_id", bin_id)
    return {"history": q.limit(200).execute().data}


# ---------------------------------------------------------------- forecasting (logic in forecasting.py)
@app.get("/forecast/{bin_id}")
def get_forecast(bin_id: str, db=Depends(get_db)):
    history = db.table("fill_history").select("*").eq("bin_id", bin_id).order("date").execute().data
    if len(history) < 2:
        raise HTTPException(422, f"Need at least 2 readings to forecast {bin_id} (have {len(history)})")
    preds, mae, days_to_full = forecast_from_history(history)
    return {
        "bin_id": bin_id, "historical_data": history, "model": "LinearRegression",
        "mae_percentage_points": mae, "days_until_full": days_to_full,
        "forecast": [{"day": d, "predicted_fill": p} for d, p in zip(["Next Day", "Day 2", "Day 3"], preds)],
    }
