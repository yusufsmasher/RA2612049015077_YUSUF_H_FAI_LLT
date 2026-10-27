# Chennai Smart Traffic Router

This Python application extracts the routing workflow from the Jupyter
notebook into reusable Python code. It uses the saved Chennai road graph,
matches traffic observations to nearby road nodes, estimates road-edge travel
times for Normal, Medium, and Heavy traffic, and finds a fastest route for each
scenario with A*.

The default journey is Perambur - Vyasarpadi to Tambaram Bypass. It uses the
included GraphML and CSV data files, so it does not download the road network
when run.

## Setup

Open a terminal in this project folder and install dependencies into the same
Python environment you select for this project:

```powershell
py -3.14 -m pip install -r requirements.txt
```

If you use a different Python version, replace `3.14` with that version. In
VS Code, select the same interpreter with **Python: Select Interpreter**.

## Run

```powershell
py -3.14 main.py
```

The application prints route node counts and estimated times, writes
`chennai_astar_results.csv`, and creates one route map PNG per scenario. To
skip map generation:

```powershell
py -3.14 main.py --skip-maps
```

## Run the UI

Install the requirements if you have not already, then start Streamlit:

```powershell
py -3.14 -m pip install -r requirements.txt
py -3.14 -m streamlit run app.py
```

The browser UI lets you choose a source and destination from the corridor
names in `chennai_traffic_dataset.csv`. It uses the average coordinates for
each selected corridor, displays those coordinates, and shows the three route
maps with a comparison table and CSV download. Click a row in the comparison
table to view that scenario's ordered road-node IDs.
The selected route details include a consecutive-deduplicated street
itinerary and the complete ordered node-ID sequence.

## Deploy to Streamlit Community Cloud

Create the app from this public repository and set **Main file path** to
`app.py` (not `main.py`, which is the command-line entry point). Keep the app's
working directory at the repository root so the graph and CSV data files are
available. Streamlit Cloud installs the dependencies from `requirements.txt`.

To try a different pair of coordinates, provide latitude and longitude:

```powershell
py -3.14 main.py --start-lat 13.114385 --start-lon 80.23872 `
  --destination-lat 12.924996 --destination-lon 80.099676 `
  --start-name "Start location" --destination-name "Destination"
```

## Use from another Python program

`traffic_router.py` exposes `run_routing()` for a future front end or API:

```python
from traffic_router import run_routing

routes = run_routing(
    start=(13.114385, 80.23872),
    destination=(12.924996, 80.099676),
)

for route in routes:
    print(route.condition, route.node_count, route.time_minutes)
```

Coordinates passed to `run_routing()` are `(latitude, longitude)` tuples.
`RouteResult` also includes the full ordered list of graph node IDs in
`route.route`.

## Files

- `main.py` — command-line interface, result CSV, and optional route maps.
- `app.py` — Streamlit interface for choosing corridors and viewing route results.
- `traffic_router.py` — reusable data-loading and route-calculation functions.
- `chennai_roads.graphml` — saved OSMnx road network.
- `chennai_traffic*.csv` — Normal, Medium, and Heavy traffic observations.
