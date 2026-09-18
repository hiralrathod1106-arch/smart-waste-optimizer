import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
from sklearn.linear_model import LinearRegression

# OR-Tools
from ortools.constraint_solver import pywrapcp
from ortools.constraint_solver import routing_enums_pb2


# ---------------- PAGE SETTINGS ----------------

st.set_page_config(
    page_title="Smart Waste Collection Optimizer",
    page_icon="🗑️",
    layout="wide"
)


# ---------------- LOAD DATA ----------------

data = pd.read_csv("bins.csv")
history = pd.read_csv("fill_history.csv")

history["date"] = pd.to_datetime(history["date"])


# ---------------- BIN STATUS ----------------

critical = len(data[data["fill_level"] >= 90])

high = len(
    data[
        (data["fill_level"] >= 70) &
        (data["fill_level"] < 90)
    ]
)

normal = len(data[data["fill_level"] < 70])


# ---------------- TITLE ----------------

st.title("🗑️ Smart Waste Collection Optimizer")

st.write(
    "Fill-Level Forecasting and Route Planning"
)

st.divider()


# ---------------- DASHBOARD STATISTICS ----------------

col1, col2, col3, col4 = st.columns(4)

with col1:
    st.metric(
        "Total Bins",
        len(data)
    )

with col2:
    st.metric(
        "🔴 Critical",
        critical
    )

with col3:
    st.metric(
        "🟠 High Fill",
        high
    )

with col4:
    st.metric(
        "🟢 Normal",
        normal
    )


st.divider()


# ---------------- BIN INFORMATION ----------------

st.subheader("🗑️ Waste Bin Information")

st.dataframe(
    data,
    use_container_width=True,
    hide_index=True
)


st.divider()


# ---------------- COLLECTION REQUIRED ----------------

st.subheader("🚛 Bins Requiring Collection")

collection_bins = data[
    data["fill_level"] >= 80
]

if len(collection_bins) > 0:

    st.warning(
        f"{len(collection_bins)} bin(s) require collection."
    )

    st.dataframe(
        collection_bins,
        use_container_width=True,
        hide_index=True
    )

else:

    st.success(
        "No bins currently require collection."
    )


st.divider()


# ---------------- MAP ----------------

st.subheader("🗺️ Waste Bin Locations")

waste_map = folium.Map(
    location=[19.0760, 72.8777],
    zoom_start=11
)


for _, row in data.iterrows():

    if row["fill_level"] >= 90:
        icon_color = "red"

    elif row["fill_level"] >= 70:
        icon_color = "orange"

    else:
        icon_color = "green"


    folium.Marker(
        location=[
            row["latitude"],
            row["longitude"]
        ],

        popup=(
            f"<b>{row['bin_id']}</b><br>"
            f"Location: {row['location']}<br>"
            f"Fill Level: {row['fill_level']}%"
        ),

        tooltip=(
            f"{row['bin_id']} - "
            f"{row['fill_level']}%"
        ),

        icon=folium.Icon(
            color=icon_color
        )

    ).add_to(waste_map)


st_folium(
    waste_map,
    width=1200,
    height=500
)


st.divider()


# ==================================================
#          FILL-LEVEL FORECASTING
# ==================================================

st.subheader("🤖 Fill-Level Forecasting")

st.write(
    "Select a bin to predict its future fill level."
)


# Bin selection

selected_bin = st.selectbox(
    "Select Waste Bin",
    data["bin_id"].tolist()
)


# Get history for selected bin

bin_history = history[
    history["bin_id"] == selected_bin
].copy()


