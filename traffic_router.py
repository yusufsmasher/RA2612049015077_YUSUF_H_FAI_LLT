"""Reusable routing logic for the Chennai smart traffic project."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

import networkx as nx
import numpy as np
import osmnx as ox
import pandas as pd
from scipy.spatial import cKDTree


PROJECT_DIR = Path(__file__).resolve().parent
GRAPH_FILE = PROJECT_DIR / "chennai_roads.graphml"
TRAFFIC_FILES = {
    "Normal": PROJECT_DIR / "chennai_traffic_dataset.csv",
    "Medium": PROJECT_DIR / "chennai_traffic_MEDIUM.csv",
    "Heavy": PROJECT_DIR / "chennai_traffic_HEAVY.csv",
}

DEFAULT_START = (13.114385, 80.23872)
DEFAULT_DESTINATION = (12.924996, 80.099676)
DEFAULT_START_NAME = "Perambur - Vyasarpadi"
DEFAULT_DESTINATION_NAME = "Tambaram Bypass"

_REQUIRED_COLUMNS = {"latitude", "longitude", "speed"}
_MAX_SPEED_KMH = 120.0
_MIN_SPEED_KMH = 5.0


@dataclass(frozen=True)
class RouteResult:
    """A route and its estimated travel time for one traffic condition."""

    condition: str
    route: list[int]
    time_seconds: float
    street_names: list[str]

    @property
    def node_count(self) -> int:
        return len(self.route)

    @property
    def time_minutes(self) -> float:
        return self.time_seconds / 60


def load_graph(path: Path = GRAPH_FILE) -> nx.MultiDiGraph:
    """Load the saved OSMnx road graph."""
    if not path.is_file():
        raise FileNotFoundError(f"Road graph not found: {path}")
    return ox.load_graphml(path)


def load_traffic_datasets(
    files: Mapping[str, Path] = TRAFFIC_FILES,
) -> dict[str, pd.DataFrame]:
    """Load and validate the traffic data for all scenarios."""
    datasets: dict[str, pd.DataFrame] = {}
    for condition, path in files.items():
        if not path.is_file():
            raise FileNotFoundError(
                f"{condition} traffic dataset not found: {path}"
            )

        dataset = pd.read_csv(path)
        missing_columns = _REQUIRED_COLUMNS.difference(dataset.columns)
        if missing_columns:
            missing = ", ".join(sorted(missing_columns))
            raise ValueError(
                f"{path.name} is missing required columns: {missing}"
            )

        for column in _REQUIRED_COLUMNS:
            dataset[column] = pd.to_numeric(dataset[column], errors="coerce")

        valid_coordinates = np.isfinite(
            dataset[["latitude", "longitude"]]
        ).all(axis=1)
        valid_speeds = dataset["speed"].isna() | np.isfinite(dataset["speed"])
        if not valid_coordinates.all() or not valid_speeds.all():
            invalid_count = int((~(valid_coordinates & valid_speeds)).sum())
            raise ValueError(
                f"{path.name} contains {invalid_count} rows with invalid "
                "coordinates or speed values"
            )

        if dataset["speed"].notna().sum() == 0:
            raise ValueError(f"{path.name} contains no valid speed observations")
        datasets[condition] = dataset

    return datasets


def _observed_node_speeds(
    graph: nx.MultiDiGraph, dataset: pd.DataFrame
) -> pd.Series:
    nearest_nodes = ox.distance.nearest_nodes(
        graph,
        X=dataset["longitude"].to_numpy(),
        Y=dataset["latitude"].to_numpy(),
    )
    observations = dataset.assign(nearest_node=nearest_nodes)
    return observations.groupby("nearest_node")["speed"].mean()


def _interpolate_node_speeds(
    projected_graph: nx.MultiDiGraph, observed_speeds: pd.Series
) -> dict[int, float]:
    node_ids = list(projected_graph.nodes)
    node_xy = np.asarray(
        [
            [projected_graph.nodes[node]["x"], projected_graph.nodes[node]["y"]]
            for node in node_ids
        ],
        dtype=float,
    )

    observed_ids = [
        node for node in observed_speeds.index if node in projected_graph
    ]
    if not observed_ids:
        raise ValueError("No traffic observations matched a road-network node")

    observed_xy = np.asarray(
        [
            [projected_graph.nodes[node]["x"], projected_graph.nodes[node]["y"]]
            for node in observed_ids
        ],
        dtype=float,
    )
    observed_values = observed_speeds.loc[observed_ids].to_numpy(dtype=float)

    nearest_indices = cKDTree(observed_xy).query(node_xy)[1]
    nearest_speeds = observed_values[nearest_indices]
    bounded_speeds = np.clip(
        nearest_speeds, _MIN_SPEED_KMH, _MAX_SPEED_KMH
    )
    return dict(zip(node_ids, bounded_speeds.tolist()))


def _assign_edge_travel_times(
    graph: nx.MultiDiGraph, node_speeds: Mapping[int, float], condition: str
) -> str:
    weight = f"time_{condition.lower()}"
    for u, v, _, edge_data in graph.edges(keys=True, data=True):
        length_m = float(edge_data["length"])
        average_speed_kmh = (node_speeds[u] + node_speeds[v]) / 2
        edge_data[weight] = length_m / (average_speed_kmh / 3.6)
    return weight


def _route_time(
    graph: nx.MultiDiGraph, route: list[int], weight: str
) -> float:
    total_seconds = 0.0
    for u, v in zip(route, route[1:]):
        parallel_edges = graph.get_edge_data(u, v)
        if not parallel_edges:
            raise ValueError(f"Route contains a missing edge: {u} -> {v}")
        total_seconds += min(float(edge[weight]) for edge in parallel_edges.values())
    return total_seconds


def route_street_names(
    graph: nx.MultiDiGraph, route: list[int], weight: str
) -> list[str]:
    """Return consecutive-deduplicated street names along a route."""
    street_names: list[str] = []
    for u, v in zip(route, route[1:]):
        parallel_edges = graph.get_edge_data(u, v)
        if not parallel_edges:
            raise ValueError(f"Route contains a missing edge: {u} -> {v}")

        edge = min(
            parallel_edges.values(),
            key=lambda data: float(data[weight]),
        )
        name = edge.get("name", "Unnamed Road")
        if isinstance(name, list):
            name = ", ".join(str(part) for part in name)
        street_name = str(name).strip() if name else "Unnamed Road"
        if not street_name:
            street_name = "Unnamed Road"

        if not street_names or street_names[-1] != street_name:
            street_names.append(street_name)

    return street_names


def calculate_routes(
    graph: nx.MultiDiGraph,
    datasets: Mapping[str, pd.DataFrame],
    start: tuple[float, float] = DEFAULT_START,
    destination: tuple[float, float] = DEFAULT_DESTINATION,
) -> list[RouteResult]:
    """Calculate fastest A* routes for each supplied traffic scenario.

    Coordinates are (latitude, longitude) pairs.
    """
    if not datasets:
        raise ValueError("At least one traffic dataset is required")

    start_node = ox.distance.nearest_nodes(
        graph, X=start[1], Y=start[0]
    )
    destination_node = ox.distance.nearest_nodes(
        graph, X=destination[1], Y=destination[0]
    )
    projected_graph = ox.project_graph(graph)
    scenario_speeds: dict[str, dict[int, float]] = {}

    for condition, dataset in datasets.items():
        missing_columns = _REQUIRED_COLUMNS.difference(dataset.columns)
        if missing_columns:
            missing = ", ".join(sorted(missing_columns))
            raise ValueError(
                f"{condition} dataset is missing required columns: {missing}"
            )
        observed_speeds = _observed_node_speeds(graph, dataset)
        scenario_speeds[condition] = _interpolate_node_speeds(
            projected_graph, observed_speeds
        )

    def heuristic(node: int, target: int) -> float:
        node_data = graph.nodes[node]
        target_data = graph.nodes[target]
        distance_m = ox.distance.great_circle(
            node_data["y"],
            node_data["x"],
            target_data["y"],
            target_data["x"],
        )
        return float(distance_m) / (_MAX_SPEED_KMH / 3.6)

    results: list[RouteResult] = []
    for condition, node_speeds in scenario_speeds.items():
        weight = _assign_edge_travel_times(graph, node_speeds, condition)
        try:
            route = nx.astar_path(
                graph,
                start_node,
                destination_node,
                heuristic=heuristic,
                weight=weight,
            )
        except nx.NetworkXNoPath as exc:
            raise ValueError(
                f"No route found for {condition.lower()} traffic"
            ) from exc

        results.append(
            RouteResult(
                condition=condition,
                route=route,
                time_seconds=_route_time(graph, route, weight),
                street_names=route_street_names(graph, route, weight),
            )
        )

    return results


def run_routing(
    start: tuple[float, float] = DEFAULT_START,
    destination: tuple[float, float] = DEFAULT_DESTINATION,
    graph_path: Path = GRAPH_FILE,
    traffic_files: Mapping[str, Path] = TRAFFIC_FILES,
) -> list[RouteResult]:
    """Load project data and calculate routes; suitable for a future UI."""
    graph = load_graph(graph_path)
    datasets = load_traffic_datasets(traffic_files)
    return calculate_routes(graph, datasets, start, destination)
