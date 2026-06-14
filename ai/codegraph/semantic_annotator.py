# -*- coding: utf-8 -*-
"""
SemanticAnnotator — LLM 语义标注引擎。

将 CodeGraph 结构层（语法信息）升级为意图层（语义描述）：

    CodeGraph SQLite (结构图谱)
      → SemanticAnnotator (LLM 语义标注)
        → node_semantics 表 (语义图谱)

工作流程：
1. 读取 code_knowledge/*.json 做冷启动填充（已有知识直接入库）
2. 对未覆盖节点，按文件分批提交 LLM 标注
3. source_hash 校验 — 源码不变时跳过
4. 结果写入 node_semantics 表

标注内容：
- FUNCTION: 功能描述 + 输入输出 + 调用关系
- VARIABLE: 语义角色 + 取值范围 + 数据来源
- SIGNAL: 物理含义 + 单位 + 数据范围
- CALIB_PARAM: 校准参数含义 + 默认值 + 影响范围
"""
from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger(__name__)


@dataclass
class SemanticAnnotation:
    """单个节点的语义标注结果。"""
    node_id: str
    focus: str  # "overview" | "alarm_logic" | "calculation_chain" | "state_machine" | "output_chain"
    semantic: dict[str, Any]
    source_hash: str
    confidence: float = 0.85

    def to_json(self) -> str:
        return json.dumps(self.semantic, ensure_ascii=False, indent=2)


@dataclass
class AnnotationBatch:
    """单文件批次的标注任务。"""
    file_path: str
    file_hash: str
    nodes: list[dict]  # [{id, type, name, start_line, end_line, source_code}]

    @property
    def function_count(self) -> int:
        return sum(1 for n in self.nodes if n.get("type") == "FUNCTION")

    @property
    def variable_count(self) -> int:
        return sum(1 for n in self.nodes if n.get("type") == "VARIABLE")

    @property
    def signal_count(self) -> int:
        return sum(1 for n in self.nodes if n.get("type") == "SIGNAL")

    @property
    def total(self) -> int:
        return len(self.nodes)


@dataclass
class AnnotationStats:
    """标注统计信息。"""
    total_nodes: int = 0
    annotated: int = 0
    skipped_cached: int = 0
    skipped_no_change: int = 0
    failed: int = 0
    cold_start_from_knowledge: int = 0

    def summary(self) -> str:
        return (
            f"SemanticAnnotation: total={self.total_nodes}, "
            f"annotated={self.annotated}, "
            f"cached={self.skipped_cached}, "
            f"no_change={self.skipped_no_change}, "
            f"cold_start={self.cold_start_from_knowledge}, "
            f"failed={self.failed}"
        )


