"""Smart Waste Collection Optimizer - Streamlit frontend.

Talks to the FastAPI backend on Render (which stores data in Supabase).
Set API_URL / API_KEY in .streamlit/secrets.toml (local) or Streamlit Cloud > Secrets.
"""
import os

import folium
import pandas as pd
import requests
import streamlit as st
from streamlit_folium import st_folium

import optimizer as opt

st.set_page_config(page_title="Smart Waste Collection Optimizer", page_icon="🗑️", layout="wide")


# ------------------------------------------------------------ settings
def _secret(name, default=""):
    try:
        return st.secrets[name]
    except Exception:  # no secrets file
        return os.getenv(name, default)


API_URL = _secret("API_URL", "http://127.0.0.1:8001").rstrip("/")   # was hard-coded to 127.0.0.1 before
API_KEY = _secret("API_KEY", "")
HEADERS = {"X-API-Key": API_KEY} if API_KEY else {}
DEPOT_LAT, DEPOT_LON = opt.DEPOT
COLLECT_AT, CRITICAL_AT = 80, 90


# ------------------------------------------------------------ API helpers
@st.cache_data(ttl=20, show_spinner=False)
def api_get(path):
    """GET with retries: Render free instances sleep and need ~30-50 s to wake up."""
    last = None
    for _ in range(3):
        try:
            r = requests.get(f"{API_URL}{path}", headers=HEADERS, timeout=45)
            r.raise_for_status()
            return r.json()
        except requests.RequestException as e:
            last = e
    raise RuntimeError(str(last))


def api_send(method, path, payload=None):
    """POST/PUT/DELETE. Raises RuntimeError with the server's message (e.g. 'Bin BIN011 already exists')."""
    try:
        r = requests.request(method, f"{API_URL}{path}", headers=HEADERS, json=payload, timeout=45)
    except requests.RequestException as e:
        raise RuntimeError(f"Backend unreachable: {e}")
    if not r.ok:
        try:
            msg = r.json().get("detail", r.text)
        except Exception:
            msg = r.text
        raise RuntimeError(f"{r.status_code}: {msg}")
    api_get.clear()  # refresh cached data
    return r.json()


def api_put(path):
    return api_send("PUT", path)


@st.cache_data(show_spinner=False)
def load_csv(name):
    return pd.read_csv(os.path.join("data", name))


def load_bins():
    """Returns (dataframe, mode). Falls back to the CSV demo data if the API is unreachable."""
    try:
        with st.spinner("Contacting backend (Render may take up to a minute to wake up)..."):
            df = pd.DataFrame(api_get("/dashboard")["bins"])
        st.session_state["last_good"] = (df, pd.Timestamp.now())      # remember the last good answer
        return df, "api"
    except Exception as e:
        st.session_state["api_error"] = str(e)
        if "last_good" in st.session_state:                           # 1st fallback: data we already had
            return st.session_state["last_good"][0].copy(), "stale"
        df = load_csv("bins.csv").copy()                              # 2nd fallback: bundled demo data
        df["status"] = "Pending"
        return df, "csv"


data, mode = load_bins()


def load_alerts():
    """Collector alerts from the backend (empty list when offline)."""
    try:
        return api_get("/smart-alerts")["alerts"]
    except Exception:
        return []


ICON = {"CRITICAL": "🔴", "FULL": "🟠", "UPCOMING": "🟡"}
data["fill_level"] = pd.to_numeric(data["fill_level"])
to_collect = data[(data["fill_level"] >= COLLECT_AT) & (data["status"] != "Collected")]

# ------------------------------------------------------------ sidebar
st.sidebar.title("🗑️ Smart Waste")
st.sidebar.caption("Fill-level forecasting & route planning")
if mode == "api":
    st.sidebar.success("🟢 Backend + Supabase connected")
elif mode == "stale":
    st.sidebar.warning(f"🟠 Backend unreachable - showing data from {st.session_state['last_good'][1]:%H:%M:%S}")
    if st.sidebar.button("Retry connection"):
        api_get.clear()
        st.rerun()
else:
    st.sidebar.warning("🟠 Backend offline - showing local CSV demo data")
    st.sidebar.caption(f"API_URL = {API_URL}")
    if st.sidebar.button("Retry connection"):
        api_get.clear()
        st.rerun()
