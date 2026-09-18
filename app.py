import streamlit as st
import os
import pandas as pd
import folium
from streamlit_folium import st_folium
from sklearn.linear_model import LinearRegression
import math

from ortools.constraint_solver import pywrapcp
from ortools.constraint_solver import routing_enums_pb2


# ==================================================
# PAGE SETTINGS
# ==================================================

st.set_page_config(
    page_title="Smart Waste Collection Optimizer",
    page_icon="🗑️",
    layout="wide"
)


# ==================================================
# PROFESSIONAL UI STYLING
# ==================================================

st.markdown("""
<style>

.main {
    padding-top: 1rem;
}

.block-container {
    padding-top: 2rem;
    padding-bottom: 2rem;
}

/* Main headings */
h1 {
    font-weight: 700;
    letter-spacing: -1px;
}

h2, h3 {
    font-weight: 600;
}

/* Sidebar */
[data-testid="stSidebar"] {
    border-right: 1px solid #dddddd;
}

[data-testid="stSidebar"] h1 {
    font-size: 24px;
}

/* Metric cards */
[data-testid="stMetric"] {
    border: 1px solid #dddddd;
    border-radius: 12px;
    padding: 15px;
    background-color: #ffffff;
}

/* Buttons */
.stButton > button {
    border-radius: 8px;
    font-weight: 600;
    min-height: 40px;
}

/* Alerts */
.stAlert {
    border-radius: 10px;
}

/* Dataframes */
[data-testid="stDataFrame"] {
    border-radius: 10px;
}

/* Divider */
hr {
    margin-top: 1.5rem;
    margin-bottom: 1.5rem;
}

</style>
""", unsafe_allow_html=True)


# ==================================================
# LOAD DATA
# ==================================================

data = pd.read_csv("bins.csv")
history = pd.read_csv("fill_history.csv")

history["date"] = pd.to_datetime(history["date"])


# ==================================================
# COLLECTION STATUS
# ==================================================

STATUS_FILE = "collection_status.csv"

if os.path.exists(STATUS_FILE):
    status_data = pd.read_csv(STATUS_FILE)
else:
    status_data = pd.DataFrame(
        columns=["bin_id", "status"]
    )

if "bin_id" not in status_data.columns:
    status_data = pd.DataFrame(
        columns=["bin_id", "status"]
    )

status_map = dict(
    zip(
        status_data["bin_id"],
        status_data["status"]
    )
)

data["status"] = (
    data["bin_id"]
    .map(status_map)
    .fillna("Pending")
)

status_data = data[
    ["bin_id", "status"]
].copy()

status_data.to_csv(
    STATUS_FILE,
    index=False
)


# ==================================================
# BIN STATUS
# ==================================================

critical = len(
    data[data["fill_level"] >= 90]
)

high = len(
    data[
        (data["fill_level"] >= 70) &
        (data["fill_level"] < 90)
    ]
)

normal = len(
    data[data["fill_level"] < 70
    ]
)

collection_required = len(
    data[
        (data["fill_level"] >= 80) &
        (data["status"] != "Collected")
    ]
)

collected = len(
    data[data["status"] == "Collected"]
)


# ==================================================
# SIDEBAR
# ==================================================

st.sidebar.title("🗑️ Smart Waste")

st.sidebar.subheader(
    "Collection Optimizer"
)

st.sidebar.write(
    "Smart waste monitoring, forecasting "
    "and route planning."
)

st.sidebar.divider()

page = st.sidebar.radio(
    "Navigation",
    [
        "🏠 Dashboard",
        "🗑️ Bin Information",
        "🤖 Fill Forecasting",
        "🚛 Route Optimization",
        "📊 Results",
        "ℹ️ About Project"
    ]
)

st.sidebar.divider()

st.sidebar.caption(
    "Smart Waste Collection Optimizer"
)

st.sidebar.caption(
    "Fill-Level Forecasting & Route Planning"
)


# ==================================================
# DASHBOARD
# ==================================================

