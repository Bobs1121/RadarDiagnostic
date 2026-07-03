# radarAnalyze V3 Requirements Solution Design

> **Document**: V3_REQUIREMENTS_DESIGN.md
> **Related**: V3_ARCHITECTURE_DESIGN.md, PRD_v3_agentic_evolution.md
> **Date**: 2026-07-02

## Introduction

This document breaks down the user stories and acceptance criteria for the V3 evolution of `radarAnalyze`. Based on the "Agentic" paradigm shift and the "Matrix Architecture" design, we decompose the system into a dynamic Agent Loop, four vertically independent sub-modules, and a horizontally isolated workspace structure. The goal is to provide actionable requirements for the development of the REPL CLI, stateless core APIs, and Human-in-the-Loop (HITL) capabilities.

---

## 1. The Agent Loop (Tool-Augmented Framework)

The transition from a rigid 15-step linear pipeline to a dynamic, LLM-driven Agentic Loop (Observation -> Thought -> Action).

### User Stories
* **US1.1 [Dynamic Orchestration]**: As a user, I want the system to understand my natural language query and dynamically select only the necessary tools, so I don't have to wait for a full diagnostic pipeline when I only need a specific task done (e.g., plotting a single signal).
* **US1.2 [Human-in-the-Loop]**: As a user, I want the CLI to pause and ask me clarifying questions (via a REPL interface) when it faces ambiguity (e.g., missing DBC files, multiple matching signals), so that it doesn't fail silently or guess incorrectly.
* **US1.3 [Streaming Thought Chain]**: As a user, I want to see the Agent's thought processes and tool execution steps streamed in real-time in my terminal, so I can understand its reasoning and trust its conclusions.
* **US1.4 [Resilience]**: As a user, I want the agent to gracefully handle tool failures (e.g., a parsing error) by receiving the error, analyzing it, and either retrying with different parameters or asking for my help, rather than crashing the entire application.

### Acceptance Criteria
* [ ] **AC1.1**: The orchestrator is implemented using an Agentic framework (e.g., LangGraph, ReAct) instead of a hardcoded sequential pipeline.
* [ ] **AC1.2**: Tools are modularized and exposed to the LLM with clear schemas (e.g., `search_code`, `plot_signals`, `ask_user`).
* [ ] **AC1.3**: The `ask_user` tool is implemented, triggering a blocking input prompt in the CLI/REPL environment.
* [ ] **AC1.4**: Token context is dynamically managed (`ContextManager`), summarizing or truncating large data outputs (like CAN frames) to prevent context window overflow.
* [ ] **AC1.5**: Exceptions within tools are caught and returned as JSON/String error messages to the LLM, not raised to crash the main process.

### CLI/REPL Interaction Example
```bash
$ radar-cli
Welcome to radarAnalyze V3 REPL.
> Plot the VehSpd signal from the latest test run.

[Thought] The user wants to plot 'VehSpd'. I need to find the latest data file in the workspace and extract this signal.
[Action] Call find_latest_data_file() -> "data/run_042.mf4"
[Action] Call query_can_signal(file="data/run_042.mf4", signal="VehSpd")
[Error] Signal 'VehSpd' is ambiguous. Found 'VehSpd_0x137' and 'EgoSpd_0x200'.
[Action] Call ask_user(question="I found multiple speed signals. Which one should I plot: VehSpd_0x137 or EgoSpd_0x200?")

Agent: I found multiple speed signals. Which one should I plot: VehSpd_0x137 or EgoSpd_0x200?
> VehSpd_0x137

[Thought] User selected VehSpd_0x137. I will plot it now.
[Action] Call query_can_signal(..., signal="VehSpd_0x137")
[Action] Call render_signal_plot(...)
[Result] Plot generated successfully.

Agent: Here is the plot for VehSpd_0x137: file://workspace/plots/vehspd.html
```

---

## 2. The Four Standalone Modules

Each core capability must function as an independent Python library with its own API and focused CLI interactions, providing distinct commercial value.

### Module A: Code Assistant (The Code & Logic Assistant)
**Focus**: AST-based code graph, requirement parsing, DBC linkage (No data needed).

#### User Stories
* **US2.A.1**: As a developer, I want to query the codebase using natural language to understand function dependencies and trigger conditions without needing to run tests.
* **US2.A.2**: As a developer, I want the system to parse requirements (PDF/MD) and map them to specific code blocks and DBC signals.

#### Acceptance Criteria
* [ ] **AC2.A.1**: Exposes a standalone Python API for parsing C/C++ into an AST graph.
* [ ] **AC2.A.2**: Generates traceability links from requirements to code variables to DBC signals.
* [ ] **AC2.A.3**: Can be invoked directly via CLI without providing any data files (`.mf4`, `.bag`).

#### CLI/REPL Example
```bash
> radar-cli -m code "Find the function definition for the RCTB trigger. What are its dependent signals in the DBC?"
[Thought] Using CodeTools to extract AST dependencies for RCTB...
Agent: The RCTB trigger is defined in `src/rctb_logic.c`. It depends on the variable `ego_speed`, which maps to the DBC signal `VehSpd_0x137`.
```

### Module B: Data Explorer (The Data Matrix Explorer)
**Focus**: Heterogeneous data ingestion, timeline alignment, signal extraction, TPE anomaly detection (No code needed).