alerts = load_alerts() if mode == "api" else []   # stale/csv: no alerts, buttons disabled
urgent = [a for a in alerts if a["severity"] != "UPCOMING"]
st.sidebar.metric("🔔 Active alerts", len(alerts), f"{len(urgent)} need collection now" if urgent else None,
                  delta_color="inverse")
page = st.sidebar.radio("Navigation", ["🔔 Alerts", "🏠 Dashboard", "🗄️ Bin Registry", "🗺️ Bin Map",
                                       "🤖 Fill Forecasting", "🚛 Route Optimization", "📊 Results",
                                       "🛡️ System & Security", "🧾 Service History", "ℹ️ About"])


# ------------------------------------------------------------ alert banner (every page) + pop-up for new alerts
if alerts and page != "🔔 Alerts":
    lines = [f"{ICON[a['severity']]} **{a['bin_id']}** - {a['location']}: {a['message']}" for a in alerts[:5]]
    (st.error if urgent else st.warning)("**Collection alerts**  \n" + "  \n".join(lines) +
                                        ("  \n...see the 🔔 Alerts page for all" if len(alerts) > 5 else ""))
seen = st.session_state.setdefault("seen_alerts", set())
for a in alerts:
    key = (a["bin_id"], a["severity"])
    if key not in seen:
        seen.add(key)
        text = f"{a['bin_id']} ({a['location']}): {a['message']}"
        try:  # stays on screen until the collector clicks the X (needs Streamlit >= 1.49)
            st.toast(text, icon=ICON[a["severity"]], duration="infinite")
        except TypeError:
            st.toast(text, icon=ICON[a["severity"]])


# ------------------------------------------------------------ pages
def bin_map(df, route=None):
    m = folium.Map(location=[DEPOT_LAT, DEPOT_LON], zoom_start=11)
    folium.Marker([DEPOT_LAT, DEPOT_LON], tooltip="Depot", icon=folium.Icon(color="blue", icon="home")).add_to(m)
    for _, r in df.iterrows():
        color = "red" if r.fill_level >= CRITICAL_AT else "orange" if r.fill_level >= 70 else "green"
        folium.Marker([r.latitude, r.longitude], tooltip=f"{r.bin_id} - {r.fill_level:.0f}%",
                      popup=f"<b>{r.bin_id}</b><br>{r.location}<br>{r.fill_level:.0f}% ({r.status})",
                      icon=folium.Icon(color=color)).add_to(m)
    colors = ["blue", "purple", "darkgreen", "black"]
    for i, trip in enumerate(route or []):
        pts = [(DEPOT_LAT, DEPOT_LON)] + [(b["latitude"], b["longitude"]) for b in trip] + [(DEPOT_LAT, DEPOT_LON)]
        folium.PolyLine(pts, weight=5, color=colors[i % 4], tooltip=f"Truck {i + 1}").add_to(m)
    st_folium(m, width=1200, height=520, returned_objects=[])


if page == "🔔 Alerts":
    st.title("🔔 Collection Alerts")
    st.caption("Bins that are full now or forecast to fill soon, grouped by area. Refreshes every 30 seconds.")

    @st.fragment(run_every=30)
    def alerts_panel():
        try:
            live = api_get("/smart-alerts")["alerts"]
        except Exception:
            st.warning("Alerts need the backend connection.")
            return
        if not live:
            st.success("✅ No bins are full or about to fill. Nothing to collect.")
            return
        c = st.columns(3)
        c[0].metric("🔴 Critical (≥90%)", sum(a["severity"] == "CRITICAL" for a in live))
        c[1].metric("🟠 Full (≥80%)", sum(a["severity"] == "FULL" for a in live))
        c[2].metric("🟡 Filling soon", sum(a["severity"] == "UPCOMING" for a in live))
        st.subheader("Where to go (by area)")
        for a in live:
            x, y, z = st.columns([3, 4, 1])
            x.write(f"{ICON[a['severity']]} **{a['location']}** - {a['bin_id']}")
            y.write(a["message"])
            maps = f"https://www.google.com/maps?q={a['latitude']},{a['longitude']}"
            z.link_button("Map", maps)
        st.caption("Click 'Map' to open the bin's location in Google Maps. Use Route Optimization for the best order.")

    alerts_panel()

