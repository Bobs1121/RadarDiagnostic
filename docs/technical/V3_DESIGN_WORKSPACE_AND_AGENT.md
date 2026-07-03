# V3 Design: Workspace Isolation & Triage Agent Loop

This document details the architectural design for the Horizontal Workspace Isolation mechanism and the Full-Link Triage Agent Loop (Modules C & Horizontal) for radarAnalyze V3. This aligns with the principles established in the Master Architecture Overview.

---

## 1. Horizontal Workspace Isolation & Inheritance

To strictly isolate COEM (Customer OEM) projects while maintaining a universal core, radarAnalyze V3 uses a localized workspace directory structure and an explicit inheritance mechanism driven by configuration files.

### 1.1 Directory Structure

Workspaces are completely self-contained within `.workspaces/`. Each project gets a dedicated folder that stores its DBCs, requirement YAMLs, local overrides, and configurations.

```text
.workspaces/
├── base_core/
│   ├── config.yaml               # Core configuration, default DBC/Req mappings
│   ├── requirements/
│   │   └── default_adas.yaml     # Baseline logic
│   └── code/
│       └── core_algo/            # Base algorithm structure
└── gen6_gwm_b26/
    ├── config.yaml               # OEM-specific configuration
    ├── dbcs/
    │   ├── GWM_RearCorner_Pri_V3.0.dbc
    │   └── Private_CAN_V1.3.dbc
    ├── requirements/
    │   ├── gwm_activation.yaml   # OEM-specific overrides or new rules
    │   └── gwm_fcta.yaml
    └── memory/
        └── lancedb/              # Project-scoped LanceDB vector tables
```

### 1.2 Configuration Resolution (`config.yaml`)

The `gen6_gwm_b26` workspace configuration dynamically inherits and overrides components from the core framework.

**`.workspaces/gen6_gwm_b26/config.yaml`:**
```yaml
workspace_id: "gen6_gwm_b26"
inherits_from: "base_core"

resources:
  # DBC resolution merges or overrides base mappings
  dbcs:
    - "dbcs/GWM_RearCorner_Pri_V3.0.dbc"
    - "dbcs/Private_CAN_V1.3.dbc"
  
  # Requirements resolution prioritizes local YAMLs over base_core
  requirements:
    - "requirements/gwm_activation.yaml"
    - "requirements/gwm_fcta.yaml"
```

**Resolution Logic:** 
When the system initializes, a Workspace Manager merges the configurations. If a specific signal alias or logic requirement exists in the `gen6_gwm_b26` files, it completely overrides the `base_core` equivalent. This guarantees zero cross-contamination of proprietary logic between OEM projects.

---

## 2. Requirements YAML Schema (The Ground Truth)

For the AI Triage Loop to mathematically deduce failure points, system requirements cannot be plain text—they must be strictly typed schemas acting as the undeniable Ground Truth.

### 2.1 Pydantic Validation

```python
from pydantic import BaseModel, Field
from typing import List, Optional, Union

class Condition(BaseModel):
    signal_alias: str = Field(..., description="The unified canonical signal name.")
    operator: str = Field(..., description="Logical operator: '>', '<', '==', '>=', '<='")
    value: Union[float, int, str, bool] = Field(..., description="Threshold value.")
    duration_ms: Optional[int] = Field(None, description="Time the condition must be held.")

class RequirementSchema(BaseModel):
    req_id: str
    feature: str
    description: str
    preconditions: List[Condition]
    activation_conditions: List[Condition]
    expected_output_signal: str
```

### 2.2 YAML Example: Activation Speed Limit

This structured format enables the Data Explorer (DuckDB) to automatically convert requirements into SQL queries.

**`requirements/gwm_activation.yaml`:**
```yaml
- req_id: "REQ-GWM-ACT-001"
  feature: "BSM_Activation"
  description: "Blind Spot Monitoring shall only activate when ego vehicle speed is between 30 kph and 150 kph."
  preconditions:
    - signal_alias: "EGO_GEAR"
      operator: "=="
      value: "DRIVE"
  activation_conditions:
    - signal_alias: "EGO_SPEED_KPH"
      operator: ">="
      value: 30
    - signal_alias: "EGO_SPEED_KPH"
      operator: "<="
      value: 150
  expected_output_signal: "BSM_SYSTEM_STATE"
```

