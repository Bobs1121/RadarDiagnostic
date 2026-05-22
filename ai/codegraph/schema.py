# -*- coding: utf-8 -*-
"""
CodeGraph SQLite Schema.

Versioned — bump SCHEMA_VERSION when tables change.
"""
from __future__ import annotations

SCHEMA_VERSION = 1

INIT_SQL = """
-- 版本管理
CREATE TABLE IF NOT EXISTS schema_version (
    version    INTEGER PRIMARY KEY DEFAULT 1,
    applied_at TEXT DEFAULT (datetime('now'))
);

-- 文件 hash (增量构建用)
CREATE TABLE IF NOT EXISTS file_hashes (
    file_path   TEXT PRIMARY KEY,    -- 相对 source_root 的路径 (正斜杠)
    hash        TEXT NOT NULL,       -- SHA-256 前 16 位
    line_count  INTEGER,
    analyzed_at TEXT DEFAULT (datetime('now'))
);

-- 节点 (7 种类型)
CREATE TABLE IF NOT EXISTS nodes (
    id           TEXT PRIMARY KEY,   -- <TYPE>:<name>, e.g. FUNCTION:FctaFctbUpdateStatus
    type         TEXT NOT NULL,      -- FILE/FUNCTION/VARIABLE/SIGNAL/STATE/MODULE/CALIB_PARAM

    -- 通用
    name         TEXT NOT NULL,
    display_name TEXT,

    -- FILE
    file_path    TEXT,               -- 相对 source_root 的完整路径 (正斜杠)

    -- FUNCTION
    file_id      TEXT REFERENCES nodes(id),
    start_line   INTEGER,
    end_line     INTEGER,
    return_type  TEXT,
    params       TEXT,
    is_static    INTEGER DEFAULT 0,

    -- VARIABLE
    scope        TEXT,               -- global/static_global/local/struct_field
    data_type    TEXT,
    defined_in   TEXT,               -- 文件路径
    line         INTEGER,
    struct_owner TEXT,

    -- SIGNAL
    direction    TEXT,               -- Rx/Tx
    can_name     TEXT,
    can_id       TEXT,
    rte_read_fn  TEXT,
    rte_write_fn TEXT,

    -- STATE
    state_id     INTEGER,
    state_name   TEXT,
    func         TEXT,

    -- MODULE
    keywords     TEXT,               -- JSON array
    side         TEXT,               -- front/rear

    -- CALIB_PARAM
    value        REAL,
    unit         TEXT,
    category     TEXT,               -- vehicle_config/function_thresholds/roi_derived
    formula      TEXT,
    computed_value REAL,

    source_hash  TEXT,
    created_at   TEXT DEFAULT (datetime('now')),
    updated_at   TEXT DEFAULT (datetime('now'))
);

-- 边 (12 种类型)
CREATE TABLE IF NOT EXISTS edges (
    id             TEXT PRIMARY KEY,  -- <source>-><target>:<type>:<line>
    source         TEXT NOT NULL REFERENCES nodes(id),
    target         TEXT NOT NULL REFERENCES nodes(id),
    type           TEXT NOT NULL,     -- CALLS/READS_VAR/WRITES_VAR/READS_SIGNAL/WRITES_SIGNAL/
                                      -- ACCESSES_FIELD/BELONGS_TO/DEFINED_IN/FILE_INcludes/
                                      -- TRANSITION/PARAM_FOR
    line           INTEGER,
    column         INTEGER,
    condition      TEXT,              -- if/while 条件字符串
    pattern        TEXT,              -- 行为模式: HoldRelease/HoldEntry/Accumulate/Hysteresis/Debounce/EdgeTrigger
    macro_name     TEXT,              -- 宏间接调用时的宏名
    struct_name    TEXT,              -- struct 访问时的结构体名
    field_name     TEXT,              -- struct field 名
    rte_call       TEXT,              -- Rte_Read/Write 完整调用字符串
    binding_method TEXT,              -- BELONGS_TO 的绑定方式: keyword/call_graph/manual
    source_hash    TEXT,
    created_at     TEXT DEFAULT (datetime('now'))
);

-- LLM 语义层 (code_knowledge 的新存法)
CREATE TABLE IF NOT EXISTS node_semantics (
    node_id      TEXT PRIMARY KEY REFERENCES nodes(id),
    focus        TEXT NOT NULL,       -- alarm_logic/calculation_chain/output_chain/state_machine
    semantic_json TEXT NOT NULL,
    source_hash  TEXT,
    learned_at   TEXT DEFAULT (datetime('now')),
    UNIQUE(node_id, focus)
);

-- 构建日志
CREATE TABLE IF NOT EXISTS build_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    build_time      TEXT DEFAULT (datetime('now')),
    build_type      TEXT,             -- incremental/full
    files_scanned   INTEGER DEFAULT 0,
    files_changed   INTEGER DEFAULT 0,
    nodes_added     INTEGER DEFAULT 0,
    edges_added     INTEGER DEFAULT 0,
    nodes_removed   INTEGER DEFAULT 0,
    edges_removed   INTEGER DEFAULT 0,
    duration_sec    REAL,
    summary         TEXT
);

-- 索引
CREATE INDEX IF NOT EXISTS idx_edges_source       ON edges(source);
CREATE INDEX IF NOT EXISTS idx_edges_target       ON edges(target);
CREATE INDEX IF NOT EXISTS idx_edges_type         ON edges(type);
CREATE INDEX IF NOT EXISTS idx_edges_source_type  ON edges(source, type);
CREATE INDEX IF NOT EXISTS idx_edges_target_type  ON edges(target, type);
CREATE INDEX IF NOT EXISTS idx_edges_3col         ON edges(source, target, type);
CREATE INDEX IF NOT EXISTS idx_nodes_type         ON nodes(type);
CREATE INDEX IF NOT EXISTS idx_nodes_name         ON nodes(name);
CREATE INDEX IF NOT EXISTS idx_nodes_file         ON nodes(file_id);
CREATE INDEX IF NOT EXISTS idx_nodes_type_name    ON nodes(type, name);
CREATE INDEX IF NOT EXISTS idx_semantics_focus    ON node_semantics(focus);
"""