if page == "🏠 Dashboard":

    st.title(
        "🗑️ Smart Waste Collection Optimizer"
    )

    st.caption(
        "Smart monitoring • Fill-level forecasting • "
        "Route optimization"
    )

    st.divider()

    st.subheader(
        "📊 System Overview"
    )

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric(
            "🗑️ Total Bins",
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

    # Collection summary

    st.subheader(
        "🚛 Collection Summary"
    )

    col1, col2, col3 = st.columns(3)

    with col1:
        st.metric(
            "Bins Requiring Collection",
            collection_required
        )

    with col2:
        st.metric(
            "Collected Bins",
            collected
        )

    with col3:
        pending = len(data) - collected
        st.metric(
            "Pending Bins",
            pending
        )

    st.divider()

    # System status

    st.subheader(
        "🚦 Current System Status"
    )

    if collection_required > 0:

        st.warning(
            f"⚠️ {collection_required} bin(s) "
            "currently require collection."
        )

    else:

        st.success(
            "✅ All bins are currently below "
            "the collection threshold."
        )

    # Collection required

    st.subheader(
        "🚛 Bins Requiring Collection"
    )

    collection_bins = data[
        (data["fill_level"] >= 80) &
        (data["status"] != "Collected")
    ]

    if len(collection_bins) > 0:

        st.dataframe(
            collection_bins,
            use_container_width=True,
            hide_index=True
        )

    else:

        st.success(
            "✅ No bins currently require collection."
        )

    st.divider()

    # Collection status

    st.subheader(
        "📋 Collection Status"
    )

    pending_bins = data[
        data["status"] != "Collected"
    ].copy()

    collected_bins = data[
        data["status"] == "Collected"
    ].copy()

    if len(pending_bins) > 0:

        st.write(
            "Bins waiting for collection:"
        )

        for _, row in pending_bins.iterrows():

            c1, c2, c3 = st.columns(
                [2, 2, 1]
            )

            with c1:

                st.write(
                    f"**{row['bin_id']}** — "
                    f"{row['location']}"
                )

            with c2:

                st.write(
                    f"Fill Level: "
                    f"**{row['fill_level']}%**"
                )

            with c3:

                if st.button(
                    "Mark Collected",
                    key=f"dashboard_collect_{row['bin_id']}"
                ):

                    status_data.loc[
                        status_data["bin_id"]
                        == row["bin_id"],
                        "status"
                    ] = "Collected"

                    status_data.to_csv(
                        STATUS_FILE,
                        index=False
                    )

                    st.success(
                        f"{row['bin_id']} marked as collected."
                    )

                    st.rerun()

    else:

        st.success(
            "✅ All bins have been collected."
        )

    if len(collected_bins) > 0:

        st.write(
            f"**{len(collected_bins)} "
            "bin(s) collected.**"
        )

    st.divider()

    # Project highlight

    st.subheader(
        "💡 Project Highlight"
    )

    st.info(
        "This system combines machine-learning based "
        "fill-level forecasting with OR-Tools route "
        "optimization to support smarter and more "
        "efficient waste collection."
    )


# ==================================================
# BIN INFORMATION
# ==================================================

elif page == "🗑️ Bin Information":

    st.title(
        "🗑️ Bin Information"
    )

    st.caption(
        "View waste-bin locations, fill levels "
        "and collection status."
    )

    st.divider()

    st.dataframe(
        data,
        use_container_width=True,
        hide_index=True
    )

    st.divider()

    st.subheader(
        "🗺️ Waste Bin Locations"
    )

    waste_map = folium.Map(
        location=[
            19.0760,
            72.8777
        ],
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
                f"Fill Level: {row['fill_level']}%<br>"
                f"Status: {row['status']}"
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
        height=550
    )


# ==================================================
# FILL FORECASTING
# ==================================================

elif page == "🤖 Fill Forecasting":

    st.title(
        "🤖 Fill-Level Forecasting"
    )

    st.caption(
        "Predict future waste-bin fill levels "
        "using historical data."
    )

    st.divider()

    selected_bin = st.selectbox(
        "Select Waste Bin",
        data["bin_id"].tolist()
    )

    bin_history = history[
        history["bin_id"] == selected_bin
    ].copy()

    if len(bin_history) >= 2:

        bin_history["day"] = range(
            len(bin_history)
        )

        X = bin_history[["day"]]
        y = bin_history["fill_level"]

        model = LinearRegression()

        model.fit(X, y)

        current_day = (
            len(bin_history) - 1
        )

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

        predictions = [
            max(
                0,
                min(
                    100,
                    value
                )
            )
            for value in predictions
        ]

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

        st.divider()

        st.write(
            "### 📈 Predicted Fill-Level"
        )

        chart_data = pd.DataFrame(
            {
                "Historical Fill Level":
                    bin_history["fill_level"].tolist()
                    + [None, None, None],

                "Predicted Fill Level":
                    [None] * len(bin_history)
                    + predictions
            }
        )

        st.line_chart(
            chart_data,
            y=[
                "Historical Fill Level",
                "Predicted Fill Level"
            ]
        )

        if predictions[0] >= 90:

            st.error(
                "🚨 This bin is predicted to "
                "reach critical level soon!"
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
            "Not enough historical data "
            "for forecasting."
        )


# ==================================================
# ROUTE OPTIMIZATION
# ==================================================

elif page == "🚛 Route Optimization":

    st.title(
        "🚛 Route Optimization"
    )

    st.caption(
        "OR-Tools generates an efficient collection "
        "route for bins that have reached 80% fill level."
    )

    st.divider()

    DEPOT_LAT = 19.0760
    DEPOT_LON = 72.8777

    route_bins = data[
        (data["fill_level"] >= 80) &
        (data["status"] != "Collected")
    ].copy().reset_index(drop=True)

    if len(route_bins) == 0:

        st.success(
            "✅ No bins need collection right now."
        )

    else:

        locations = [
            (
                DEPOT_LAT,
                DEPOT_LON
            )
        ]

        for _, row in route_bins.iterrows():

            locations.append(
                (
                    float(row["latitude"]),
                    float(row["longitude"])
                )
            )

        # Distance function

        def calculate_distance(
            lat1,
            lon1,
            lat2,
            lon2
        ):

            lat_distance = (
                lat1 - lat2
            ) * 111

            lon_distance = (
                lon1 - lon2
            ) * 111 * 0.94

            return math.sqrt(
                lat_distance ** 2 +
                lon_distance ** 2
            )

        # Baseline route

        baseline_distance = 0

        current_lat = DEPOT_LAT
        current_lon = DEPOT_LON

        for _, row in route_bins.iterrows():

            baseline_distance += calculate_distance(
                current_lat,
                current_lon,
                float(row["latitude"]),
                float(row["longitude"])
            )

            current_lat = float(
                row["latitude"]
            )

            current_lon = float(
                row["longitude"]
            )

        baseline_distance += calculate_distance(
            current_lat,
            current_lon,
            DEPOT_LAT,
            DEPOT_LON
        )

        # Distance matrix

        distance_matrix = []

        for from_lat, from_lon in locations:

            row_distances = []

            for to_lat, to_lon in locations:

                lat_distance = (
                    from_lat - to_lat
                ) * 111000

                lon_distance = (
                    from_lon - to_lon
                ) * 111000 * 0.94

                distance = (
                    lat_distance ** 2 +
                    lon_distance ** 2
                ) ** 0.5

                row_distances.append(
                    int(distance)
                )

            distance_matrix.append(
                row_distances
            )

        # OR-Tools

        manager = pywrapcp.RoutingIndexManager(
            len(distance_matrix),
            1,
            0
        )

        routing = pywrapcp.RoutingModel(
            manager
        )

        def distance_callback(
            from_index,
            to_index
        ):

            from_node = manager.IndexToNode(
                from_index
            )

            to_node = manager.IndexToNode(
                to_index
            )

            return distance_matrix[
                from_node
            ][
                to_node
            ]

        transit_callback_index = (
            routing.RegisterTransitCallback(
                distance_callback
            )
        )

        routing.SetArcCostEvaluatorOfAllVehicles(
            transit_callback_index
        )

        search_parameters = (
            pywrapcp.DefaultRoutingSearchParameters()
        )

        search_parameters.first_solution_strategy = (
            routing_enums_pb2
            .FirstSolutionStrategy
            .PATH_CHEAPEST_ARC
        )

        search_parameters.local_search_metaheuristic = (
            routing_enums_pb2
            .LocalSearchMetaheuristic
            .GUIDED_LOCAL_SEARCH
        )

        search_parameters.time_limit.seconds = 5

        solution = routing.SolveWithParameters(
            search_parameters
        )

        if solution:

            index = routing.Start(0)

            route_order = []
            total_distance = 0

            while not routing.IsEnd(index):

                node = manager.IndexToNode(
                    index
                )

                route_order.append(node)

                previous_index = index

                index = solution.Value(
                    routing.NextVar(index)
                )

                total_distance += (
                    routing.GetArcCostForVehicle(
                        previous_index,
                        index,
                        0
                    )
                )

            route_order.append(
                manager.IndexToNode(index)
            )

            optimized_distance = (
                total_distance / 1000
            )

            distance_saved = (
                baseline_distance -
                optimized_distance
            )

            if baseline_distance > 0:

                improvement = (
                    distance_saved /
                    baseline_distance
                ) * 100

            else:

                improvement = 0

            # Performance

            st.subheader(
                "📊 Route Performance"
            )

            col1, col2, col3, col4 = st.columns(4)

            with col1:

                st.metric(
                    "📏 Baseline",
                    f"{baseline_distance:.2f} km"
                )

            with col2:

                st.metric(
                    "🚛 Optimized",
                    f"{optimized_distance:.2f} km"
                )

            with col3:

                st.metric(
                    "💡 Saved",
                    f"{max(0, distance_saved):.2f} km"
                )

            with col4:

                st.metric(
                    "📈 Improvement",
                    f"{max(0, improvement):.1f}%"
                )

            if distance_saved > 0:

                st.success(
                    f"✅ OR-Tools reduced the route by "
                    f"{distance_saved:.2f} km "
                    f"({improvement:.1f}% improvement)."
                )

            else:

                st.info(
                    "ℹ️ The optimized route is similar "
                    "to the baseline route for the "
                    "current bin locations."
                )

            # Comparison chart

            comparison_data = pd.DataFrame(
                {
                    "Route": [
                        "Baseline",
                        "OR-Tools Optimized"
                    ],

                    "Distance (km)": [
                        baseline_distance,
                        optimized_distance
                    ]
                }
            )

            st.write(
                "### 📊 Distance Comparison"
            )

            st.bar_chart(
                comparison_data.set_index("Route")
            )

            st.divider()

            # Route map

            st.write(
                "### 🗺️ Optimized Route Map"
            )

            route_map = folium.Map(
                location=[
                    DEPOT_LAT,
                    DEPOT_LON
                ],
                zoom_start=11
            )

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

            route_coordinates = []

            for stop_number, node in enumerate(
                route_order
            ):

                lat, lon = locations[node]

                route_coordinates.append(
                    [lat, lon]
                )

                if node != 0:

                    bin_position = node - 1

                    bin_row = route_bins.iloc[
                        bin_position
                    ]

                    folium.Marker(
                        location=[
                            lat,
                            lon
                        ],

                        popup=(
                            f"<b>Stop {stop_number}</b><br>"
                            f"Bin: {bin_row['bin_id']}<br>"
                            f"Location: {bin_row['location']}<br>"
                            f"Fill Level: "
                            f"{bin_row['fill_level']}%"
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

            folium.PolyLine(
                locations=route_coordinates,
                weight=5,
                opacity=0.8,
                tooltip="Optimized Collection Route"
            ).add_to(route_map)

            st_folium(
                route_map,
                width=1200,
                height=550
            )

            st.divider()

            # Route information

            col1, col2 = st.columns(2)

            with col1:

                st.metric(
                    "🗑️ Bins to Collect",
                    len(route_bins)
                )

            with col2:

                st.metric(
                    "📏 Route Distance",
                    f"{optimized_distance:.2f} km"
                )

            st.success(
                "✅ Optimized collection route "
                "generated using OR-Tools."
            )

            # Collection order

            st.write(
                "### 📋 Collection Order"
            )

            route_table = []

            for stop_number, node in enumerate(
                route_order
            ):

                if node == 0:

                    route_table.append(
                        {
                            "Stop": stop_number,
                            "Bin": "DEPOT",
                            "Location":
                                "Collection Depot",
                            "Fill Level": "-"
                        }
                    )

                else:

                    bin_position = node - 1

                    bin_row = route_bins.iloc[
                        bin_position
                    ]

                    route_table.append(
                        {
                            "Stop": stop_number,
                            "Bin":
                                bin_row["bin_id"],
                            "Location":
                                bin_row["location"],
                            "Fill Level":
                                f"{bin_row['fill_level']}%"
                        }
                    )

            st.dataframe(
                pd.DataFrame(route_table),
                use_container_width=True,
                hide_index=True
            )

        else:

            st.error(
                "❌ OR-Tools could not generate a route."
            )


# ==================================================
# RESULTS
# ==================================================

elif page == "📊 Results":

    st.title(
        "📊 Project Performance & Results"
    )

    st.caption(
        "Overall performance of the Smart Waste "
        "Collection Optimizer."
    )

    st.divider()

    # Overall statistics

    st.subheader(
        "📌 Overall System Statistics"
    )

    col1, col2, col3, col4 = st.columns(4)

    with col1:

        st.metric(
            "🗑️ Total Bins",
            len(data)
        )

    with col2:

        st.metric(
            "🚛 Collection Required",
            collection_required
        )

    with col3:

        st.metric(
            "✅ Collected",
            collected
        )

    with col4:

        st.metric(
            "🔴 Critical",
            critical
        )

    st.divider()

    # Route results

    st.subheader(
        "🚛 Route Optimization Results"
    )

    route_bins = data[
        (data["fill_level"] >= 80) &
        (data["status"] != "Collected")
    ].copy()

    if len(route_bins) > 0:

        DEPOT_LAT = 19.0760
        DEPOT_LON = 72.8777

        locations = [
            (
                DEPOT_LAT,
                DEPOT_LON
            )
        ]

        for _, row in route_bins.iterrows():

            locations.append(
                (
                    float(row["latitude"]),
                    float(row["longitude"])
                )
            )

        def result_distance(
            lat1,
            lon1,
            lat2,
            lon2
        ):

            lat_distance = (
                lat1 - lat2
            ) * 111

            lon_distance = (
                lon1 - lon2
            ) * 111 * 0.94

            return math.sqrt(
                lat_distance ** 2 +
                lon_distance ** 2
            )

        baseline = 0

        current_lat = DEPOT_LAT
        current_lon = DEPOT_LON

        for _, row in route_bins.iterrows():

            baseline += result_distance(
                current_lat,
                current_lon,
                float(row["latitude"]),
                float(row["longitude"])
            )

            current_lat = float(
                row["latitude"]
            )

            current_lon = float(
                row["longitude"]
            )

        baseline += result_distance(
            current_lat,
            current_lon,
            DEPOT_LAT,
            DEPOT_LON
        )

        matrix = []

        for from_lat, from_lon in locations:

            row_distances = []

            for to_lat, to_lon in locations:

                lat_distance = (
                    from_lat - to_lat
                ) * 111000

                lon_distance = (
                    from_lon - to_lon
                ) * 111000 * 0.94

                distance = math.sqrt(
                    lat_distance ** 2 +
                    lon_distance ** 2
                )

                row_distances.append(
                    int(distance)
                )

            matrix.append(
                row_distances
            )

        manager = pywrapcp.RoutingIndexManager(
            len(matrix),
            1,
            0
        )

        routing = pywrapcp.RoutingModel(
            manager
        )

        def result_callback(
            from_index,
            to_index
        ):

            return matrix[
                manager.IndexToNode(
                    from_index
                )
            ][
                manager.IndexToNode(
                    to_index
                )
            ]

        callback_index = (
            routing.RegisterTransitCallback(
                result_callback
            )
        )

        routing.SetArcCostEvaluatorOfAllVehicles(
            callback_index
        )

        parameters = (
            pywrapcp.DefaultRoutingSearchParameters()
        )

        parameters.first_solution_strategy = (
            routing_enums_pb2
            .FirstSolutionStrategy
            .PATH_CHEAPEST_ARC
        )

        parameters.local_search_metaheuristic = (
            routing_enums_pb2
            .LocalSearchMetaheuristic
            .GUIDED_LOCAL_SEARCH
        )

        parameters.time_limit.seconds = 5

        solution = routing.SolveWithParameters(
            parameters
        )

        if solution:

            index = routing.Start(0)

            optimized = 0

            while not routing.IsEnd(index):

                previous = index

                index = solution.Value(
                    routing.NextVar(index)
                )

                optimized += (
                    routing.GetArcCostForVehicle(
                        previous,
                        index,
                        0
                    )
                )

            optimized = optimized / 1000

            saved = max(
                0,
                baseline - optimized
            )

            if baseline > 0:

                improvement = (
                    saved / baseline
                ) * 100

            else:

                improvement = 0

            col1, col2, col3 = st.columns(3)

            with col1:

                st.metric(
                    "Baseline Distance",
                    f"{baseline:.2f} km"
                )

            with col2:

                st.metric(
                    "Optimized Distance",
                    f"{optimized:.2f} km"
                )

            with col3:

                st.metric(
                    "Distance Saved",
                    f"{saved:.2f} km"
                )

            st.metric(
                "📈 Route Improvement",
                f"{max(0, improvement):.1f}%"
            )

            if improvement > 0:

                st.success(
                    f"🎯 Route efficiency improved by "
                    f"{improvement:.1f}% compared with "
                    f"the baseline route."
                )

            else:

                st.info(
                    "The current bin locations do not "
                    "provide a significant distance reduction."
                )

        else:

            st.warning(
                "Route results are currently unavailable."
            )

    else:

        st.info(
            "No pending bins are currently available "
            "for route comparison."
        )

    st.divider()

    # Final project summary

    st.subheader(
        "🏆 Project Summary"
    )

    st.info(
        "The Smart Waste Collection Optimizer is an "
        "intelligent waste-management system that "
        "monitors bin fill levels, predicts future "
        "fill levels using Linear Regression, identifies "
        "bins requiring collection and generates an "
        "optimized collection route using Google "
        "OR-Tools."
    )

    st.subheader(
        "📝 Project Conclusion"
    )

    st.success(
        "The system demonstrates how machine learning "
        "and route optimization can work together to "
        "support smarter waste collection. By predicting "
        "fill levels and optimizing collection routes, "
        "the system can help reduce unnecessary travel, "
        "save collection time and improve overall "
        "waste-management efficiency."
    )


# ==================================================
# ABOUT PROJECT
# ==================================================

elif page == "ℹ️ About Project":

    st.title(
        "ℹ️ About the Project"
    )

    st.caption(
        "Project overview, technologies and key features."
    )

    st.write(
        "### 🗑️ Smart Waste Collection Optimizer"
    )

    st.write(
        "This project combines fill-level forecasting "
        "and route optimization to improve waste "
        "collection planning."
    )

    st.divider()

    st.subheader(
        "🎯 Project Objective"
    )

    st.write(
        "To identify waste bins that require collection "
        "and generate an efficient route for the collection "
        "vehicle."
    )

    st.subheader(
        "⚙️ Technologies Used"
    )

    st.write(
        """
        - Python
        - Streamlit
        - Pandas
        - Scikit-learn
        - Folium
        - Streamlit-Folium
        - Google OR-Tools
        """
    )

    st.subheader(
        "🤖 Main Features"
    )

    st.write(
        """
        - Waste-bin fill-level monitoring
        - Fill-level forecasting
        - Collection status management
        - Waste-bin map visualization
        - Baseline route calculation
        - OR-Tools route optimization
        - Route distance comparison
        - Performance evaluation
        - Professional dashboard interface
        """
    )

    st.subheader(
        "💡 Expected Benefit"
    )

    st.write(
        "The system can help reduce unnecessary travel, "
        "save collection time and improve waste-management "
        "efficiency."
    )

    st.divider()

    st.subheader(
        "🏆 Final Project Statement"
    )

    st.success(
        "Smart Waste Collection Optimizer provides a "
        "complete workflow from waste-bin monitoring and "
        "prediction to optimized collection planning."
    )