from fastapi import FastAPI
from supabase import create_client
from dotenv import load_dotenv
from sklearn.linear_model import LinearRegression 
import os

# Find the project root (one folder above backend)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Load .env from the project root
ENV_FILE = os.path.join(BASE_DIR, "config.env")
load_dotenv(ENV_FILE)

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

print("ENV FILE:", ENV_FILE)
print("SUPABASE URL FOUND:", bool(SUPABASE_URL))
print("SUPABASE KEY FOUND:", bool(SUPABASE_KEY))

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError(
        "Supabase credentials not found. Check the .env file in the project root."
    )

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

app = FastAPI(title="Smart Waste Collection Optimizer")


@app.get("/")
def home():
    return {
        "message": "Smart Waste Collection Optimizer API is running"
    }
@app.get("/bins")
def get_bins():
    response = supabase.table("bins").select("*").execute()

    return {
        "bins": response.data
    }


@app.get("/bins/{bin_id}")
def get_bin(bin_id: str):
    response = (
        supabase
        .table("bins")
        .select("*")
        .eq("bin_id", bin_id)
        .execute()
    )

    if not response.data:
        return {
            "message": "Bin not found"
        }

    return {
        "bin": response.data[0]
    }
@app.get("/fill-history/{bin_id}")
def get_fill_history(bin_id: str):
    response = (
        supabase
        .table("fill_history")
        .select("*")
        .eq("bin_id", bin_id)
        .order("date")
        .execute()
    )

    return {
        "bin_id": bin_id,
        "history": response.data
    }
@app.get("/statuses")
def get_statuses():
    response = (
        supabase
        .table("collection_status")
        .select("*")
        .execute()
    )

    return {
        "statuses": response.data
    }
@app.get("/dashboard")
def get_dashboard():
    bins_response = (
        supabase
        .table("bins")
        .select("*")
        .execute()
    )

    status_response = (
        supabase
        .table("collection_status")
        .select("*")
        .execute()
    )

    status_map = {
        item["bin_id"]: item["status"]
        for item in status_response.data
    }

    dashboard_data = []

    for bin_data in bins_response.data:
        bin_id = bin_data["bin_id"]

        dashboard_data.append({
            **bin_data,
            "status": status_map.get(bin_id, "Pending")
        })

    return {
        "bins": dashboard_data
    }
@app.put("/bins/{bin_id}/collect")
def mark_bin_collected(bin_id: str):
    response = (
        supabase
        .table("collection_status")
        .update({"status": "Collected"})
        .eq("bin_id", bin_id)
        .execute()
    )

    if not response.data:
        return {
            "message": "Bin not found"
        }

    return {
        "message": f"{bin_id} marked as Collected",
        "status": response.data[0]
    }
@app.get("/forecast/{bin_id}")
def get_forecast(bin_id: str):
    response = (
        supabase
        .table("fill_history")
        .select("*")
        .eq("bin_id", bin_id)
        .order("date")
        .execute()
    )

    history = response.data

    if not history:
        return {
            "message": "No historical data found",
            "bin_id": bin_id
        }

    # Prepare data for the ML model
    x = [[i] for i in range(len(history))]
    y = [item["fill_level"] for item in history]

    # Train Linear Regression model
    model = LinearRegression()
    model.fit(x, y)

    # Predict the next 3 days
    future_days = [
        [len(history)],
        [len(history) + 1],
        [len(history) + 2]
    ]

    predictions = model.predict(future_days)

    # Keep predictions between 0 and 100
    predictions = [
        max(0, min(100, round(float(prediction), 2)))
        for prediction in predictions
    ]

    return {
        "bin_id": bin_id,
        "historical_data": history,
        "forecast": [
            {
                "day": "Next Day",
                "predicted_fill": predictions[0]
            },
            {
                "day": "Day 2",
                "predicted_fill": predictions[1]
            },
            {
                "day": "Day 3",
                "predicted_fill": predictions[2]
            }
        ]
    }

