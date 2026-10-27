"""Streamlit interface for the Chennai smart traffic router."""

from __future__ import annotations

import io

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import osmnx as ox
import pandas as pd
import streamlit as st

from traffic_router import (
    DEFAULT_DESTINATION_NAME,
    DEFAULT_START_NAME,
    GRAPH_FILE,
    TRAFFIC_FILES,
    RouteResult,
    load_graph,
    run_routing,
)


LOCATION_DATA_FILE = TRAFFIC_FILES["Normal"]
ROUTE_COLORS = {"Normal": "green", "Medium": "orange", "Heavy": "red"}


st.set_page_config(
    page_title="Chennai Smart Traffic Router",
    page_icon="🚦",
    layout="wide",
)


@st.cache_data
def load_corridors() -> pd.DataFrame:
    """Return one representative coordinate per corridor."""
    data = pd.read_csv(LOCATION_DATA_FILE)
    required = {"corridor", "latitude", "longitude"}
    missing = required.difference(data.columns)
    if missing:
        raise ValueError(
            f"{LOCATION_DATA_FILE.name} is missing required columns: "
            f"{', '.join(sorted(missing))}"
        )

    data["latitude"] = pd.to_numeric(data["latitude"], errors="coerce")
    data["longitude"] = pd.to_numeric(data["longitude"], errors="coerce")
    data = data.dropna(subset=["corridor", "latitude", "longitude"])
    locations = (
        data.groupby("corridor", as_index=False)[["latitude", "longitude"]]
        .mean()
        .sort_values("corridor")
        .reset_index(drop=True)
    )
    if locations.empty:
        raise ValueError(
            f"No valid corridor coordinates found in {LOCATION_DATA_FILE.name}"
        )
    return locations


@st.cache_resource
def get_graph():
    """Load the road graph once for rendering route maps."""
    return load_graph(GRAPH_FILE)


@st.cache_data(show_spinner="Calculating the three traffic routes...")
def calculate_for_coordinates(
    start_latitude: float,
    start_longitude: float,
    destination_latitude: float,
    destination_longitude: float,
) -> list[RouteResult]:
    """Calculate routes for the selected corridor coordinates."""
    return run_routing(
        start=(start_latitude, start_longitude),
        destination=(destination_latitude, destination_longitude),
    )


def route_png(graph, result: RouteResult) -> bytes:
    """Render a route as PNG bytes for display and download."""
    figure, _ = ox.plot_graph_route(
        graph,
        result.route,
        route_color=ROUTE_COLORS.get(result.condition, "blue"),
        route_linewidth=3,
        node_size=0,
        bgcolor="white",
        figsize=(9, 9),
        show=False,
        close=False,
    )
    image = io.BytesIO()
    figure.savefig(image, format="png", dpi=180, bbox_inches="tight")
    plt.close(figure)
    return image.getvalue()


st.title("Chennai Smart Traffic Router")
st.write(
    "Choose start and destination corridors. The app uses each corridor's "
    "average latitude and longitude from the Normal traffic dataset, then "
    "compares routes under Normal, Medium, and Heavy traffic."
)

try:
    corridors = load_corridors()
except (FileNotFoundError, ValueError, OSError) as exc:
    st.error(f"Could not load corridor locations: {exc}")
    st.stop()

locations = corridors.set_index("corridor")
corridor_names = corridors["corridor"].tolist()
start_default = (
    corridor_names.index(DEFAULT_START_NAME)
    if DEFAULT_START_NAME in corridor_names
    else 0
)
destination_default = (
    corridor_names.index(DEFAULT_DESTINATION_NAME)
    if DEFAULT_DESTINATION_NAME in corridor_names
    else min(1, len(corridor_names) - 1)
)

