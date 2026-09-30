"""Route planning: constraint-aware OR-Tools optimisation vs. two baselines.

Baselines (what the brief asks us to beat):
  * fixed_round   - the current process: visit every bin in a fixed list order, no fill-level logic
  * business_rule - "empty the fullest bins first" (a rule a supervisor would actually use)
  * nearest_neighbour - classic greedy heuristic
Optimised: OR-Tools vehicle routing with truck capacity + a penalty for skipping a bin.
All baselines respect the same truck capacity by starting a new trip when the truck is full.
"""
import math

DEPOT = (19.0760, 72.8777)  # depot lat, lon (Mumbai)


def haversine_km(a, b):
    """Great-circle distance in km (replaces the old 111 km * 0.94 approximation)."""
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * 6371.0088 * math.asin(math.sqrt(h))


def _load(b):
    return float(b["fill_level"]) / 100.0 * float(b.get("capacity", 100))


def _split_trips(order, capacity):
    """Cut an ordered list of bins into trips that fit the truck capacity."""
    trips, cur, load = [], [], 0.0
    for b in order:
        if cur and load + _load(b) > capacity:
            trips.append(cur)
            cur, load = [], 0.0
        cur.append(b)
        load += _load(b)
    if cur:
        trips.append(cur)
    return trips


def trips_distance(trips, depot=DEPOT):
    total = 0.0
    for trip in trips:
        pts = [depot] + [(b["latitude"], b["longitude"]) for b in trip] + [depot]
        total += sum(haversine_km(pts[i], pts[i + 1]) for i in range(len(pts) - 1))
    return total


def fixed_round(bins, capacity, depot=DEPOT):
    """Baseline 1: list order (bins.csv order) - no optimisation."""
    return _split_trips(list(bins), capacity)


def business_rule(bins, capacity, depot=DEPOT):
    """Baseline 2: fullest first."""
    return _split_trips(sorted(bins, key=lambda b: -b["fill_level"]), capacity)


def nearest_neighbour(bins, capacity, depot=DEPOT):
    """Baseline 3: always drive to the closest unvisited bin."""
    left, order, pos = list(bins), [], depot
    while left:
        nxt = min(left, key=lambda b: haversine_km(pos, (b["latitude"], b["longitude"])))
        order.append(nxt)
        left.remove(nxt)
        pos = (nxt["latitude"], nxt["longitude"])
    return _split_trips(order, capacity)


def ortools_routes(bins, capacity, num_trucks=2, depot=DEPOT, time_limit_s=5, skip_penalty_km=500):
    """Capacitated VRP. Returns (trips, dropped_bins). Needs `ortools` (imported lazily)."""
    from ortools.constraint_solver import pywrapcp, routing_enums_pb2

    if not bins:
        return [], []
    pts = [depot] + [(b["latitude"], b["longitude"]) for b in bins]
    dist = [[int(haversine_km(a, b) * 1000) for b in pts] for a in pts]  # metres
    demand = [0] + [int(math.ceil(_load(b))) for b in bins]
    baseline_trips = len(_split_trips(list(bins), capacity))
    vehicles = max(num_trucks, baseline_trips)  # never fewer trucks than the baselines need

    manager = pywrapcp.RoutingIndexManager(len(pts), vehicles, 0)
    routing = pywrapcp.RoutingModel(manager)
    cb = routing.RegisterTransitCallback(lambda i, j: dist[manager.IndexToNode(i)][manager.IndexToNode(j)])
    routing.SetArcCostEvaluatorOfAllVehicles(cb)
    dem = routing.RegisterUnaryTransitCallback(lambda i: demand[manager.IndexToNode(i)])
    routing.AddDimensionWithVehicleCapacity(dem, 0, [int(capacity)] * vehicles, True, "Capacity")
    for node in range(1, len(pts)):  # allow skipping a bin only at a heavy cost
        routing.AddDisjunction([manager.NodeToIndex(node)], int(skip_penalty_km * 1000))

    params = pywrapcp.DefaultRoutingSearchParameters()
    params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    params.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    params.time_limit.seconds = time_limit_s
    sol = routing.SolveWithParameters(params)
    if not sol:
        return [], list(bins)

    trips, visited = [], set()
    for v in range(vehicles):
        idx, trip = routing.Start(v), []
        while not routing.IsEnd(idx):
            node = manager.IndexToNode(idx)
            if node:
                trip.append(bins[node - 1])
                visited.add(node - 1)
            idx = sol.Value(routing.NextVar(idx))
        if trip:
            trips.append(trip)
    dropped = [b for i, b in enumerate(bins) if i not in visited]
    return trips, dropped


def compare(bins, capacity=300, num_trucks=2, depot=DEPOT):
    """Run all strategies and return {name: {trips, km}} plus dropped bins for OR-Tools."""
    res = {}
    for name, fn in [("Fixed round (current process)", fixed_round),
                     ("Business rule (fullest first)", business_rule),
                     ("Nearest neighbour heuristic", nearest_neighbour)]:
        t = fn(bins, capacity, depot)
        res[name] = {"trips": t, "km": trips_distance(t, depot)}
    t, dropped = ortools_routes(bins, capacity, num_trucks, depot)
    res["OR-Tools (capacity-aware)"] = {"trips": t, "km": trips_distance(t, depot), "dropped": dropped}
    return res