#### User Stories
* **US2.B.1**: As a data analyst, I want to throw an unknown MF4/Bag file at the system and have it automatically extract requested signals and plot them.
* **US2.B.2**: As a tester, I want the system to automatically find data anomalies (e.g., spikes > 10Hz) using the Temporal Pattern Engine (TPE) without needing to configure a full project.

#### Acceptance Criteria
* [ ] **AC2.B.1**: Independently parses and timeline-aligns ROS Bag, CAN BLF, and MF4 files.
* [ ] **AC2.B.2**: TPE engine functions as a standalone utility for finding anomalies based on natural language or programmatic rules.
* [ ] **AC2.B.3**: Generates interactive HTML plots directly from raw data queries.

#### CLI/REPL Example
```bash
> radar-cli -m data "Load unknown_test.mf4. Find any signals that fluctuate above 10Hz and plot them."
[Thought] Loading data using DataTools. Applying TPE with a high-frequency filter...
Agent: Found 2 signals with >10Hz fluctuations: `SteeringAngle` and `YawRate`. HTML plot generated at: ./plots/hf_signals.html
```

### Module C: Full-Link Diagnostic Agent
**Focus**: The "Complete" mode tracing from Bug -> Data -> Code.

#### User Stories
* **US2.C.1**: As a system engineer, I want to provide a bug report, data file, and codebase, and have the system find the root cause by cross-referencing all three domains.
* **US2.C.2**: As an architect, I want the system to build an Ontology (Traceability Graph) connecting requirements, AST nodes, and physical CAN data.

#### Acceptance Criteria
* [ ] **AC2.C.1**: Combines Module A and Module B using the intermediate representation (Ontology).
* [ ] **AC2.C.2**: Automatically validates constraints found in code (AST) against the time-series data (FrameStore).
* [ ] **AC2.C.3**: Outputs a comprehensive diagnostic HTML report pinpointing the exact layer where the failure occurred.

#### CLI/REPL Example
```bash
> radar-cli -m diagnose "Investigate why AEB didn't trigger in case_001.mf4. Bug report says target was visible."
[Thought] Building full traceability graph. Link 1: AEB trigger conditions in Code. Link 2: Mapping variables to DBC. Link 3: Checking data for those signals at the time of target visibility...
Agent: The failure is in the Data layer. Code requires `VehSpd > 10`, but in the data, `VehSpd` dropped to 0 due to a sensor fault at t=4.2s.
```

### Module D: Performance Profiler
**Focus**: End-to-end latency, execution hotspots, CPU load.

#### User Stories
* **US2.D.1**: As a performance engineer, I want to calculate the end-to-end delay from when an object appears in a ROS Bag to when the CAN warning is emitted in the BLF.
* **US2.D.2**: As a developer, I want to identify execution hotspots (e.g., long loops) causing performance degradation.

#### Acceptance Criteria
* [ ] **AC2.D.1**: Accurately calculates time deltas across different data modalities (Bag vs. BLF).
* [ ] **AC2.D.2**: Analyzes code structures or trace logs to infer performance bottlenecks.

#### CLI/REPL Example
```bash
> radar-cli -m profile "What is the end-to-end latency between the object appearing in the bag file and the warning signal in the CAN bus?"
Agent: The average end-to-end latency is 145ms. Max latency observed was 210ms at t=12.5s.
```

---

## 3. Workspace Isolation

Implementing a multi-tenant, locally isolated environment to ensure the core engine remains stateless and configuration is highly localized.

### User Stories
* **US3.1 [Project Context]**: As a developer switching between multiple vehicle platforms, I want project-specific configurations, DBC files, and historical memory to be confined to a local directory, ensuring no cross-contamination between projects.
* **US3.2 [Stateless Engine]**: As a system administrator, I want the `radarAnalyze` engine to be stateless, mounting workspace configurations dynamically at runtime.

### Acceptance Criteria
* [ ] **AC3.1**: The system reads context strictly from `.workspace/<project_name>/` or a local `.radar_workspace` directory at the execution root.
* [ ] **AC3.2**: DBC matrices, requirement documents, and memory/history are managed per-workspace.
* [ ] **AC3.3**: The core application avoids using global environment variables for project-specific settings.
* [ ] **AC3.4**: CLI provides commands to initialize and manage workspaces.

### CLI/REPL Interaction Example
```bash
# Initialize a new workspace
> radar-cli workspace init --name GWM_B26
Workspace 'GWM_B26' created at .workspace/GWM_B26/

# Switch context to an existing workspace
> radar-cli workspace switch GWM_B26
Active workspace set to GWM_B26. Loading DBCs and project memory...

# Run a query within the context of the active workspace
> radar-cli "Find the AEB trigger logic."
[Thought] Searching AST inside GWM_B26 workspace...
```

---

## Summary of Next Steps
1. **Refactor entry points**: Decouple `cli.py` to support REPL and modular flags (`-m code`, `-m data`).
2. **Implement Workspace Loader**: Build the logic to mount `.workspace/` dynamically.
3. **Migrate Orchestrator**: Replace the linear 15-step pipeline with an Agentic tool-calling loop.
4. **Expose APIs**: Ensure CodeAssistant and DataExplorer have clean, stateless Python APIs for future DAP/VSCode integration.