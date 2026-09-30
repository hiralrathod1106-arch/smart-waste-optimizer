"""Fill-level forecasting (shared by the API and the Streamlit offline fallback)."""
from datetime import date

from sklearn.linear_model import LinearRegression


def _days(history):
    """x-axis = real calendar days since the first reading (not row numbers)."""
    d0 = date.fromisoformat(str(history[0]["date"])[:10])
    return [[(date.fromisoformat(str(h["date"])[:10]) - d0).days] for h in history]


def forecast_from_history(history, horizon=3):
    """Linear regression on (day -> fill). Returns predictions and a leave-last-out MAE."""
    x = _days(history)
    y = [float(h["fill_level"]) for h in history]
    model = LinearRegression().fit(x, y)
    last = x[-1][0]
    preds = [max(0.0, min(100.0, round(float(p), 2)))
             for p in model.predict([[last + i] for i in range(1, horizon + 1)])]
    mae = None
    if len(y) >= 4:  # one-step-ahead backtest: train on all but last k points, predict the next
        errs = []
        for i in range(3, len(y)):
            m = LinearRegression().fit(x[:i], y[:i])
            errs.append(abs(float(m.predict([x[i]])[0]) - y[i]))
        mae = round(sum(errs) / len(errs), 2)
    slope = float(model.coef_[0])
    days_to_full = None
    if slope > 0 and y[-1] < 100:
        days_to_full = round((100 - y[-1]) / slope, 1)
    return preds, mae, days_to_full


COLLECT_AT = 80
CRITICAL_AT = 90
_SEV_ORDER = {"CRITICAL": 0, "FULL": 1, "UPCOMING": 2}


def classify_alerts(bins, history):
    """Collector alerts for every uncollected bin.
    CRITICAL >= 90% now | FULL >= 80% now | UPCOMING = forecast reaches 80% within 3 readings/days."""
    by_bin = {}
    for h in history:
        by_bin.setdefault(h["bin_id"], []).append(h)
    alerts = []
    for b in bins:
        if b.get("status") == "Collected":
            continue
        level = float(b["fill_level"])
        rows = by_bin.get(b["bin_id"], [])
        preds = forecast_from_history(rows)[0] if len(rows) >= 2 else []
        eta = next((i + 1 for i, p in enumerate(preds) if p >= COLLECT_AT), None)
        if level >= CRITICAL_AT:
            sev, msg = "CRITICAL", f"{level:.0f}% full - collect immediately"
        elif level >= COLLECT_AT:
            sev, msg = "FULL", f"{level:.0f}% full - needs collection"
        elif eta:
            sev, msg = "UPCOMING", f"{level:.0f}% now, forecast to pass {COLLECT_AT}% in {eta} day(s)"
        else:
            continue
        alerts.append({"bin_id": b["bin_id"], "location": b["location"], "latitude": b["latitude"],
                       "longitude": b["longitude"], "fill_level": level, "severity": sev,
                       "eta_days": eta, "message": msg})
    alerts.sort(key=lambda a: (_SEV_ORDER[a["severity"]], -a["fill_level"]))
    return alerts