elif page == "🏠 Dashboard":
    st.title("🗑️ Smart Waste Collection Optimizer")
    auto = st.toggle("🔄 Live mode (refresh every 15 s)", value=False,
                     help="Pulls fresh sensor data from the backend automatically - good for the demo.")

    @st.fragment(run_every=15 if auto else None)
    def live_dashboard():
        if auto:
            api_get.clear()
        try:
            df = pd.DataFrame(api_get("/dashboard")["bins"]) if mode == "api" else data.copy()
        except Exception:
            df = data.copy()
        df["fill_level"] = pd.to_numeric(df["fill_level"])
        prev = st.session_state.get("prev_levels", {})
        c = st.columns(5)
        c[0].metric("Total bins", len(df))
        c[1].metric("🔴 Critical (≥90%)", int((df.fill_level >= CRITICAL_AT).sum()))
        c[2].metric("🟠 High (70-89%)", int(((df.fill_level >= 70) & (df.fill_level < CRITICAL_AT)).sum()))
        c[3].metric("🟢 Normal (<70%)", int((df.fill_level < 70).sum()))
        c[4].metric("Average fill", f"{df.fill_level.mean():.0f}%",
                    None if not prev else f"{df.fill_level.mean() - sum(prev.values()) / len(prev):+.1f} pts")
        st.caption(f"Last refreshed {pd.Timestamp.now():%H:%M:%S}")

        f1, f2, f3 = st.columns([2, 2, 2])
        areas = f1.multiselect("Area", sorted(df.location.unique()))
        min_fill = f2.slider("Minimum fill %", 0, 100, 0)
        show_done = f3.checkbox("Show collected bins", value=False)
        view = df[df.fill_level >= min_fill]
        if areas:
            view = view[view.location.isin(areas)]
        if not show_done:
            view = view[view.status != "Collected"]

        left, right = st.columns([3, 2])
        with right:
            st.subheader("Fill level by area")
            st.bar_chart(df.set_index("location")["fill_level"], horizontal=True, height=320)
        with left:
            st.subheader("Collection tasks")
            for _, r in view.sort_values("fill_level", ascending=False).iterrows():
                a, b, c3 = st.columns([3, 3, 2])
                moved = r.fill_level - prev.get(r.bin_id, r.fill_level)
                icon = "🔴" if r.fill_level >= CRITICAL_AT else "🟠" if r.fill_level >= COLLECT_AT else "🟢"
                a.write(f"{icon} **{r.bin_id}** - {r.location}")
                b.progress(min(int(r.fill_level), 100),
                           text=f"{r.fill_level:.0f}%" + (f" ({moved:+.0f})" if moved else ""))
                if c3.button("Mark collected", key=f"col_{r.bin_id}", disabled=(mode != "api")):
                    try:
                        api_put(f"/bins/{r.bin_id}/collect")
                        st.rerun()
                    except RuntimeError as e:
                        st.error(f"Could not update {r.bin_id}: {e}")
            if view.empty:
                st.success("✅ Nothing to collect with these filters.")
        st.session_state["prev_levels"] = dict(zip(df.bin_id, df.fill_level))
        st.caption(f"{int((df.status == 'Collected').sum())} bin(s) already collected.")

    live_dashboard()

