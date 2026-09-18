import pandas as pd
import math

# Load bin data
data = pd.read_csv("bins.csv")

# Select bins that need collection
route_bins = data[
    data["fill_level"] >= 80
].copy().reset_index(drop=True)

# Depot
DEPOT_LAT = 19.0760
DEPOT_LON = 72.8777


def distance(lat1, lon1, lat2, lon2):
    lat_distance = (lat1 - lat2) * 111
    lon_distance = (lon1 - lon2) * 111 * 0.94

    return math.sqrt(
        lat_distance ** 2 +
        lon_distance ** 2
    )


# Start from depot
current_lat = DEPOT_LAT
current_lon = DEPOT_LON

total_distance = 0

print("\n===== BASELINE ROUTE =====")

print("Start: Collection Depot")

# Visit bins in their original order
for _, row in route_bins.iterrows():

    d = distance(
        current_lat,
        current_lon,
        row["latitude"],
        row["longitude"]
    )

    total_distance += d

    print(
        f"Collect {row['bin_id']} "
        f"({row['location']})"
    )

    current_lat = row["latitude"]
    current_lon = row["longitude"]


# Return to depot
total_distance += distance(
    current_lat,
    current_lon,
    DEPOT_LAT,
    DEPOT_LON
)

print("Return: Collection Depot")

print(
    f"\nTotal Baseline Distance: "
    f"{total_distance:.2f} km"
)

print(
    f"Bins Collected: "
    f"{len(route_bins)}"
)