with st.form("route_selection"):
    source_column, destination_column = st.columns(2)
    with source_column:
        source_name = st.selectbox(
            "Source corridor",
            corridor_names,
            index=start_default,
        )
    with destination_column:
        destination_name = st.selectbox(
            "Destination corridor",
            corridor_names,
            index=destination_default,
        )

    source = locations.loc[source_name]
    destination = locations.loc[destination_name]
    st.caption(
        f"Source coordinates: {source['latitude']:.6f}, "
        f"{source['longitude']:.6f}  |  "
        f"Destination coordinates: {destination['latitude']:.6f}, "
        f"{destination['longitude']:.6f}"
    )
    submitted = st.form_submit_button("Find routes", type="primary")

selected_pair = (source_name, destination_name)
if submitted:
    if source_name == destination_name:
        st.session_state.pop("route_results", None)
        st.session_state.pop("route_pair", None)
        st.warning("Choose two different corridors to calculate a route.")
    else:
        try:
            results = calculate_for_coordinates(
                float(source["latitude"]),
                float(source["longitude"]),
                float(destination["latitude"]),
                float(destination["longitude"]),
            )
        except (FileNotFoundError, ValueError, OSError) as exc:
            st.error(f"Could not calculate routes: {exc}")
            st.stop()
        st.session_state["route_results"] = results
        st.session_state["route_pair"] = selected_pair

results = st.session_state.get("route_results")
if results and st.session_state.get("route_pair") == selected_pair:
    best = min(results, key=lambda route: route.time_seconds)
    st.subheader(f"{source_name} to {destination_name}")
    st.success(
        f"Fastest estimated route: {best.condition} traffic "
        f"({best.time_minutes:.2f} minutes)"
    )

    table = pd.DataFrame(
        [
            {
                "Traffic condition": result.condition,
                "Route nodes": result.node_count,
                "Estimated time (minutes)": round(result.time_minutes, 2),
            }
            for result in results
        ]
    )
    st.subheader("Route comparison")
    selection = st.dataframe(
        table,
        hide_index=True,
        width="stretch",
        on_select="rerun",
        selection_mode="single-row",
        key=f"route-comparison-{source_name}-{destination_name}",
    )
    selected_rows = selection.selection.rows
    if selected_rows:
        selected_result = results[selected_rows[0]]
        itinerary = "\n".join(
            f"{step}. {street_name}"
            for step, street_name in enumerate(
                selected_result.street_names, start=1
            )
        )
        node_ids = ", ".join(str(node) for node in selected_result.route)
        st.code(
            f"=== STREET-BY-STREET TRAVEL PATH "
            f"({selected_result.condition.upper()} ROUTE) ===\n"
            f"{itinerary}\n\n"
            f"=== ALL {selected_result.node_count} NODE IDS IN SEQUENCE ===\n"
            f"[{node_ids}]",
            language="text",
            wrap_lines=True,
        )
    else:
        st.caption(
            "Click a row in the comparison table to view its street itinerary "
            "and complete route node sequence."
        )

    st.download_button(
        "Download comparison CSV",
        data=table.to_csv(index=False).encode("utf-8"),
        file_name="chennai_astar_results.csv",
        mime="text/csv",
    )

    st.subheader("Route maps")
    try:
        graph = get_graph()
        tabs = st.tabs([f"{result.condition} traffic" for result in results])
        for tab, result in zip(tabs, results):
            with tab:
                png = route_png(graph, result)
                st.image(
                    png,
                    caption=(
                        f"{result.condition} traffic route — "
                        f"{result.time_minutes:.2f} minutes, "
                        f"{result.node_count} nodes"
                    ),
                    width="stretch",
                )
                st.download_button(
                    f"Download {result.condition.lower()} route PNG",
                    data=png,
                    file_name=f"chennai_{result.condition.lower()}_route.png",
                    mime="image/png",
                    key=f"download-{result.condition.lower()}",
                )
    except (FileNotFoundError, ValueError, OSError) as exc:
        st.error(f"Could not display route maps: {exc}")
elif not submitted:
    st.info("Select two corridors and click **Find routes** to view the results.")
