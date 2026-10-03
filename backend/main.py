"""Smart Waste Collection Optimizer - FastAPI backend (Supabase as database).

Run locally (from the project root):
    uvicorn backend.main:app --reload --port 8001
Render start command (root directory = repo root):
    uvicorn backend.main:app --host 0.0.0.0 --port $PORT
"""
import datetime as dt
import hmac
import logging
import os
import time
import urllib.parse
import urllib.request
from collections import defaultdict, deque
from datetime import datetime, timezone
from functools import lru_cache
from typing import Optional

from dotenv import load_dotenv
from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from forecasting import classify_alerts, evaluation_table, forecast_from_history

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


# ---------------------------------------------------------------- security
def require_api_key(x_api_key: Optional[str] = Header(default=None)):
    """Write endpoints need the X-API-Key header when API_KEY is set (constant-time comparison)."""
    expected = os.getenv("API_KEY")
    if expected and not hmac.compare_digest(x_api_key or "", expected):
        add_event("WARN", "rejected request with invalid API key")
        raise HTTPException(401, "Invalid or missing X-API-Key")


_hits = defaultdict(deque)


def rate_limit(request: Request, limit: int = 60, window_s: int = 60):
    """Very small in-memory rate limiter for write endpoints: 60 writes / minute / client."""
    ip = request.client.host if request.client else "unknown"
    q, now = _hits[ip], time.time()
    while q and now - q[0] > window_s:
        q.popleft()
    if len(q) >= limit:
        add_event("WARN", f"rate limit hit by {ip}")
        raise HTTPException(429, "Too many requests - slow down")
    q.append(now)


# CORS: only the origins you list in ALLOWED_ORIGINS (comma separated); default = none (server-to-server only)
app.add_middleware(CORSMiddleware, allow_origins=[o for o in os.getenv("ALLOWED_ORIGINS", "").split(",") if o],
                   allow_methods=["GET", "POST", "PUT", "DELETE"], allow_headers=["X-API-Key", "Content-Type"])


@app.middleware("http")
async def security_headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Cache-Control"] = "no-store"
    return resp


# ---------------------------------------------------------------- failure handling + event log
_events = deque(maxlen=200)   # recent warnings/errors, shown on the System Health page


def add_event(level, msg):
    _events.appendleft({"time": datetime.now(timezone.utc).isoformat(timespec="seconds"), "level": level, "message": msg})
    log.log(logging.ERROR if level == "ERROR" else logging.WARNING if level == "WARN" else logging.INFO, msg)


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    """Any crash becomes a clean JSON 500 (no stack trace leaked) and is recorded in /events."""
    add_event("ERROR", f"{request.method} {request.url.path} -> {type(exc).__name__}: {str(exc)[:160]}")
    return JSONResponse(status_code=500, content={"detail": "Internal server error - see /events"})


def audit(db, action, bin_id=None, detail=""):
    """Audit trail row in Supabase. Best effort: a failure here must never break the real action."""
    try:
        db.table("audit_log").insert({"action": action, "bin_id": bin_id, "detail": detail[:300]}).execute()
    except Exception as e:  # table missing / DB hiccup
        add_event("WARN", f"audit write failed ({action}): {type(e).__name__}")


def notify(text):
    """Push an overflow alert to Telegram (optional). Needs TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID env vars."""
    token, chat = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat:
        return False
    try:
        body = urllib.parse.urlencode({"chat_id": chat, "text": text}).encode()
        urllib.request.urlopen(f"https://api.telegram.org/bot{token}/sendMessage", data=body, timeout=5)
        return True
    except Exception as e:
        add_event("WARN", f"telegram notification failed: {type(e).__name__}")
        return False


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
    t = time.perf_counter()
    db.table("bins").select("bin_id").limit(1).execute()
    return {"status": "ok", "database": "connected", "db_latency_ms": round((time.perf_counter() - t) * 1000),
            "notifications": "telegram" if os.getenv("TELEGRAM_BOT_TOKEN") else "in-app only",
            "api_key_required": bool(os.getenv("API_KEY"))}


@app.get("/events")
def events():
    """Recent warnings and errors (failure handling evidence)."""
    return {"events": list(_events)}