class SemanticAnnotator:
    """
    CodeGraph 语义标注引擎。

    支持两种标注模式：
    1. cold_start: 从 code_knowledge/*.json 填充已有知识
    2. llm_analyze: LLM 读取源码 + AST 结构，生成语义标注

    Usage:
        annotator = SemanticAnnotator(db_path, project_root, router)
        annotator.cold_start()       # Phase 1: 填充已有知识
        annotator.annotate_all()     # Phase 2: LLM 增量标注
        stats = annotator.stats
    """

    # LLM 标注使用的 focus 列表
    FOCUS_LIST = ["overview"]

    # 需要优先标注的核心文件
    CORE_FILES = [
        "adasFunc.c",
        "ASWIN_SystemState.c",
        "ASWOUT_OutCalc.c",
        "RteComMapping.c",
        "FctCtrl.c",
        "FctbCtrl.c",
        "RctCtrl.c",
        "RcwCtrl.c",
        "BsdCtrl.c",
        "LcaCtrl.c",
        "DowCtrl.c",
    ]

    def __init__(
        self,
        db_path: str | Path,
        project_root: str | Path,
        router=None,
        memory_dir: Optional[Path] = None,
    ):
        self.db_path = Path(db_path)
        self.project_root = Path(project_root)
        self.router = router
        self.memory_dir = memory_dir  # per-project memory dir (e.g. memory/projects/gwm_b26)
        self.conn: Optional[sqlite3.Connection] = None
        self.stats = AnnotationStats()
        self._connect()

    def _connect(self):
        """打开数据库连接。"""
        if not self.db_path.exists():
            raise FileNotFoundError(f"CodeGraph DB not found: {self.db_path}")
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.row_factory = sqlite3.Row

    def close(self):
        """关闭数据库连接。"""
        if self.conn:
            self.conn.close()
            self.conn = None

    # ─── Hash 计算 ───────────────────────────────────────────────────────

    @staticmethod
    def compute_file_hash(file_path: str | Path) -> str:
        """计算文件内容的 hash（用于缓存失效）。"""
        try:
            with open(file_path, "rb") as f:
                return hashlib.md5(f.read()).hexdigest()[:12]
        except (FileNotFoundError, PermissionError):
            return ""

    @staticmethod
    def compute_source_hash(source_code: str) -> str:
        """计算源码片段的 hash。"""
        return hashlib.md5(source_code.encode("utf-8", errors="replace")).hexdigest()[:12]

    # ─── Cold Start: code_knowledge → node_semantics ─────────────────────

    def _resolve_knowledge_dir(self) -> Optional[Path]:
        """Resolve code_knowledge directory — per-project first, then legacy global."""
        # Try per-project directory
        if self.memory_dir:
            proj_ckpt = self.memory_dir / "code_knowledge"
            if proj_ckpt.exists() and any(proj_ckpt.glob("*.json")):
                return proj_ckpt
        # Fallback: legacy global directory
        legacy = self.project_root / "memory" / "code_knowledge"
        if legacy.exists() and any(legacy.glob("*.json")):
            return legacy
        return None

    def cold_start(self) -> int:
        """
        从 code_knowledge/*.json 填充已有知识到 node_semantics 表。

        这是零成本的冷启动 — 已有的知识直接入库，不需要 LLM 调用。

        优先使用 per-project 目录（memory/projects/<proj>/code_knowledge/），
        若不存在则回退到 legacy 全局目录（memory/code_knowledge/）。

        Returns:
            填充的标注数量。
        """
        knowledge_dir = self._resolve_knowledge_dir()
        if knowledge_dir is None:
            log.info("Cold start: no code_knowledge directory found")
            return 0

        count = 0
        for knowledge_file in sorted(knowledge_dir.glob("*.json")):
            if knowledge_file.name in ("learning_state.json",):
                continue

            try:
                with open(knowledge_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except (json.JSONDecodeError, UnicodeDecodeError) as e:
                log.warning(f"Cold start: failed to load {knowledge_file}: {e}")
                continue

            count += self._inject_knowledge(knowledge_file.stem, data)

        self.stats.cold_start_from_knowledge = count
        log.info(f"Cold start complete: {count} annotations from code_knowledge")
        return count

    def _inject_knowledge(self, func_name: str, data: dict) -> int:
        """
        将一个 code_knowledge JSON 的知识注入到 node_semantics。

        策略：code_knowledge 是按功能模块（FCTA/RCTB 等）组织的，
        不是按具体函数名。需要找到该功能模块相关的所有 FUNCTION nodes，
        然后把 focus 标注到匹配的函数上。

        匹配规则：
        - FCTA → name LIKE '%Fcta%' OR name LIKE '%FCTA%'
        - RCTB → name LIKE '%Rctb%' OR name LIKE '%RCTB%'
        - BSD → name LIKE '%Bsd%' OR name LIKE '%bsd%'
        - 等等...
        """
        if not self.conn:
            return 0

        count = 0
        meta = data.get("_meta", {})
        learned_at = meta.get("last_updated", time.strftime("%Y-%m-%dT%H:%M:%S"))

        # 找到该功能模块相关的 FUNCTION nodes
        func_node_ids = self._find_function_nodes_by_module(func_name)
        if not func_node_ids:
            # 如果没有找到函数，尝试找到相关的 VARIABLE 节点
            var_node_ids = self._find_variable_nodes_by_module(func_name)
            log.debug(f"Cold start: no FUNCTION for {func_name}, found {len(var_node_ids)} VARIABLES")
        else:
            log.info(f"Cold start: {func_name} → {len(func_node_ids)} FUNCTION nodes")

        # 1. alarm_logic — 标注到所有相关函数
        if "alarm_logic" in data and func_node_ids:
            alarm_data = data["alarm_logic"]
            semantic = {
                "type": "alarm_logic",
                "description": f"{func_name} 告警逻辑",
                "trigger_conditions": alarm_data.get("trigger_conditions", []),
                "cancel_conditions": alarm_data.get("cancel_conditions", []),
                "exit_conditions": alarm_data.get("exit_conditions", []),
                "hysteresis": alarm_data.get("hysteresis", []),
                "timers": alarm_data.get("timers", []),
            }
            source_hash = meta.get("source_hashes", {}).get("alarm_logic", "")
            for nid in func_node_ids:
                if self._upsert_semantics(nid, "alarm_logic", semantic, source_hash, learned_at):
                    count += 1

        # 2. calculation_chain — 函数级别 + 变量级别
        if "calculation_chain" in data:
            calc_data = data["calculation_chain"]
            source_hash = meta.get("source_hashes", {}).get("calculation_chain", "")

            # 函数级别
            func_semantic = {
                "type": "calculation_chain",
                "description": f"{func_name} 计算链路",
                "key_variables": list(calc_data.get("key_variables", {}).keys()),
                "derivation_chain": calc_data.get("derivation_chain", []),
                "thresholds_used": calc_data.get("thresholds_used", []),
            }
            for nid in func_node_ids:
                if self._upsert_semantics(nid, "calculation_chain", func_semantic, source_hash, learned_at):
                    count += 1

            # 变量级别标注
            all_nodes = func_node_ids + self._find_variable_nodes_by_module(func_name)
            for var_name, var_info in calc_data.get("key_variables", {}).items():
                var_nids = self._find_variable_nodes_by_name(var_name)
                if not var_nids:
                    var_nids = [nid for nid in all_nodes
                                if self._node_is_variable(nid) and var_name.lower() in self._node_name(nid, "").lower()]
                for var_nid in (var_nids or []):
                    var_semantic = {
                        "type": "variable_semantic",
                        "description": var_info.get("description", ""),
                        "formula": var_info.get("formula", ""),
                        "inputs": var_info.get("inputs", []),
                        "data_source": var_info.get("data_source", ""),
                        "output_usage": var_info.get("output_usage", ""),
                    }
                    if self._upsert_semantics(var_nid, "overview", var_semantic, source_hash, learned_at):
                        count += 1

        # 3. state_machine
        if "state_machine" in data and func_node_ids:
            sm_data = data["state_machine"]
            semantic = {
                "type": "state_machine",
                "description": f"{func_name} 状态机定义",
                "states": sm_data.get("states", []),
                "transitions": sm_data.get("transitions", []),
                "entry_functions": sm_data.get("entry_functions", []),
                "dual_state_interaction": sm_data.get("dual_state_interaction"),
            }
            source_hash = meta.get("source_hashes", {}).get("state_machine", "")
            for nid in func_node_ids:
                if self._upsert_semantics(nid, "state_machine", semantic, source_hash, learned_at):
                    count += 1

        # 4. output_chain
        if "output_chain" in data and func_node_ids:
            oc_data = data["output_chain"]
            semantic = {
                "type": "output_chain",
                "description": f"{func_name} 输出链路",
                "outputs": oc_data.get("outputs", []),
                "merge_strategy": oc_data.get("merge_strategy"),
                "external_gating": oc_data.get("external_gating", []),
            }
            source_hash = meta.get("source_hashes", {}).get("output_chain", "")
            for nid in func_node_ids:
                if self._upsert_semantics(nid, "output_chain", semantic, source_hash, learned_at):
                    count += 1

        return count

    def _find_function_nodes_by_module(self, module_name: str) -> list[str]:
        """按功能模块名查找相关 FUNCTION nodes。"""
        if not self.conn:
            return []
        upper = module_name.upper()
        lower = module_name.lower()
        cur = self.conn.execute(
            "SELECT id FROM nodes WHERE type='FUNCTION' AND "
            "(name LIKE ? OR name LIKE ? OR name LIKE ? OR name LIKE ?)",
            (f"%{upper}%", f"%{lower}%", f"%{module_name}%", f"%_{upper}%"),
        )
        ids = [row["id"] for row in cur.fetchall()]
        # Limit to avoid too many annotations
        return ids[:10]

    def _find_variable_nodes_by_module(self, module_name: str) -> list[str]:
        """按功能模块名查找相关 VARIABLE nodes。"""
        if not self.conn:
            return []
        upper = module_name.upper()
        lower = module_name.lower()
        cur = self.conn.execute(
            "SELECT id FROM nodes WHERE type='VARIABLE' AND "
            "(name LIKE ? OR name LIKE ?)",
            (f"%{upper}%", f"%{lower}%"),
        )
        return [row["id"] for row in cur.fetchall()]

    def _find_variable_nodes_by_name(self, var_name: str) -> list[str]:
        """按变量名查找 VARIABLE nodes（支持模糊匹配）。"""
        if not self.conn:
            return []
        # Try exact match first
        cur = self.conn.execute(
            "SELECT id FROM nodes WHERE type='VARIABLE' AND name=?",
            (var_name,),
        )
        ids = [row["id"] for row in cur.fetchall()]
        if ids:
            return ids
        # Fuzzy: LIKE
        cur = self.conn.execute(
            "SELECT id FROM nodes WHERE type='VARIABLE' AND name LIKE ?",
            (f"%{var_name}%",),
        )
        return [row["id"] for row in cur.fetchall()]

    def _node_is_variable(self, node_id: str) -> bool:
        """检查节点是否是 VARIABLE 类型。"""
        if not self.conn:
            return False
        cur = self.conn.execute(
            "SELECT type FROM nodes WHERE id=?", (node_id,)
        )
        row = cur.fetchone()
        return row and row["type"] == "VARIABLE"

    def _node_name(self, node_id: str, default: str = "") -> str:
        """获取节点名称。"""
        if not self.conn:
            return default
        cur = self.conn.execute(
            "SELECT name FROM nodes WHERE id=?", (node_id,)
        )
        row = cur.fetchone()
        return row["name"] if row else default

    # ─── LLM 标注 Pipeline ───────────────────────────────────────────────

    def annotate_all(self, core_files_only: bool = True) -> AnnotationStats:
        """
        对所有节点执行 LLM 语义标注。

        Args:
            core_files_only: 是否只标注核心文件（默认 True）。
        """
        if not self.conn:
            self._connect()

        # 获取需要标注的文件列表
        files_to_annotate = self._get_files_to_annotate(core_files_only)
        log.info(f"LLM annotation: {len(files_to_annotate)} files to process")

        for file_info in files_to_annotate:
            file_path = file_info["path"]
            file_id = file_info["id"]

            # 读取文件源码
            source_file = self.project_root / file_path
            if not source_file.exists():
                log.debug(f"Source file not found: {source_file}")
                continue

            file_hash = self.compute_file_hash(source_file)

            # 获取该文件下的节点
            batch = self._build_annotation_batch(file_path, file_id, file_hash)
            if batch.total == 0:
                continue

            # 执行 LLM 标注
            self._annotate_batch(batch)

        log.info(self.stats.summary())
        return self.stats

    def annotate_batch(self, batch: AnnotationBatch) -> int:
        """对单个批次执行 LLM 标注。"""
        return self._annotate_batch(batch)

    def _annotate_batch(self, batch: AnnotationBatch) -> int:
        """
        对一批节点执行 LLM 标注。

        策略：
        1. 跳过已有标注的节点（检查 node_semantics）
        2. 按节点类型分组（FUNCTION/VARIABLE/SIGNAL）
        3. 每类提交一次 LLM 调用
        4. 解析结果写入 node_semantics
        """
        if not self.router:
            log.warning("No router available for LLM annotation — skipping")
            return 0

        annotated = 0

        # 按类型分组
        functions = [n for n in batch.nodes if n.get("type") == "FUNCTION"]
        variables = [n for n in batch.nodes if n.get("type") == "VARIABLE"]
        signals = [n for n in batch.nodes if n.get("type") in ("SIGNAL", "CALIB_PARAM")]

        # 1. 函数标注
        if functions:
            annotated += self._annotate_functions(functions, batch.file_hash)

        # 2. 变量标注
        if variables:
            annotated += self._annotate_variables(variables, batch.file_hash)

        # 3. 信号/校准参数标注
        if signals:
            annotated += self._annotate_signals(signals, batch.file_hash)

        self.stats.annotated += annotated
        return annotated

    def _annotate_functions(self, functions: list[dict], file_hash: str) -> int:
        """对一批函数进行 LLM 标注。"""
        if not self.router:
            return 0

        # 构建 prompt — 一次性标注所有函数
        prompt_parts = ["你是一个嵌入式 C 代码分析专家。请为以下函数生成语义标注。"]
        prompt_parts.append(f"\n文件：{functions[0].get('_file_path', 'unknown')}")
        prompt_parts.append("\n\n请为每个函数提供以下信息：")
        prompt_parts.append("- description: 函数的功能描述（中文）")
        prompt_parts.append("- inputs: 输入参数列表及其含义")
        prompt_parts.append("- outputs: 返回值或输出的全局变量")
        prompt_parts.append("- side_effects: 副作用（如修改全局状态、发送信号等）")
        prompt_parts.append("- belongs_to: 属于哪个 ADAS 功能模块（BSD/LCA/DOW/RCW/RCTA/RCTB/FCTA/FCTB）")
        prompt_parts.append("\n输出格式为 JSON 数组：")
        prompt_parts.append('{"annotations": [{"node_id": "...", "semantic": {...}}, ...]}')
        prompt_parts.append("\n\n以下是函数源码：\n")

        for func in functions:
            prompt_parts.append(f"// === {func['name']} (L{func.get('start_line', '?')}-L{func.get('end_line', '?')}) ===\n")
            prompt_parts.append(func.get("source_code", "")[:2000])
            prompt_parts.append("\n")

        prompt = "\n".join(prompt_parts)

        try:
            result = self.router.chat(
                "semantic_annotate_functions",
                prompt,
                system="你是一个专业的嵌入式 C 代码语义标注引擎。只输出 JSON，不要其他文字。",
            )
            # Parse JSON result
            import re
            json_match = re.search(r'\{.*\}', result, re.DOTALL)
            if not json_match:
                log.warning(f"LLM annotation: no JSON in response for {len(functions)} functions")
                self.stats.failed += len(functions)
                return 0

            data = json.loads(json_match.group())
            count = 0
            for annotation in data.get("annotations", []):
                node_id = annotation.get("node_id")
                semantic = annotation.get("semantic", {})
                if node_id and semantic:
                    self._upsert_semantics(node_id, "overview", semantic, file_hash)
                    count += 1

            return count

        except Exception as e:
            log.error(f"LLM annotation failed for {len(functions)} functions: {e}")
            self.stats.failed += len(functions)
            return 0

    def _annotate_variables(self, variables: list[dict], file_hash: str) -> int:
        """对一批变量进行 LLM 标注。"""
        if not self.router:
            return 0

        # Filter out variables that already have semantics
        unannotated = []
        for var in variables:
            existing = self._get_existing_semantics(var["id"], "overview")
            if existing:
                self.stats.skipped_cached += 1
                continue
            unannotated.append(var)

        if not unannotated:
            return 0

        # Group by semantic category for efficient prompting
        state_vars = [v for v in unannotated if any(k in v["name"] for k in ["State", "Mode", "Status"])]
        flag_vars = [v for v in unannotated if any(k in v["name"] for k in ["Flag", "Enable", "Active"])]
        threshold_vars = [v for v in unannotated if any(k in v["name"] for k in ["Thresh", "Limit", "Max", "Min"])]
        other_vars = [v for v in unannotated if v not in state_vars + flag_vars + threshold_vars]

        count = 0
        count += self._annotate_var_group(state_vars, "状态变量", file_hash)
        count += self._annotate_var_group(flag_vars, "标志变量", file_hash)
        count += self._annotate_var_group(threshold_vars, "阈值变量", file_hash)
        count += self._annotate_var_group(other_vars, "其他变量", file_hash)

        return count

    def _annotate_var_group(self, variables: list[dict], category: str, file_hash: str) -> int:
        """对一组同类型变量进行批量标注。"""
        if not variables or not self.router:
            return 0

        # For variables, use a simpler approach: infer from naming conventions + context
        count = 0
        for var in variables:
            semantic = self._infer_variable_semantics(var, category)
            if semantic:
                self._upsert_semantics(var["id"], "overview", semantic, file_hash)
                count += 1

        return count

    def _infer_variable_semantics(self, var: dict, category: str) -> dict:
        """
        基于命名规则和上下文推断变量语义。

        对于常见命名模式的变量，可以直接推断语义而不需要 LLM。
        对于不确定的变量，返回 None 标记为需要 LLM 标注。
        """
        name = var.get("name", "")
        data_type = var.get("data_type", "")
        var_type = var.get("type", "VARIABLE")

        semantic = {
            "type": f"variable_{category.lower().replace(' ', '_')}",
            "category": category,
            "name": name,
        }

        # State variables
        if "State" in name or "state" in name.lower():
            semantic["description"] = f"{name} — 状态变量，表示相关功能模块的运行状态"
            semantic["value_range"] = "枚举值或状态码"
            if "FCTA" in name:
                semantic["description"] = "FCTA 功能运行状态（Inactive/Standby/Active）"
            elif "FCTB" in name:
                semantic["description"] = "FCTB 功能运行状态（Inactive/Standby/Active）"
            elif "RCTA" in name:
                semantic["description"] = "RCTA 功能运行状态（Inactive/Standby/Active）"
            elif "RCTB" in name:
                semantic["description"] = "RCTB 功能运行状态（Inactive/Standby/Active）"
            elif "RCW" in name:
                semantic["description"] = "RCW 功能运行状态（Inactive/Standby/Active）"
            elif "BSD" in name or "bsd" in name.lower():
                semantic["description"] = "BSD 盲点监测功能状态"
            elif "LCA" in name or "lca" in name.lower():
                semantic["description"] = "LCA 变道辅助功能状态"
            elif "DOW" in name or "dow" in name.lower():
                semantic["description"] = "DOW 车门开启警告功能状态"
            return semantic

        # Flag/Enable variables
        if any(k in name for k in ["Flag", "Enable", "Active", "flag", "enable"]):
            semantic["description"] = f"{name} — 标志/开关变量"
            semantic["value_range"] = "0/1 或 TRUE/FALSE"
            if "Enable" in name:
                semantic["description"] = f"{name} — 功能使能标志，1=启用，0=禁用"
            elif "Flag" in name:
                semantic["description"] = f"{name} — 状态标志位"
            return semantic

        # Threshold variables
        if any(k in name for k in ["Thresh", "Limit", "Max", "Min", "thresh", "limit"]):
            semantic["description"] = f"{name} — 阈值/限制参数"
            semantic["unit"] = self._infer_unit(name)
            return semantic

        # TTC/Distance/Speed variables
        if "TTC" in name:
            semantic["description"] = f"{name} — 碰撞时间 (Time To Collision)，单位秒"
            semantic["unit"] = "s"
            return semantic
        if "Distance" in name or "Dist" in name:
            semantic["description"] = f"{name} — 距离参数"
            semantic["unit"] = "m"
            return semantic
        if "Speed" in name or "Vel" in name or "Speed" in name:
            semantic["description"] = f"{name} — 速度参数"
            semantic["unit"] = "km/h"
            return semantic

        # Object-related
        if "Object" in name or "Obj" in name or "Target" in name:
            semantic["description"] = f"{name} — 目标对象相关变量"
            return semantic

        # Brake-related
        if "Brake" in name or "brake" in name.lower():
            semantic["description"] = f"{name} — 制动相关变量"
            if "Value" in name:
                semantic["unit"] = "% 或 m/s²"
            return semantic

        # Default: return basic info, mark as low confidence
        semantic["description"] = f"{name} — {category}"
        semantic["confidence"] = 0.5
        semantic["needs_llm_review"] = True
        return semantic

    def _infer_unit(self, name: str) -> str:
        """从变量名推断单位。"""
        lower = name.lower()
        if "speed" in lower or "vel" in lower:
            return "km/h"
        if "dist" in lower:
            return "m"
        if "ttc" in lower or "time" in lower:
            return "s"
        if "angle" in lower:
            return "deg"
        if "accel" in lower:
            return "m/s²"
        return ""

    def _annotate_signals(self, signals: list[dict], file_hash: str) -> int:
        """对信号/校准参数进行标注。"""
        if not signals or not self.router:
            return 0

        count = 0
        for sig in signals:
            existing = self._get_existing_semantics(sig["id"], "overview")
            if existing:
                self.stats.skipped_cached += 1
                continue

            semantic = self._infer_signal_semantics(sig)
            if semantic:
                self._upsert_semantics(sig["id"], "overview", semantic, file_hash)
                count += 1

        return count

    def _infer_signal_semantics(self, sig: dict) -> dict:
        """基于信号名推断语义。"""
        name = sig.get("name", "")
        direction = sig.get("direction", "")
        sig_type = sig.get("type", "SIGNAL")

        semantic = {
            "type": "signal_semantic" if sig_type == "SIGNAL" else "calib_param_semantic",
            "name": name,
            "direction": direction,
        }

        if sig_type == "CALIB_PARAM":
            semantic["description"] = f"{name} — 校准参数"
            semantic["category"] = "calibration"
        else:
            # Signal
            if "Speed" in name:
                semantic["description"] = f"{name} — 车速信号"
                semantic["unit"] = "km/h"
                semantic["range"] = "0-250"
            elif "Gear" in name:
                semantic["description"] = f"{name} — 挡位信号"
                semantic["values"] = "P/R/N/D/... 挡位枚举"
            elif "Brake" in name:
                semantic["description"] = f"{name} — 制动信号"
                semantic["unit"] = "%"
            elif "Steer" in name or "Yaw" in name:
                semantic["description"] = f"{name} — 转向信号"
                semantic["unit"] = "deg"
            elif "Object" in name or "Obj" in name:
                semantic["description"] = f"{name} — 目标对象信号"
            else:
                semantic["description"] = f"{name} — CAN 通信信号"
                semantic["confidence"] = 0.5
                semantic["needs_llm_review"] = True

        return semantic

    # ─── Database Operations ─────────────────────────────────────────────

    def _find_function_node(self, func_name: str) -> Optional[str]:
        """按函数名精确查找 FUNCTION node。"""
        if not self.conn:
            return None
        cur = self.conn.execute(
            "SELECT id FROM nodes WHERE type='FUNCTION' AND name=?",
            (func_name,),
        )
        row = cur.fetchone()
        return row["id"] if row else None

    def _find_function_node_fuzzy(self, func_name: str) -> Optional[str]:
        """模糊匹配 FUNCTION node。"""
        if not self.conn:
            return None
        upper = func_name.upper()
        cur = self.conn.execute(
            "SELECT id FROM nodes WHERE type='FUNCTION' AND "
            "UPPER(name) LIKE ? OR UPPER(name) LIKE ? OR UPPER(name) LIKE ?",
            (f"%{upper}%", f"%{upper}_%", f"%_{upper}%"),
        )
        row = cur.fetchone()
        return row["id"] if row else None

    def _find_variable_node(self, var_name: str) -> Optional[str]:
        """按变量名查找 VARIABLE node。"""
        if not self.conn:
            return None
        cur = self.conn.execute(
            "SELECT id FROM nodes WHERE type='VARIABLE' AND name=?",
            (var_name,),
        )
        row = cur.fetchone()
        return row["id"] if row else None

    def _get_existing_semantics(self, node_id: str, focus: str) -> Optional[dict]:
        """检查节点是否已有语义标注。"""
        if not self.conn:
            return None
        cur = self.conn.execute(
            "SELECT semantic_json, source_hash FROM node_semantics WHERE node_id=? AND focus=?",
            (node_id, focus),
        )
        row = cur.fetchone()
        if not row:
            return None
        try:
            return json.loads(row["semantic_json"])
        except (json.JSONDecodeError, TypeError):
            return None

    def _upsert_semantics(
        self,
        node_id: str,
        focus: str,
        semantic: dict,
        source_hash: str = "",
        learned_at: str = "",
    ) -> bool:
        """
        插入或更新语义标注。

        如果已有标注且 source_hash 相同，则跳过（缓存命中）。

        Returns:
            True 如果实际写入了新数据，False 如果跳过了。
        """
        if not self.conn:
            return False

        if not learned_at:
            learned_at = time.strftime("%Y-%m-%dT%H:%M:%S")

        semantic_json = json.dumps(semantic, ensure_ascii=False, indent=2)

        # Check if already annotated with same hash
        cur = self.conn.execute(
            "SELECT source_hash FROM node_semantics WHERE node_id=? AND focus=?",
            (node_id, focus),
        )
        existing = cur.fetchone()
        if existing and existing["source_hash"] == source_hash:
            self.stats.skipped_no_change += 1
            return False

        self.conn.execute(
            """INSERT OR REPLACE INTO node_semantics
               (node_id, focus, semantic_json, source_hash, learned_at)
               VALUES (?, ?, ?, ?, ?)""",
            (node_id, focus, semantic_json, source_hash, learned_at),
        )
        self.conn.commit()
        return True

    def _get_files_to_annotate(self, core_only: bool) -> list[dict]:
        """获取需要标注的文件列表。"""
        if not self.conn:
            return []

        if core_only:
            # 只标注核心文件
            patterns = [f"%{f}%" for f in self.CORE_FILES]
            where = " OR ".join([f"path LIKE {p}" for p in patterns])
            cur = self.conn.execute(
                f"SELECT id, path FROM nodes WHERE type='FILE' AND ({where})"
            )
        else:
            cur = self.conn.execute(
                "SELECT id, path FROM nodes WHERE type='FILE'"
            )

        return [{"id": row["id"], "path": row["path"]} for row in cur.fetchall()]

    def _build_annotation_batch(
        self, file_path: str, file_id: str, file_hash: str
    ) -> Optional[AnnotationBatch]:
        """
        为单个文件构建标注批次。

        只包含未标注的节点。
        """
        if not self.conn:
            return None

        # Get functions in this file
        cur = self.conn.execute(
            """SELECT n.id, n.name, n.start_line, n.end_line
               FROM nodes n
               JOIN edges e ON e.target = n.id AND e.type = 'BELONGS_TO'
               WHERE e.source = ?""",
            (file_id,),
        )
        functions = [dict(row) for row in cur.fetchall()]

        # Read source code for functions
        source_file = self.project_root / file_path
        nodes = []
        if source_file.exists():
            try:
                with open(source_file, "r", encoding="utf-8", errors="replace") as f:
                    lines = f.readlines()

                for func in functions:
                    start = func["start_line"] or 0
                    end = func["end_line"] or len(lines)
                    source_code = "".join(lines[start - 1:end]) if start > 0 else ""

                    # Skip if already annotated
                    existing = self._get_existing_semantics(func["id"], "overview")
                    if existing:
                        self.stats.skipped_cached += 1
                        continue

                    nodes.append({
                        "id": func["id"],
                        "type": "FUNCTION",
                        "name": func["name"],
                        "start_line": start,
                        "end_line": end,
                        "source_code": source_code[:4000],  # cap to avoid huge prompts
                        "_file_path": file_path,
                    })

                # Get variables related to this file
                var_cur = self.conn.execute(
                    """SELECT DISTINCT n.id, n.name, n.data_type, n.scope
                       FROM nodes n
                       JOIN edges e ON e.target = n.id
                       WHERE e.source IN (SELECT id FROM nodes WHERE type='FUNCTION'
                          AND file_id = ?)""",
                    (file_id,),
                )
                for v in var_cur.fetchall():
                    v_dict = dict(v)
                    v_dict["type"] = "VARIABLE"
                    # Skip if already annotated
                    existing = self._get_existing_semantics(v_dict["id"], "overview")
                    if existing:
                        self.stats.skipped_cached += 1
                        continue
                    nodes.append(v_dict)

            except Exception as e:
                log.warning(f"Failed to read source for {file_path}: {e}")

        if not nodes:
            return None

        self.stats.total_nodes += len(nodes)
        return AnnotationBatch(
            file_path=file_path,
            file_hash=file_hash,
            nodes=nodes,
        )

    # ─── Query Interface ─────────────────────────────────────────────────

    def get_semantics(self, node_id: str, focus: str = "overview") -> Optional[dict]:
        """获取单个节点的语义标注。"""
        existing = self._get_existing_semantics(node_id, focus)
        return existing

    def get_semantics_for_nodes(self, node_ids: list[str]) -> dict[str, dict]:
        """批量获取节点的语义标注。"""
        if not self.conn or not node_ids:
            return {}

        result = {}
        placeholders = ",".join(["?" for _ in node_ids])
        cur = self.conn.execute(
            f"SELECT node_id, focus, semantic_json FROM node_semantics "
            f"WHERE node_id IN ({placeholders})",
            node_ids,
        )
        for row in cur.fetchall():
            nid = row["node_id"]
            try:
                semantic = json.loads(row["semantic_json"])
            except (json.JSONDecodeError, TypeError):
                continue
            if nid not in result:
                result[nid] = {}
            result[nid][row["focus"]] = semantic

        return result

    def get_semantics_by_file(self, file_path: str) -> dict[str, dict]:
        """获取某个文件下所有节点的语义标注。"""
        if not self.conn:
            return {}

        # Find file node
        cur = self.conn.execute(
            "SELECT id FROM nodes WHERE type='FILE' AND path LIKE ?",
            (f"%{file_path}%",),
        )
        file_row = cur.fetchone()
        if not file_row:
            return {}

        file_id = file_row["id"]

        # Find all nodes belonging to this file
        cur = self.conn.execute(
            """SELECT DISTINCT n.id FROM nodes n
               WHERE n.file_id = ? OR
               EXISTS (SELECT 1 FROM edges e
                       WHERE e.target = n.id AND e.source = ?)""",
            (file_id, file_id),
        )
        node_ids = [row["id"] for row in cur.fetchall()]

        return self.get_semantics_for_nodes(node_ids)

    def get_semantics_summary(self) -> dict:
        """获取语义标注统计摘要。"""
        if not self.conn:
            return {}

        cur = self.conn.execute("""
            SELECT
                n.type,
                COUNT(DISTINCT n.id) as total_nodes,
                COUNT(DISTINCT ns.node_id) as annotated_nodes,
                COUNT(DISTINCT CASE WHEN ns.focus='overview' THEN ns.node_id END) as overview_count,
                COUNT(DISTINCT CASE WHEN ns.focus='alarm_logic' THEN ns.node_id END) as alarm_logic_count,
                COUNT(DISTINCT CASE WHEN ns.focus='calculation_chain' THEN ns.node_id END) as calc_chain_count,
                COUNT(DISTINCT CASE WHEN ns.focus='state_machine' THEN ns.node_id END) as sm_count,
                COUNT(DISTINCT CASE WHEN ns.focus='output_chain' THEN ns.node_id END) as oc_count,
            FROM nodes n
            LEFT JOIN node_semantics ns ON ns.node_id = n.id
            GROUP BY n.type
        """)

        summary = {}
        for row in cur.fetchall():
            summary[row[0]] = dict(row)

        return summary