elif page == "🗄️ Bin Registry":
    st.title("🗄️ Bin Registry")
    st.caption("Add, edit or remove bins. Changes go to Supabase through the API and are written to the audit log.")
    if mode != "api":
        st.warning("The registry needs the backend connection.")
        st.stop()
    st.dataframe(data[["bin_id", "location", "latitude", "longitude", "capacity", "fill_level", "status"]],
                 hide_index=True, use_container_width=True)
    t_add, t_edit, t_del = st.tabs(["➕ Add bin", "✏️ Edit bin", "🗑️ Delete bin"])
    with t_add:
        with st.form("add_bin", clear_on_submit=True):
            nums = [int(x[3:]) for x in data.bin_id if x[3:].isdigit()]
            c1, c2 = st.columns(2)
            new_id = c1.text_input("Bin ID", f"BIN{max(nums, default=0) + 1:03d}")
            loc = c2.text_input("Area / location name")
            c3, c4 = st.columns(2)
            lat = c3.number_input("Latitude", -90.0, 90.0, 19.0760, format="%.5f")
            lon = c4.number_input("Longitude", -180.0, 180.0, 72.8777, format="%.5f")
            c5, c6 = st.columns(2)
            cap = c5.number_input("Capacity", 1, 10000, 100)
            lvl = c6.slider("Current fill %", 0, 100, 0)
            if st.form_submit_button("Add bin"):
                try:
                    api_send("POST", "/bins", {"bin_id": new_id.strip(), "location": loc.strip(), "latitude": lat,
                                               "longitude": lon, "capacity": int(cap), "fill_level": float(lvl)})
                    st.success(f"Added {new_id}. It appears on the dashboard, map and alerts.")
                    st.rerun()
                except RuntimeError as e:
                    st.error(str(e))
    with t_edit:
        pick = st.selectbox("Bin to edit", data.bin_id.tolist(), key="edit_pick")
        row = data[data.bin_id == pick].iloc[0]
        with st.form("edit_bin"):
            e_loc = st.text_input("Area / location name", row.location)
            e1, e2 = st.columns(2)
            e_lat = e1.number_input("Latitude", -90.0, 90.0, float(row.latitude), format="%.5f")
            e_lon = e2.number_input("Longitude", -180.0, 180.0, float(row.longitude), format="%.5f")
            e_lvl = st.slider("Fill %", 0, 100, int(row.fill_level))
            if st.form_submit_button("Save changes"):
                try:
                    api_send("PUT", f"/bins/{pick}", {"location": e_loc, "latitude": e_lat,
                                                      "longitude": e_lon, "fill_level": float(e_lvl)})
                    st.success("Saved.")
                    st.rerun()
                except RuntimeError as e:
                    st.error(str(e))
    with t_del:
        victim = st.selectbox("Bin to delete", data.bin_id.tolist(), key="del_pick")
        st.warning("Deleting also removes the bin's history and service records.")
        if st.checkbox(f"Yes, delete {victim}") and st.button("Delete bin", type="primary"):
            try:
                api_send("DELETE", f"/bins/{victim}")
                st.success(f"Deleted {victim}.")
                st.rerun()
            except RuntimeError as e:
                st.error(str(e))

elif page == "🗺️ Bin Map":
    st.title("🗺️ Bin Map")
    bin_map(data)
    st.dataframe(data, use_container_width=True, hide_index=True)

elif page == "🤖 Fill Forecasting":
    st.title("🤖 Fill-Level Forecasting")
    bin_id = st.selectbox("Bin", data.bin_id.tolist())
    try:
        f = api_get(f"/forecast/{bin_id}")
        hist = pd.DataFrame(f["historical_data"])
        preds = [p["predicted_fill"] for p in f["forecast"]]
        source = "FastAPI backend"
    except Exception:
        st.warning("Backend forecast unavailable - using local CSV history.")
        hist = load_csv("fill_history.csv")
        hist = hist[hist.bin_id == bin_id].copy()
        if len(hist) < 2:
            st.stop()
        from forecasting import forecast_from_history
        preds, mae, dtf = forecast_from_history(hist.to_dict("records"))
        f = {"mae_percentage_points": mae, "days_until_full": dtf}
        source = "local model"
    c = st.columns(5)
    for col, label, p in zip(c[:3], ["Tomorrow", "In 2 days", "In 3 days"], preds):
        col.metric(label, f"{p:.1f}%")
    c[3].metric("Model error (MAE)", "n/a" if f.get("mae_percentage_points") is None else f"±{f['mae_percentage_points']} pts")
    c[4].metric("Days until full", "n/a" if f.get("days_until_full") is None else f["days_until_full"])
    n = len(hist)
    chart = pd.DataFrame({"Historical": list(hist.fill_level) + [None] * 3,
                          "Predicted": [None] * (n - 1) + [hist.fill_level.iloc[-1]] + preds})
    st.line_chart(chart)
    if preds[0] >= CRITICAL_AT:
        st.error("🚨 Predicted to reach a critical level tomorrow - schedule collection.")
    elif preds[0] >= COLLECT_AT:
        st.warning("⚠️ Approaching the collection threshold.")
    else:
        st.success("✅ No immediate collection needed.")
    st.caption(f"Source: {source}. Linear regression on calendar days; MAE = one-step-ahead backtest.")

