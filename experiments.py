"""Failure-mode / robustness experiment (offline, no database needed):  python experiments.py
Question: how much does forecast error grow when sensor readings are lost or noisy?
Output: a table you can paste into the evaluation dossier (also saved as experiment_results.csv)."""
import csv
import os
import random

import pandas as pd

from forecasting import forecast_from_history

random.seed(7)
hist = pd.read_csv(os.path.join("data", "fill_history.csv"))


def mean_mae(rows_by_bin):
    maes = [forecast_from_history(r)[1] for r in rows_by_bin.values() if len(r) >= 4]
    maes = [m for m in maes if m is not None]
    return round(sum(maes) / len(maes), 2) if maes else None


def run(drop, noise, trials=30):
    results = []
    for _ in range(trials):
        by_bin = {}
        for b, g in hist.groupby("bin_id"):
            rows = []
            for r in g.to_dict("records"):
                if random.random() < drop:
                    continue                                   # packet lost
                r["fill_level"] = min(100, max(0, r["fill_level"] + random.gauss(0, noise)))
                rows.append(r)
            by_bin[b] = rows
        m = mean_mae(by_bin)
        if m is not None:
            results.append(m)
    return round(sum(results) / len(results), 2) if results else None


rows = []
for drop in (0, 0.1, 0.3, 0.5):
    for noise in (0, 2, 5):
        rows.append({"packet_loss": f"{int(drop * 100)}%", "sensor_noise_std": noise, "avg_mae_pts": run(drop, noise)})
df = pd.DataFrame(rows)
print(df.to_string(index=False))
df.to_csv("experiment_results.csv", index=False)