if len(bin_history) >= 2:

    # Create numerical day values

    bin_history["day"] = range(
        len(bin_history)
    )


    # Prepare machine learning data

    X = bin_history[["day"]]

    y = bin_history["fill_level"]


    # Create model

    model = LinearRegression()

    model.fit(X, y)


    # Current day

    current_day = len(bin_history) - 1


    # Predict next 3 days

    future_days = pd.DataFrame(
        {
            "day": [
                current_day + 1,
                current_day + 2,
                current_day + 3
            ]
        }
    )


    predictions = model.predict(
        future_days
    )


    # Keep prediction between 0 and 100

    predictions = [
        max(0, min(100, value))
        for value in predictions
    ]


    # Display predictions

    col1, col2, col3 = st.columns(3)


    with col1:

        st.metric(
            "Tomorrow",
            f"{predictions[0]:.1f}%"
        )


    with col2:

        st.metric(
            "After 2 Days",
            f"{predictions[1]:.1f}%"
        )


    with col3:

        st.metric(
            "After 3 Days",
            f"{predictions[2]:.1f}%"
        )


    # Forecast chart

    st.write("📈 Predicted Fill-Level")

    chart_data = pd.DataFrame(
        {
            "Historical Fill Level": bin_history[
                "fill_level"
            ].tolist()
            + [None, None, None],

            "Predicted Fill Level": [None] * len(
                bin_history
            )
            + predictions
        }
    )


    st.line_chart(
        chart_data,
        y=["Historical Fill Level", "Predicted Fill Level"]
    )


    # Collection warning

    if predictions[0] >= 90:

        st.error(
            "🚨 This bin is predicted to reach "
            "critical level soon!"
        )

    elif predictions[0] >= 80:

        st.warning(
            "⚠️ This bin is approaching "
            "the collection threshold."
        )

    else:

        st.success(
            "✅ This bin does not require "
            "immediate collection."
        )


else:

    st.warning(
        "Not enough historical data for forecasting."
    )


st.divider()


# ==================================================
#          ROUTE OPTIMIZATION
# ==================================================

st.subheader("🚛 Optimized Waste Collection Route")

st.write(
    "OR-Tools selects the shortest collection route "
    "for bins that have reached 80% fill level."
)


# ---------------- DEPOT ----------------

# Waste collection truck starts and ends here.
DEPOT_LAT = 19.0760
DEPOT_LON = 72.8777


# ---------------- BINS FOR COLLECTION ----------------

route_bins = data[
    data["fill_level"] >= 80
].copy().reset_index(drop=True)


if len(route_bins) == 0:

    st.success(
        "✅ No bins need collection right now, "
        "so an optimized route is not required."
    )