elif page == "🚛 Route Optimization":
    st.title("🚛 Route Optimization")
    st.caption("Constraint-aware OR-Tools routing vs. three baselines, with truck capacity.")
    c1, c2 = st.columns(2)
    capacity = c1.number_input("Truck capacity (bin-units)", 100, 2000, 300, step=50)
    trucks = c2.number_input("Trucks available", 1, 6, 2)
    if to_collect.empty:
        st.success("✅ No bins need collection right now.")
        st.stop()
    bins = to_collect.to_dict("records")
    with st.spinner("Optimising..."):
        res = opt.compare(bins, capacity, trucks)
    table = pd.DataFrame([{"Strategy": k, "Distance (km)": round(v["km"], 2), "Trips": len(v["trips"])}
                          for k, v in res.items()])
    best_base = min(v["km"] for k, v in res.items() if not k.startswith("OR-Tools"))
    ort = res["OR-Tools (capacity-aware)"]
    st.dataframe(table, hide_index=True, use_container_width=True)
    st.bar_chart(table.set_index("Strategy")["Distance (km)"])
    fixed = res["Fixed round (current process)"]["km"]
    m = st.columns(3)
    m[0].metric("Saved vs current process", f"{fixed - ort['km']:.1f} km", f"{(fixed - ort['km']) / fixed * 100:.1f}%")
    m[1].metric("Saved vs best baseline", f"{best_base - ort['km']:.1f} km")
    m[2].metric("Bins skipped", len(ort["dropped"]))
    if ort["dropped"]:
        st.error("Some bins could not be served with this capacity/truck count: " +
                 ", ".join(b["bin_id"] for b in ort["dropped"]))
    bin_map(data, ort["trips"])
    rows = [{"Truck": i + 1, "Stop": s + 1, "Bin": b["bin_id"], "Location": b["location"],
             "Fill %": b["fill_level"]} for i, t in enumerate(ort["trips"]) for s, b in enumerate(t)]
    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)

elif page == "📊 Results":
    st.title("📊 Evaluation Results")
    st.caption("The tables the capstone evaluation dossier asks for: forecast error, overflow prevention, "
               "route reduction, network reliability and battery life.")
    ev = None
    if mode == "api":
        try:
            ev = api_get("/evaluation")
        except Exception as e:
            st.warning(f"Evaluation unavailable: {e}")
    if ev:
        sm = ev["summary"]
        c = st.columns(5)
        c[0].metric("Avg forecast error (MAE)", "n/a" if sm["avg_forecast_mae_pts"] is None else f"±{sm['avg_forecast_mae_pts']} pts")
        c[1].metric("Bins overflowing now", sm["bins_overflowing_now"])
        c[2].metric("Collections done", sm["collections_done"])
        c[3].metric("Overflow prevention", "n/a" if sm["overflow_prevention_pct"] is None else f"{sm['overflow_prevention_pct']}%",
                    help="Share of collections done before the bin reached 100%.")
        c[4].metric("Sensor readings stored", sm["sensor_readings"])
        st.subheader("1. Fill estimation error and battery life (per bin)")
        t = pd.DataFrame(ev["per_bin"]).rename(columns={
            "bin_id": "Bin", "location": "Area", "readings": "Readings", "fill_now": "Fill now %",
            "mae_pts": "Forecast MAE (pts)", "days_until_full": "Days until full",
            "battery_pct": "Battery %", "battery_days_left": "Battery days left (est.)"})
        st.dataframe(t, hide_index=True, use_container_width=True)
        st.download_button("⬇️ Download as CSV", t.to_csv(index=False), "evaluation_per_bin.csv", "text/csv")
    st.subheader("2. Route reduction (bins ≥ 80%, truck capacity 300)")
    if to_collect.empty:
        st.info("No bins need collection right now.")
    else:
        res = opt.compare(to_collect.to_dict("records"), 300, 2)
        fixed = res["Fixed round (current process)"]["km"]
        rt = pd.DataFrame([{"Strategy": k, "Distance (km)": round(v["km"], 2), "Trips": len(v["trips"]),
                            "Saving vs current (%)": round((fixed - v["km"]) / fixed * 100, 1)} for k, v in res.items()])
        st.dataframe(rt, hide_index=True, use_container_width=True)
        st.bar_chart(rt.set_index("Strategy")["Distance (km)"])
    st.subheader("3. Network reliability (backend telemetry)")
    try:
        mt = api_get("/metrics")
        c = st.columns(4)
        c[0].metric("Requests", mt["requests"])
        c[1].metric("Errors", mt["errors"])
        ok = 100 * (1 - mt["errors"] / max(mt["requests"], 1))
        c[2].metric("Success rate", f"{ok:.1f}%")
        c[3].metric("Avg latency", f"{mt['avg_latency_ms']} ms")
        st.dataframe(pd.DataFrame(mt["requests_by_endpoint"].items(), columns=["Endpoint", "Requests"]),
                     hide_index=True, use_container_width=True)
    except Exception:
        st.info("Backend metrics unavailable while offline.")
    st.subheader("4. Robustness experiment (packet loss and sensor noise)")
    if os.path.exists("experiment_results.csv"):
        st.dataframe(pd.read_csv("experiment_results.csv"), hide_index=True, use_container_width=True)
    else:
        st.info("Run `python experiments.py` once and commit `experiment_results.csv` to show this table.")

