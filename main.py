"""Command-line entry point for the Chennai smart traffic router."""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import osmnx as ox

from traffic_router import (
    DEFAULT_DESTINATION,
    DEFAULT_DESTINATION_NAME,
    DEFAULT_START,
    DEFAULT_START_NAME,
    GRAPH_FILE,
    TRAFFIC_FILES,
    RouteResult,
    load_graph,
    run_routing,
)


PROJECT_DIR = Path(__file__).resolve().parent


def _write_results(results: list[RouteResult], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.writer(output)
        writer.writerow(
            ["Traffic Condition", "Route Nodes", "Estimated Time (minutes)"]
        )
        for result in results:
            writer.writerow(
                [
                    result.condition,
                    result.node_count,
                    f"{result.time_minutes:.2f}",
                ]
            )


def _save_route_maps(results: list[RouteResult], graph_path: Path) -> None:
    graph = load_graph(graph_path)
    colors = {"Normal": "green", "Medium": "orange", "Heavy": "red"}
    for result in results:
        figure, _ = ox.plot_graph_route(
            graph,
            result.route,
            route_color=colors.get(result.condition, "blue"),
            route_linewidth=3,
            node_size=0,
            bgcolor="white",
            show=False,
            close=False,
        )
        figure.savefig(
            PROJECT_DIR / f"chennai_{result.condition.lower()}_route.png",
            dpi=300,
            bbox_inches="tight",
        )
        plt.close(figure)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare Chennai routes under different traffic scenarios."
    )
    parser.add_argument("--start-name", default=DEFAULT_START_NAME)
    parser.add_argument("--destination-name", default=DEFAULT_DESTINATION_NAME)
    parser.add_argument("--start-lat", type=float, default=DEFAULT_START[0])
    parser.add_argument("--start-lon", type=float, default=DEFAULT_START[1])
    parser.add_argument(
        "--destination-lat", type=float, default=DEFAULT_DESTINATION[0]
    )
    parser.add_argument(
        "--destination-lon", type=float, default=DEFAULT_DESTINATION[1]
    )
    parser.add_argument("--graph", type=Path, default=GRAPH_FILE)
    parser.add_argument(
        "--results", type=Path, default=PROJECT_DIR / "chennai_astar_results.csv"
    )
    parser.add_argument(
        "--skip-maps",
        action="store_true",
        help="Do not generate or overwrite the route map PNG files.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    start = (args.start_lat, args.start_lon)
    destination = (args.destination_lat, args.destination_lon)

    try:
        results = run_routing(
            start=start,
            destination=destination,
            graph_path=args.graph,
            traffic_files=TRAFFIC_FILES,
        )
        _write_results(results, args.results)
        if not args.skip_maps:
            _save_route_maps(results, args.graph)
    except (FileNotFoundError, ValueError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(f"Route comparison: {args.start_name} -> {args.destination_name}")
    print(f"{'Traffic':<10} {'Nodes':>8} {'Estimated time':>18}")
    for result in results:
        print(
            f"{result.condition:<10} {result.node_count:>8} "
            f"{result.time_minutes:>15.2f} min"
        )
    best = min(results, key=lambda result: result.time_seconds)
    print(
        f"\nFastest estimate: {best.condition} traffic "
        f"({best.time_minutes:.2f} min)"
    )
    print(f"Results CSV: {args.results.resolve()}")
    if not args.skip_maps:
        print("Route maps saved as chennai_<condition>_route.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