@app.get("/audit-log")
def audit_log(limit: int = 100, db=Depends(get_db)):
    return {"log": db.table("audit_log").select("*").order("created_at", desc=True).limit(min(limit, 500)).execute().data}


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


@app.get("/alerts")
def get_alerts(threshold: int = CRITICAL_THRESHOLD, db=Depends(get_db)):
    """Overflow alerts: bins at/above the threshold that are not yet collected."""
    bins = get_dashboard(db)["bins"]
    alerts = [
        {**b, "level": "CRITICAL" if b["fill_level"] >= CRITICAL_THRESHOLD else "HIGH"}
        for b in bins if b["fill_level"] >= threshold and b["status"] != "Collected"
    ]
    return {"threshold": threshold, "count": len(alerts), "alerts": alerts}


# ---------------------------------------------------------------- history & sensor intake
@app.get("/smart-alerts")
def smart_alerts(db=Depends(get_db)):
    """Current + predicted overflow alerts with area names, most urgent first (used by the dashboard)."""
    bins = get_dashboard(db)["bins"]
    history = db.table("fill_history").select("*").order("date").execute().data
    alerts = classify_alerts(bins, history)
    return {"count": len(alerts), "alerts": alerts}


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
    date: Optional[dt.date] = None


@app.post("/readings", status_code=201, dependencies=[Depends(require_api_key), Depends(rate_limit)])
def ingest_reading(reading: Reading, background: BackgroundTasks, db=Depends(get_db)):
    """Event intake: validate -> store in fill_history -> refresh the bin -> push alert when it crosses 90%."""
    rows = db.table("bins").select("*").eq("bin_id", reading.bin_id).execute().data
    if not rows:
        raise HTTPException(404, f"Unknown bin {reading.bin_id}")
    before = float(rows[0]["fill_level"] or 0)
    day = (reading.date or datetime.now(timezone.utc).date()).isoformat()
    db.table("fill_history").insert({
        "bin_id": reading.bin_id, "date": day, "fill_level": reading.fill_level,
        "battery_pct": reading.battery_pct, "source": "sensor"}).execute()
    db.table("bins").update({"fill_level": reading.fill_level}).eq("bin_id", reading.bin_id).execute()
    if reading.fill_level >= COLLECT_THRESHOLD:  # a new overflow event re-opens the collection task
        db.table("collection_status").upsert({"bin_id": reading.bin_id, "status": "Pending"}).execute()
    crossed = before < CRITICAL_THRESHOLD <= reading.fill_level      # notify once, when it crosses
    if crossed:
        add_event("ALERT", f"{reading.bin_id} ({rows[0]['location']}) reached {reading.fill_level:.0f}%")
        background.add_task(notify, f"OVERFLOW ALERT: {reading.bin_id} at {rows[0]['location']} is "
                                    f"{reading.fill_level:.0f}% full. Please collect now.")
    if reading.battery_pct is not None and reading.battery_pct < 20:
        add_event("WARN", f"{reading.bin_id} sensor battery low ({reading.battery_pct:.0f}%)")
    log.info("reading %s=%.1f%% battery=%s", reading.bin_id, reading.fill_level, reading.battery_pct)
    return {"stored": True, "bin_id": reading.bin_id, "fill_level": reading.fill_level,
            "alert": reading.fill_level >= CRITICAL_THRESHOLD, "notified": crossed}


@app.post("/notify-test", dependencies=[Depends(require_api_key), Depends(rate_limit)])
def notify_test():
    ok = notify("Smart Waste Optimizer: test notification - alerts are working.")
    return {"sent": ok, "hint": None if ok else "Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID on Render"}


# ---------------------------------------------------------------- bin registry (create / update / delete)
class BinIn(BaseModel):
    bin_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,32}$")
    location: str = Field(min_length=1, max_length=80)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    capacity: int = Field(default=100, ge=1, le=10000)
    fill_level: float = Field(default=0, ge=0, le=100)


class BinUpdate(BaseModel):
    location: Optional[str] = Field(default=None, min_length=1, max_length=80)
    latitude: Optional[float] = Field(default=None, ge=-90, le=90)
    longitude: Optional[float] = Field(default=None, ge=-180, le=180)
    capacity: Optional[int] = Field(default=None, ge=1, le=10000)
    fill_level: Optional[float] = Field(default=None, ge=0, le=100)