elif page == "🛡️ System & Security":
    st.title("🛡️ System Health, Failure Handling & Security")
    if mode != "api":
        st.warning("Backend not reachable - this page needs it.")
        st.stop()
    try:
        h = api_get("/health")
        c = st.columns(4)
        c[0].metric("Backend", h["status"].upper())
        c[1].metric("Database", h["database"])
        c[2].metric("DB latency", f"{h['db_latency_ms']} ms")
        c[3].metric("Notifications", h["notifications"])
    except Exception as e:
        st.error(f"Health check failed: {e}")
        h = {}
    if st.button("📨 Send test notification"):
        try:
            r = api_send("POST", "/notify-test")
            (st.success if r["sent"] else st.info)("Sent to Telegram." if r["sent"] else f"Not sent. {r['hint']}")
        except RuntimeError as e:
            st.error(str(e))
    t1, t2, t3 = st.tabs(["⚠️ Events & failures", "🧾 Audit log", "🔒 Security checklist"])
    with t1:
        st.caption("Warnings and errors the backend recorded (bad API keys, low batteries, failed writes, crashes).")
        ev = api_get("/events")["events"]
        st.dataframe(pd.DataFrame(ev) if ev else pd.DataFrame(columns=["time", "level", "message"]),
                     hide_index=True, use_container_width=True)
    with t2:
        try:
            lg = api_get("/audit-log")["log"]
            st.dataframe(pd.DataFrame(lg) if lg else pd.DataFrame(columns=["created_at", "action", "bin_id", "detail"]),
                         hide_index=True, use_container_width=True)
        except Exception:
            st.info("Run the new `audit_log` SQL from schema.sql in Supabase first.")
    with t3:
        checks = [
            ("Write endpoints need an API key (X-API-Key, constant-time compare)", h.get("api_key_required", False)),
            ("Input validation on every write (ranges, ID pattern, length)", True),
            ("Rate limit: 60 writes per minute per client", True),
            ("CORS closed by default (ALLOWED_ORIGINS)", True),
            ("Security headers (nosniff, frame deny, no-store)", True),
            ("No stack traces leaked: errors return a clean JSON 500", True),
            ("Secrets live in Render/Streamlit secrets, never in GitHub (.gitignore)", True),
            ("Supabase row-level security enabled (run the last lines of schema.sql)", None),
            ("Privacy: only bin IDs, areas and fill levels are stored - no personal data", True),
        ]
        for text, ok in checks:
            st.write(("✅ " if ok else "⚠️ " if ok is None else "❌ ") + text +
                     ("  *(verify in Supabase > Authentication > Policies)*" if ok is None else ""))

elif page == "🧾 Service History":
    st.title("🧾 Service History (audit trail)")
    try:
        rows = api_get("/service-history")["history"]
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True) if rows else st.info("No collections yet.")
    except Exception:
        st.info("Available when the backend is connected.")

else:
    st.title("ℹ️ About")
    st.write("Streamlit dashboard → FastAPI (Render) → Supabase Postgres. Forecasting: scikit-learn linear "
             "regression. Routing: Google OR-Tools capacitated VRP compared with three baselines. "
             "Sensor intake: `POST /readings` (used by `simulator.py`).")