else:

    # ----------------------------------------------
    # CREATE LOCATIONS
    # ----------------------------------------------

    # Depot is location 0.
    locations = [
        (DEPOT_LAT, DEPOT_LON)
    ]

    for _, row in route_bins.iterrows():
        locations.append(
            (
                float(row["latitude"]),
                float(row["longitude"])
            )
        )


    # ----------------------------------------------
    # DISTANCE MATRIX
    # ----------------------------------------------

    # Approximate distance using latitude/longitude.
    # Multiplying by 100000 converts the values to
    # integers, which OR-Tools requires for routing.
    distance_matrix = []

    for from_lat, from_lon in locations:

        row_distances = []

        for to_lat, to_lon in locations:

            lat_distance = (from_lat - to_lat) * 111000
            lon_distance = (
                (from_lon - to_lon)
                * 111000
                * 0.94
            )

            distance = (
                lat_distance ** 2 +
                lon_distance ** 2
            ) ** 0.5

            row_distances.append(
                int(distance)
            )

        distance_matrix.append(row_distances)


    # ----------------------------------------------
    # OR-TOOLS ROUTING MODEL
    # ----------------------------------------------

    manager = pywrapcp.RoutingIndexManager(
        len(distance_matrix),
        1,
        0
    )

    routing = pywrapcp.RoutingModel(manager)


    def distance_callback(from_index, to_index):

        from_node = manager.IndexToNode(from_index)
        to_node = manager.IndexToNode(to_index)

        return distance_matrix[from_node][to_node]


    transit_callback_index = routing.RegisterTransitCallback(
        distance_callback
    )

    routing.SetArcCostEvaluatorOfAllVehicles(
        transit_callback_index
    )


    # ----------------------------------------------
    # SOLVE ROUTE
    # ----------------------------------------------

    search_parameters = pywrapcp.DefaultRoutingSearchParameters()

    search_parameters.first_solution_strategy = (
        routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    )

    search_parameters.local_search_metaheuristic = (
        routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    )

    search_parameters.time_limit.seconds = 5


    solution = routing.SolveWithParameters(
        search_parameters
    )


    if solution:

        # ------------------------------------------
        # GET OPTIMIZED ORDER
        # ------------------------------------------

        index = routing.Start(0)

        route_order = []
        total_distance = 0

        while not routing.IsEnd(index):

            node = manager.IndexToNode(index)

            route_order.append(node)

            previous_index = index

            index = solution.Value(
                routing.NextVar(index)
            )

            total_distance += routing.GetArcCostForVehicle(
                previous_index,
                index,
                0
            )


        # Add final depot
        route_order.append(
            manager.IndexToNode(index)
        )


        # ------------------------------------------
        # ROUTE MAP
        # ------------------------------------------

        route_map = folium.Map(
            location=[
                DEPOT_LAT,
                DEPOT_LON
            ],
            zoom_start=11
        )


        # Depot marker

        folium.Marker(
            location=[
                DEPOT_LAT,
                DEPOT_LON
            ],
            popup="<b>🚛 Collection Depot</b>",
            tooltip="Collection Depot",
            icon=folium.Icon(
                color="blue",
                icon="home"
            )
        ).add_to(route_map)


        # Route coordinates

        route_coordinates = []


        for stop_number, node in enumerate(route_order):

            lat, lon = locations[node]

            route_coordinates.append(
                [lat, lon]
            )


            if node != 0:

                bin_position = node - 1
                bin_row = route_bins.iloc[bin_position]

                folium.Marker(
                    location=[
                        lat,
                        lon
                    ],
                    popup=(
                        f"<b>Stop {stop_number}</b><br>"
                        f"Bin: {bin_row['bin_id']}<br>"
                        f"Location: {bin_row['location']}<br>"
                        f"Fill Level: {bin_row['fill_level']}%"
                    ),
                    tooltip=(
                        f"Stop {stop_number}: "
                        f"{bin_row['bin_id']}"
                    ),
                    icon=folium.Icon(
                        color="red",
                        icon="trash"
                    )
                ).add_to(route_map)


        # Draw optimized route

        folium.PolyLine(
            locations=route_coordinates,
            weight=5,
            opacity=0.8,
            tooltip="Optimized Collection Route"
        ).add_to(route_map)


        # ------------------------------------------
        # ROUTE INFORMATION
        # ------------------------------------------

        route_distance_km = total_distance / 1000

        col1, col2 = st.columns(2)

        with col1:
            st.metric(
                "🗑️ Bins to Collect",
                len(route_bins)
            )

        with col2:
            st.metric(
                "📏 Approx. Route Distance",
                f"{route_distance_km:.2f} km"
            )


        st.success(
            "✅ Optimized collection route generated "
            "using OR-Tools."
        )


        # ------------------------------------------
        # ROUTE STOP TABLE
        # ------------------------------------------

        route_table = []

        for stop_number, node in enumerate(route_order):

            if node == 0:

                route_table.append(
                    {
                        "Stop": stop_number,
                        "Bin": "DEPOT",
                        "Location": "Collection Depot",
                        "Fill Level": "-"
                    }
                )

            else:

                bin_position = node - 1
                bin_row = route_bins.iloc[bin_position]

                route_table.append(
                    {
                        "Stop": stop_number,
                        "Bin": bin_row["bin_id"],
                        "Location": bin_row["location"],
                        "Fill Level": f"{bin_row['fill_level']}%"
                    }
                )


        st.write("### 📋 Collection Order")

        st.dataframe(
            pd.DataFrame(route_table),
            use_container_width=True,
            hide_index=True
        )


        # ------------------------------------------
        # DISPLAY ROUTE MAP
        # ------------------------------------------

        st.write("### 🗺️ Optimized Route Map")

        st_folium(
            route_map,
            width=1200,
            height=550
        )


    else:

        st.error(
            "❌ OR-Tools could not generate a route."
        )
