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


def api_put(path):
    r = requests.put(f"{API_URL}{path}", headers=HEADERS, timeout=45)
    r.raise_for_status()
    api_get.clear()  # refresh cached data
    return r.json()


@st.cache_data(show_spinner=False)
def load_csv(name):
    return pd.read_csv(os.path.join("data", name))


def load_bins():
    """Returns (dataframe, mode). Falls back to the CSV demo data if the API is unreachable."""
    try:
        with st.spinner("Contacting backend (Render may take up to a minute to wake up)..."):
            return pd.DataFrame(api_get("/dashboard")["bins"]), "api"
    except Exception as e:
        st.session_state["api_error"] = str(e)
        df = load_csv("bins.csv").copy()
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
else:
    st.sidebar.warning("🟠 Backend offline - showing local CSV demo data")
    st.sidebar.caption(f"API_URL = {API_URL}")
    if st.sidebar.button("Retry connection"):
        api_get.clear()
        st.rerun()
alerts = load_alerts() if mode == "api" else []
urgent = [a for a in alerts if a["severity"] != "UPCOMING"]
st.sidebar.metric("🔔 Active alerts", len(alerts), f"{len(urgent)} need collection now" if urgent else None,
                  delta_color="inverse")
page = st.sidebar.radio("Navigation", ["🔔 Alerts", "🏠 Dashboard", "🗺️ Bin Map", "🤖 Fill Forecasting",
                                       "🚛 Route Optimization", "📊 Results", "🧾 Service History", "ℹ️ About"])


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
        st.toast(f"{a['bin_id']} ({a['location']}): {a['message']}", icon=ICON[a["severity"]])


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
    c = st.columns(4)
    c[0].metric("Total bins", len(data))
    c[1].metric("🔴 Critical (≥90%)", int((data.fill_level >= CRITICAL_AT).sum()))
    c[2].metric("🟠 High (70-89%)", int(((data.fill_level >= 70) & (data.fill_level < CRITICAL_AT)).sum()))
    c[3].metric("🟢 Normal (<70%)", int((data.fill_level < 70).sum()))
    if len(to_collect):
        st.warning(f"⚠️ Overflow alert: {len(to_collect)} bin(s) need collection.")
    else:
        st.success("✅ No bins currently need collection.")
    st.subheader("Collection tasks")
    pending = data[data.status != "Collected"].sort_values("fill_level", ascending=False)
    for _, r in pending.iterrows():
        a, b, c3 = st.columns([3, 2, 1])
        a.write(f"**{r.bin_id}** - {r.location}")
        b.progress(min(int(r.fill_level), 100), text=f"{r.fill_level:.0f}%")
        if c3.button("Mark collected", key=f"col_{r.bin_id}", disabled=(mode != "api")):
            try:
                api_put(f"/bins/{r.bin_id}/collect")
                st.rerun()
            except requests.RequestException as e:
                st.error(f"Could not update {r.bin_id}: {e}")
    st.caption(f"{int((data.status == 'Collected').sum())} bin(s) already collected.")

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
    st.subheader("Route reduction (all bins ≥ 80%)")
    if to_collect.empty:
        st.info("No bins need collection right now.")
    else:
        res = opt.compare(to_collect.to_dict("records"), 300, 2)
        st.dataframe(pd.DataFrame([{"Strategy": k, "Distance (km)": round(v["km"], 2), "Trips": len(v["trips"])}
                                   for k, v in res.items()]), hide_index=True, use_container_width=True)
    st.subheader("Backend telemetry")
    try:
        mt = api_get("/metrics")
        c = st.columns(4)
        c[0].metric("Requests", mt["requests"])
        c[1].metric("Errors", mt["errors"])
        c[2].metric("Avg latency", f"{mt['avg_latency_ms']} ms")
        c[3].metric("Uptime", f"{mt['uptime_s'] // 60} min")
    except Exception:
        st.info("Backend metrics unavailable while offline.")
    st.caption("Add your forecast MAE table and battery-life test results here once the sensor simulator has run.")

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