@app.post("/bins", status_code=201, dependencies=[Depends(require_api_key), Depends(rate_limit)])
def create_bin(b: BinIn, db=Depends(get_db)):
    if db.table("bins").select("bin_id").eq("bin_id", b.bin_id).execute().data:
        raise HTTPException(409, f"Bin {b.bin_id} already exists")
    db.table("bins").insert(b.model_dump()).execute()
    db.table("collection_status").upsert({"bin_id": b.bin_id, "status": "Pending"}).execute()
    db.table("fill_history").insert({"bin_id": b.bin_id, "date": datetime.now(timezone.utc).date().isoformat(),
                                     "fill_level": b.fill_level, "source": "registry"}).execute()
    audit(db, "bin_created", b.bin_id, f"{b.location} ({b.latitude},{b.longitude})")
    return {"created": b.bin_id}


@app.put("/bins/{bin_id}", dependencies=[Depends(require_api_key), Depends(rate_limit)])
def update_bin(bin_id: str, b: BinUpdate, db=Depends(get_db)):
    changes = {k: v for k, v in b.model_dump().items() if v is not None}
    if not changes:
        raise HTTPException(422, "Nothing to update")
    if not db.table("bins").select("bin_id").eq("bin_id", bin_id).execute().data:
        raise HTTPException(404, f"Bin {bin_id} not found")
    db.table("bins").update(changes).eq("bin_id", bin_id).execute()
    audit(db, "bin_updated", bin_id, str(changes))
    return {"updated": bin_id, "changes": changes}


@app.delete("/bins/{bin_id}", dependencies=[Depends(require_api_key), Depends(rate_limit)])
def delete_bin(bin_id: str, db=Depends(get_db)):
    if not db.table("bins").select("bin_id").eq("bin_id", bin_id).execute().data:
        raise HTTPException(404, f"Bin {bin_id} not found")
    for t in ("fill_history", "collection_status", "service_history"):  # children first (foreign keys)
        db.table(t).delete().eq("bin_id", bin_id).execute()
    db.table("bins").delete().eq("bin_id", bin_id).execute()
    audit(db, "bin_deleted", bin_id)
    return {"deleted": bin_id}


# ---------------------------------------------------------------- collection workflow
@app.put("/bins/{bin_id}/collect", dependencies=[Depends(require_api_key), Depends(rate_limit)])
def mark_bin_collected(bin_id: str, db=Depends(get_db)):
    bins = db.table("bins").select("fill_level").eq("bin_id", bin_id).execute().data
    if not bins:
        raise HTTPException(404, f"Bin {bin_id} not found")
    row = db.table("collection_status").upsert({"bin_id": bin_id, "status": "Collected"}).execute()
    db.table("service_history").insert({
        "bin_id": bin_id, "fill_level_at_collection": bins[0]["fill_level"],
        "collected_at": datetime.now(timezone.utc).isoformat()}).execute()  # audit trail
    audit(db, "bin_collected", bin_id, f"fill {bins[0]['fill_level']}%")
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


# ---------------------------------------------------------------- evaluation metrics (tables for the Results page)
@app.get("/evaluation")
def evaluation(db=Depends(get_db)):
    bins = get_dashboard(db)["bins"]
    history = db.table("fill_history").select("*").order("date").execute().data
    service = db.table("service_history").select("*").execute().data
    table = evaluation_table(bins, history)
    maes = [r["mae_pts"] for r in table if r["mae_pts"] is not None]
    done = len(service)
    safe = sum(1 for r in service if float(r["fill_level_at_collection"] or 0) < 100)
    return {
        "per_bin": table,
        "summary": {
            "avg_forecast_mae_pts": round(sum(maes) / len(maes), 2) if maes else None,
            "bins_overflowing_now": sum(1 for b in bins if float(b["fill_level"]) >= 100),
            "collections_done": done,
            "overflow_prevention_pct": round(100 * safe / done, 1) if done else None,
            "sensor_readings": sum(1 for h in history if h.get("source") == "sensor"),
        },
    }
