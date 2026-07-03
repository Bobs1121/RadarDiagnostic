# V3 Design: Module B - Heterogeneous Data Explorer

## 1. Architectural Role & Objective

As defined in the V3 Master Architecture, the **Heterogeneous Data Explorer** serves as the critical "Data Logs" pillar in the AI Triage Loop (Req -> Code -> Data). Its primary mandate is to process GB-scale vehicle telemetry files (ROS Bag, BLF, MF4) with **zero-latency** and **OOM-proof** reliability on standard engineering laptops. 

It provides the empirical truth layer: allowing human engineers to visualize anomalies offline, and the LangGraph Agent to mathematically verify requirement violations against raw sensor and CAN bus data.

## 2. The DuckDB Pipeline: Ingestion & Querying

To process massive datasets offline without crushing system RAM (OOM errors), this module strictly bans monolithic `pandas.DataFrame` concatenation. Instead, it leverages a highly efficient streaming **Apache Arrow -> Parquet -> DuckDB** pipeline.

### Ingestion Flow
1. **Chunked Parsing**: Native parsers (`asammdf` for MF4, `cantools` for BLF, `rosbags` for Bag) read the raw binary vehicle logs in strictly bounded, memory-efficient chunks.
2. **Arrow IPC / Parquet Serialization**: Parsed chunks are immediately converted into Apache Arrow RecordBatches. Instead of accumulating in memory, these batches are flushed sequentially to local, compressed `.parquet` files on disk within the project workspace (e.g., `.workspaces/<variant>/.cache/data/`).
3. **DuckDB In-Memory Views**: DuckDB never eagerly loads the `.parquet` files into memory. Instead, it creates a lightweight virtual view over the directory:
   ```sql
   CREATE VIEW v_vehicle_signals AS 
   SELECT * FROM read_parquet('.workspaces/<variant>/.cache/data/*.parquet');
   ```
   This allows execution of complex analytical queries directly against the disk-backed Parquet files using DuckDB's advanced vectorized execution engine.

### Memory Management Strategy
* **Zero-Copy**: The Arrow memory format ensures data doesn't need expensive deserialization when passing from the parser to disk.
* **Columnar Pruning**: When the Agent executes a query like `SELECT ego_speed FROM v_vehicle_signals`, DuckDB only reads the bytes associated with the `ego_speed` column from the Parquet file, skipping hundreds of other multiplexed signals.

## 3. TimeSync: Native DuckDB Alignment

A major challenge in heterogeneous ADAS analysis is synchronizing disparate logging formats (e.g., ROS bags using epoch timestamps vs. CAN logs using monotonic hardware ticks). V3 solves this entirely within the DuckDB SQL engine using native **ASOF JOINs**.

### Alignment Strategy
1. **Unified Schema**: All generated Parquet files enforce a standardized schema containing at least a `sys_time` (normalized UNIX epoch) and `log_time` (original format time base).
2. **Time Anchoring**: When a file is loaded, a reference anchor (e.g., the first message timestamp or hardware trigger event) is stored in the workspace metadata.
3. **SQL ASOF JOIN**: To query a ROS perception signal alongside a CAN chassis signal, the engine generates an `ASOF JOIN` (As-Of Join). This native operation efficiently finds the closest preceding timestamp in the right table for every timestamp in the left table, entirely replacing slow, memory-intensive Python interpolation loops (`pandas.merge_asof`).

```sql
-- Example: Natively aligning CAN chassis speed with ROS perception bounding boxes
SELECT 
    ros.sys_time,
    ros.target_distance_x,
    can.ego_speed
FROM v_ros_perception ros
ASOF JOIN v_can_chassis can 
  ON ros.sys_time >= can.sys_time
WHERE ros.sys_time BETWEEN 1689000000 AND 1689000100;
```

## 4. Tool Interfaces for the LangGraph Agent

The LangGraph Orchestrator interacts with the Data Explorer exclusively through highly constrained, Pydantic-validated tool signatures. These interfaces are designed to return minimal, high-signal data to preserve LLM context windows and reduce token spend.

### `query_signal_duckdb(query: str) -> dict`
Executes an arbitrary DuckDB SQL query against the data views. It is expected to return aggregated metrics, extrema, or booleans, *not* full raw time series.
```python
def query_signal_duckdb(query: str) -> dict:
    """
    Executes a DuckDB SQL query against the loaded vehicle data views.
    
    Args:
        query: A valid DuckDB SQL string (e.g., "SELECT MAX(ego_speed) FROM v_can").
        
    Returns:
        JSON dictionary containing up to the first 100 rows or aggregation results.
    """
```

### `probe_time_window(start_t: float, end_t: float, signals: list[str]) -> list[dict]`
Fetches a specific slice of data for localized inspection. Automatically downsamples the output using techniques like LTTB (Largest Triangle Three Buckets) to max 50 points to prevent LLM context overflow.
```python
def probe_time_window(start_t: float, end_t: float, signals: list[str]) -> list[dict]:
    """
    Retrieves and downsamples time-series data for specific signals within a narrow window.
    
    Args:
        start_t: Start system epoch time.
        end_t: End system epoch time.
        signals: List of exact signal names (e.g., ["ego_speed", "fcta_alert"]).
        
    Returns:
        List of dictionaries mapping timestamps to signal values.
    """
```

### `detect_anomalies(condition_sql: str) -> list[tuple]`
A high-level extraction tool. The Agent provides a logical violation condition, and DuckDB computes the specific time intervals where the condition evaluates to true.
```python
def detect_anomalies(condition_sql: str) -> list[tuple]:
    """
    Finds exact time ranges where a defined SQL condition is continuously met.
    
    Args:
        condition_sql: A SQL WHERE clause (e.g., "ego_speed > 60 AND fcta_alert == 0").
        
    Returns:
        List of tuples representing anomalous time windows: [(start_t1, end_t1), ...]
    """
```

## 5. Operational Modes: Standalone vs. Composed

The Data Explorer module respects the vertical axis of the V3 Matrix Architecture, functioning independently as both a human-facing CLI tool and a programmatic Agentic API.

### 1. Standalone Mode: CLI Human Interaction
Engineers can use the CLI to directly bypass the AI and perform offline plotting and extraction with zero setup and zero latency.
* **Usage**: `python cli.py data plot --file logs/test1.mf4 --signals "Ego_Speed, FCTA_Warn"`
* **Execution**: 
  1. The CLI streams the target MF4 directly into the Parquet cache.
  2. DuckDB executes a dynamic `SELECT` with fast Min/Max downsampling over the requested signals.
  3. The output is instantly piped to `matplotlib` or `plotly` to render an interactive HTML chart or static PNG. The engineer receives immediate visual feedback on GBs of data without memory stalls.

### 2. Composed Mode: AI Triage Agent
When invoked by the Full-Link LangGraph Agent, the module operates silently, structurally, and programmatically.
* **Usage**: The Agent formulates a hypothesis (e.g., "The brake was applied but deceleration was inadequate"), writes the DuckDB SQL, and calls `detect_anomalies()`.
* **Execution**:
  1. The Agent receives only the boundaries (time ranges) of the anomaly via JSON.
  2. The Agent is intentionally restricted from requesting full-resolution plots during the reasoning cycle, saving massive LLM token overhead.
  3. Once the root cause is mathematically deduced, the Agent can optionally issue a command to the Data Explorer to generate an SVG snippet of the isolated anomaly window to be embedded directly into the final diagnostic Markdown report.

---
*Architecture designed by Claude Opus 4.8 — Principal Data Architect*