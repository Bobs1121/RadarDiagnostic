# Master Architecture Overview: radarAnalyze V3

## 1. System Vision & Context

The **radarAnalyze V3** system is purpose-built as an advanced **"AI Triage" tool** for Advanced Driver Assistance Systems (ADAS) engineers. Its primary mission is to dramatically accelerate the diagnosis and root-cause analysis of vehicle issues captured in standard data logging formats (Bag, BLF, MF4).

By bridging the gap between raw vehicle logs, system requirements, and complex ADAS codebases, radarAnalyze V3 empowers engineers to move from a reported anomaly to a verified code-level diagnosis with unprecedented speed and accuracy. It is designed to operate securely and autonomously in highly regulated engineering environments.

## 2. The Matrix Architecture

The system's structural integrity is maintained through a highly modular **Matrix Design**, ensuring clean separation of concerns, scalability, and strict data governance.

### Horizontal Axis: Domain & Workspace Isolation
The horizontal layer manages domain knowledge and ensures isolation between different projects and customers.
* **Core Foundation:** The baseline data processing, AI orchestration, and universal ADAS logic.
* **COEM Project Inheritance:** Customer Original Equipment Manufacturer (COEM) projects inherit from the Core. This enables strict **Workspace Isolation**, ensuring that specific OEM configurations, proprietary signals, and bespoke logic remain entirely independent and secure.

### Vertical Axis: Standalone Operational Modules
The vertical layer provides four distinct, standalone toolsets for the engineering workflow:
1. **Data Explorer:** A high-performance module for querying, probing, and visualizing massive, time-series vehicle data logs with zero latency.
2. **Code Assistant:** A deep codebase analysis module that understands structural dependencies and semantic intent within the ADAS source code.
3. **Full-Link Agent:** The orchestrator. An autonomous agent workflow that seamlessly correlates data anomalies, code logic, and system requirements to deduce failure modes.
4. **Profiler:** An integrated performance monitoring system tracking execution metrics and latency across the entire triage pipeline.

## 3. The "Bones & Flesh" Knowledge Engine

A central tenet of radarAnalyze V3 is the total rejection of LLM-hallucinated architectural relationships. The system relies on a rigorous, two-tiered knowledge representation strategy: **"CodeGraph as Bones + LLI Wiki as Flesh."**

* **The Bones (CodeGraph):** The deterministic structural truth of the system. Powered by robust Abstract Syntax Tree (AST) parsing, the CodeGraph is a local property graph that maps out function calls, state transitions, and variable scopes with mathematical certainty.
* **The Flesh (LLI Wiki):** The semantic context. Large Language Models process the codebase to generate rich, semantic Markdown documentation. This "Flesh" wraps the CodeGraph, providing human-readable design intent, summaries, and context-aware Retrieval-Augmented Generation (RAG) capabilities.

## 4. The AI Triage Loop (Req -> Code -> Data)

The triage process is governed by a cyclical, LangGraph-driven autonomous loop that mathematically deduces root causes by traversing three domains:

1. **Requirements (Req):** The loop begins by ingesting formalized system requirements. It establishes the baseline expectation—*"What is the system supposed to do in this scenario?"*
2. **Codebase (Code):** Utilizing the "Bones & Flesh" engine, the agent cross-references the requirements against the implemented logic. It isolates the specific functions, state machines, and variables responsible for the expected behavior.
3. **Data Logs (Data):** Finally, the agent probes the raw vehicle data streams (Bag/BLF/MF4). It compares the actual logged values against the expected states derived from the Code and Requirements to pinpoint the exact moment and location of the failure.

## 5. The Immutable Tech Stack Blueprint

radarAnalyze V3 is strictly constrained to be a **zero-backend, fully offline, and Windows-friendly** application. Every component of the tech stack is selected to operate entirely on the engineer's local machine, ensuring absolute data privacy and maximum performance.

* **Data Layer:** **DuckDB + Apache Arrow** 
  * Delivers blistering fast, zero-copy querying and aggregation of heavy time-series vehicle logs.
* **Knowledge Graph:** **KùzuDB**
  * An embedded, high-performance property graph database used to store and query the deterministic AST CodeGraph.
* **Semantic Memory:** **LanceDB**
  * A local vector database providing ultra-fast similarity search for RAG over the semantic LLI Wiki markdown files.
* **Schema & Configuration:** **Pydantic + YAML**
  * Enforces strict type validation and requirement structuring, ensuring the AI operates within rigidly defined parameters.
* **AI Orchestration:** **LangGraph**
  * Powers the resilient, stateful, and cyclical agent loops required for the complex Triage workflow.