---

## 3. Full-Link Triage Agent Loop (LangGraph)

The Full-Link Agent orchestrates the root-cause analysis by routing through the "Req -> Code -> Data" triad. LangGraph manages this state machine, providing deterministic execution, cyclical reasoning, and fault recovery.

### 3.1 The `AgentState` Dictionary

The state object tracks the diagnosis lifecycle and passes evidence between nodes.

```python
from typing import TypedDict, List, Dict, Any

class AgentState(TypedDict):
    issue_description: str           # Original engineer query/issue
    active_requirements: List[Dict]  # Parsed Pydantic Requirements (Req)
    code_nodes: List[Dict]           # Ast Nodes from CodeGraph/KùzuDB (Code)
    data_anomalies: List[Dict]       # DuckDB Query Results (Data)
    triage_conclusion: str           # Final synthesized root cause
    next_step: str                   # Router control state
```

### 3.2 Triage State Machine Flow

The LangGraph consists of the following exact nodes and edges:

1. **`ReadReq` Node:** 
   * **Action:** Uses LanceDB to semantically match the `issue_description` to the structured YAML Requirements in the current workspace.
   * **Update State:** Populates `active_requirements`.
2. **`CodeGraphQuery` Node:** 
   * **Action:** Queries KùzuDB (The Bones) using signals extracted from `active_requirements`. Identifies the C/C++ files, functions, and specific variables responsible for calculating `expected_output_signal`.
   * **Update State:** Populates `code_nodes` with function paths and AST references.
3. **`DataDuckDBQuery` Node:**
   * **Action:** Translates the `Condition` schemas and `code_nodes` variable states into DuckDB SQL queries over the loaded MF4/Bag data. Probes for the exact timestamp where the data violates the requirements.
   * **Update State:** Populates `data_anomalies` with specific frames and signal traces.
4. **`TriageConclusion` Node:**
   * **Action:** The LLM synthesizes the `active_requirements`, `code_nodes`, and `data_anomalies` into a deterministic conclusion (e.g., "BSM failed to activate at t=12.4s because EGO_SPEED_KPH was 29.8, violating REQ-GWM-ACT-001 line 14 in `bsm_core.cpp`").
   * **Update State:** Sets `triage_conclusion`.

**LangGraph Routing:**
```text
[START] -> ReadReq -> CodeGraphQuery -> DataDuckDBQuery -> TriageConclusion -> [END]
                          ^                     |
                          |___(If missing var)__|
```
*Note: If DuckDB finds an intermediary signal anomaly, it can loop back to `CodeGraphQuery` to trace further up the AST graph.*

---

## 4. Memory Integration (LanceDB)

Once the `TriageConclusion` node completes, the system does not simply discard the insights. The diagnostic result is vectorized to improve future triage loops.

### 4.1 Local Vectorization Strategy
1. **Payload Generation:** The system combines the `issue_description` (symptom) and the `triage_conclusion` (root cause) into a highly dense text payload.
2. **Embedding Generation:** Uses a locally hosted embedding model (e.g., via ONNX or a lightweight local transformer) to map the payload into high-dimensional vector space.
3. **Insertion:** The vector, alongside metadata (Req IDs touched, Code Nodes visited), is saved exclusively to the project's local memory tier: `.workspaces/gen6_gwm_b26/memory/lancedb/triage_history.lance`.

### 4.2 Retrieval Utilization
In future sessions, when an engineer inputs a new `issue_description`:
* The **`ReadReq`** node performs a similarity search on `triage_history.lance`.
* If a similar symptom is found with a high confidence score (>0.85), the loop instantly pulls the historical `code_nodes` and `active_requirements` into the context budget, allowing the agent to bypass initial discovery phases and immediately test the known failure vectors in the Data Explorer (DuckDB).
