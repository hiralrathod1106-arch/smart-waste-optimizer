"""Simulated ESP32 fill sensors -> POST /readings.   python simulator.py --url https://YOUR.onrender.com --key API_KEY
Includes failure modes for the robustness experiment: --drop-rate (lost packets) and --noise (sensor noise)."""
import argparse, random, time

import requests

p = argparse.ArgumentParser()
p.add_argument("--url", default="http://127.0.0.1:8001")
p.add_argument("--key", default="")
p.add_argument("--rounds", type=int, default=5)
p.add_argument("--interval", type=float, default=2)
p.add_argument("--drop-rate", type=float, default=0.1, help="fraction of readings lost")
p.add_argument("--noise", type=float, default=2.0, help="std-dev of sensor noise (fill %%)")
a = p.parse_args()

headers = {"X-API-Key": a.key} if a.key else {}
bins = requests.get(f"{a.url}/bins", timeout=60).json()["bins"]
level = {b["bin_id"]: float(b["fill_level"]) for b in bins}
battery = {b["bin_id"]: 100.0 for b in bins}
sent = lost = failed = 0
for r in range(a.rounds):
    for bid in level:
        level[bid] = min(100.0, level[bid] + random.uniform(0, 6))
        battery[bid] = max(0.0, battery[bid] - random.uniform(0.05, 0.2))
        if random.random() < a.drop_rate:
            lost += 1
            continue
        body = {"bin_id": bid, "fill_level": round(min(100, max(0, level[bid] + random.gauss(0, a.noise))), 1),
                "battery_pct": round(battery[bid], 1)}
        try:
            requests.post(f"{a.url}/readings", json=body, headers=headers, timeout=60).raise_for_status()
            sent += 1
        except requests.RequestException as e:
            failed += 1
            print("failed:", bid, e)
    print(f"round {r + 1}/{a.rounds}: sent={sent} lost={lost} failed={failed}")
    time.sleep(a.interval)
print(f"delivery rate = {sent / max(sent + lost + failed, 1):.0%}")
