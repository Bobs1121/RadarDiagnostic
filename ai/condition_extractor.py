# -*- coding: utf-8 -*-
"""
Condition Extractor: uses AI to extract structured activation condition
trees from source code, then caches the result for reuse.

Output: a JSON dict describing the state machine transitions,
target filtering rules, and detection enable conditions for a given
ADAS function. Cached to source_docs/{FUNC}_conditions.json.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from .model_router import ModelRouter
from .utils import parse_json_from_llm, extract_relevant_sections, build_keyword_variants

_DEFAULT_DOMAIN_SOURCES = {
    "system_state": [
        "coem\\GWM_B26\\components\\AswIf\\ASW_IN\\ASWIN_SystemState.c",
        "coem\\GWM_B26\\components\\AswIf\\ASW_IN\\ASWIN_SystemState.h",
    ],
    "algorithm": [
        "coem\\GWM_B26\\components\\AswPerception\\func\\adasFunc.c",
        "coem\\GWM_B26\\components\\AswPerception\\func\\adasFunc.h",
        "adas\\symmetry\\perception\\include\\paraDefine.h",
    ],
    "signal_chain": [
        "coem\\GWM_B26\\components\\AswIf\\ASW_IN\\RteComMapping.c",
    ],
}

_EXTRACT_PROMPT = """你是嵌入式 ADAS 代码分析专家。请从以下源码中精确提取 **{func_name}** 功能的所有激活条件。

## 源码

{source_code}

---

请严格输出以下 JSON 结构（不要输出任何其他文字）:

```json
{{
  "function": "{func_name}",
  "system_state": {{
    "state_values": {{
      "0": "None", "1": "Init", "2": "Standby", "3": "Active",
      "4": "Off", "5": "Failure", "6": "Passive"
    }},
    "transitions": [
      {{
        "from": "起始状态(数字或*)",
        "to": "目标状态(数字)",
        "conditions": [
          {{"condition": "条件描述", "variable": "变量名", "threshold": "阈值或要求", "source": "文件名:行号(近似)"}}
        ]
      }}
    ]
  }},
  "target_filter": {{
    "skip_function": "FctaSkipFlg 或类似函数名",
    "conditions": [
      {{"condition": "条件描述", "variable": "变量名", "threshold": "阈值", "note": "进入/维持/其他"}}
    ]
  }},
  "detect_enable": {{
    "flag": "bFctaDetectFlg 或类似",
    "conditions": [
      {{"condition": "条件描述", "variable": "变量名", "threshold": "阈值"}}
    ]
  }},
  "ego_speed_ranges": {{
    "active": {{"low": "变量名=值", "high": "变量名=值", "unit": "km/h"}},
    "deactive": {{"low": "变量名=值", "high": "变量名=值", "unit": "km/h"}},
    "detect": {{"low": "变量名=值", "high": "变量名=值", "unit": "km/h"}}
  }},
  "target_speed_ranges": {{
    "warning_enter": {{"low": "变量名=值", "high": "变量名=值", "unit": "km/h"}},
    "warning_exit":  {{"low": "变量名=值", "high": "变量名=值", "unit": "km/h"}}
  }},
  "external_suppression": [
    {{
      "source_system": "AEB/ESP/ACC/TCS/驾驶员操作/其他外部系统",
      "condition": "抑制条件描述",
      "variable": "单个C变量名(如 AdasStM.DrvDoorSts)，禁止填宏名或函数名",
      "can_signal": "RteComMapping.c中找到的精确CAN信号名，禁止编造",
      "suppression_trigger": "导致抑制发生的具体值/条件(如: ==0, !=0, >80, TRUE, FALSE)",
      "normal_value": "不触发抑制时的正常值(如: !=0, ==0, <80)",
      "effect": "抑制/禁用/中断/降级",
      "source": "文件名:行号(近似)"
    }}
  ],
  "other_conditions": [
    {{"category": "类别", "condition": "描述", "variable": "变量名", "threshold": "阈值"}}
  ]
}}
```

要求:
1. 所有阈值必须给出具体数值（从代码中的 float 初始化值读取）
2. 变量名必须与代码中完全一致
3. 如果代码中有 System_Kmh2ms 转换，注明原始单位是 km/h
4. 分清"进入报警"和"维持报警/退出报警"的不同阈值
5. 只提取与 {func_name} 直接相关的条件，不要混入其他功能
6. **特别重要**: 仔细查找代码中读取**外部系统/驾驶员/整车状态**信号
   （AEB/AEBIB/AEBBA/ESP/ACC/TCS/DTC/车门/手刹/档位/仪表开关等）
   来抑制/禁用/中断 {func_name} 功能的所有逻辑，填入 external_suppression 数组。
   不同功能的抑制源不同：
   - 前向功能（FCTA/FCTB）：常见 AEB/ACC/ESP 等纵向制动系统介入
   - 后向功能（BSD/LCA/DOW/RCW/RCTA/RCTB）：常见档位（R 档）、转向灯、
     车门状态、驻车、停车状态、DTC 故障码等
   - 通用：仪表开关关断、变型位屏蔽、DTC 故障码屏蔽
   在 RteComMapping.c 中查找这些外部信号的 CAN 信号名映射。
7. **external_suppression 的 variable 字段规则**:
   - 必须是**单个 C 变量名**(如 AdasStM.DrvDoorSts)，不得填宏名(如 DOORISCLS())或函数调用
   - 如果代码中条件是宏/函数调用(如 DOORISCLS())，必须追溯其定义，拆分为多个条目，每个条目对应一个底层变量
   - 如果条件是 OR 表达式(如 a || b)，拆分为多个条目
8. **suppression_trigger 极性规则(最重要)**:
   suppression_trigger 必须填写**导致功能退出 / 抑制动作发生 / 状态回退** 的那个值或条件。
   必须严格按照代码中 if 语句的判定条件填写，不可根据变量名猜测含义。

   **关键反直觉模式**: 变量名中含 "Active" 并不意味着 TRUE 是抑制条件！
   - 代码 `if(!bXxxActiveFlg){{ bKeepFunc=false; }}`
     含义: 当"Active"标志为 FALSE/0 时取消功能，所以:
     suppression_trigger='== FALSE', normal_value='== TRUE'
   - 代码 `if(bXxxActiveFlg == 0){{ exit; }}` → suppression_trigger='== 0', normal_value='!= 0'
   - 代码 `if(AccPedPos > 80){{ suppress; }}` → suppression_trigger='> 80', normal_value='<= 80'
   - 代码 `if(DoorSts != 0){{ suppress; }}` → suppression_trigger='!= 0', normal_value='== 0'
   - 代码 `if(gear == REVERSE){{ enable_rcw=false; }}` → suppression_trigger='== REVERSE',
     normal_value='!= REVERSE'

   **验证方法**: 填完 suppression_trigger 后，将其代入 if 语句——如果条件为真时代码执行的是
   exit/return/bKeepXxx=false/状态回退等抑制动作，则极性正确。否则请反转。"""


class ConditionExtractor:
    """Extract and cache structured activation conditions from source code."""

    def __init__(self, router: ModelRouter, project_root: Path, config: dict):
        self.router = router
        self.project_root = project_root
        from config import resolve_source_docs_dir
        self.source_root = Path(config["paths"]["source_code"])
        self.cache_dir = resolve_source_docs_dir(config, project_root)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._domain_sources = config.get("source_domains", _DEFAULT_DOMAIN_SOURCES)

    def extract(self, func_name: str, force: bool = False) -> dict:
        """
        Returns structured conditions for the given function.
        Uses cached version if available and source hasn't changed.
        After extraction, auto-fills Unknown CAN signal names via signal_mapping.
        """
        func_name = func_name.upper()
        cache_path = self.cache_dir / f"{func_name}_conditions.json"

        if not force and cache_path.exists():
            cached = self._load_cache(cache_path)
            if cached and not self._source_changed(cached, cache_path):
                return cached

        conditions = self._extract_with_ai(func_name)
        if conditions and "error" not in conditions:
            conditions = self._backfill_can_signals(conditions)
            self._save_cache(cache_path, conditions)
        return conditions

    def _backfill_can_signals(self, conditions: dict) -> dict:
        """Resolve Unknown CAN signal names in external_suppression via signal_mapping."""
        from .signal_mapper import extract_signal_mapping, resolve_internal_to_can, load_variable_chains

        sig_mapping = extract_signal_mapping(
            self.source_root,
            self.cache_dir,
        )
        chains = load_variable_chains(self.cache_dir)

        for sup in conditions.get("external_suppression", []):
            can = sup.get("can_signal", "") or ""
            if can and can.lower() not in ("unknown", "?", ""):
                continue
            var_name = sup.get("variable", "")
            if not var_name:
                continue
            resolved = resolve_internal_to_can(var_name, sig_mapping, chains)
            if resolved:
                sup["can_signal"] = resolved[0]
                sup["_can_resolved"] = True
            else:
                sup["can_signal"] = "Unknown"
                sup["_can_resolved"] = False

        return conditions

    MAX_SOURCE_CHARS = 80_000
    MAX_RETRIES = 2

    def _extract_with_ai(self, func_name: str) -> dict:
        """Use Qwen3.5 to extract conditions from source code.

        Uses CodeGraph to pinpoint relevant code sections instead of
        blind keyword matching across all files.
        """
        source_parts = []

        # Strategy 1: CodeGraph-guided extraction (precise)
        cg_source_parts = self._extract_with_codegraph(func_name)
        if cg_source_parts:
            source_parts.extend(cg_source_parts)

        # Strategy 2: Legacy keyword matching (fallback + supplement)
        if len(source_parts) < 3:
            for domain, files in self._domain_sources.items():
                for rel_path in files:
                    full_path = self.source_root / rel_path
                    if not full_path.exists():
                        continue
                    try:
                        text = full_path.read_text(encoding="utf-8", errors="replace")
                        relevant = self._extract_relevant_sections(text, func_name)
                        if relevant:
                            already_present = any(rel_path in sp for sp in source_parts)
                            if not already_present:
                                source_parts.append(f"### {rel_path} (相关段落)\n```c\n{relevant}\n```")
                    except Exception:
                        pass

        if not source_parts:
            return {"error": "源码不可用", "function": func_name}

        source_code = "\n\n".join(source_parts)
        if len(source_code) > self.MAX_SOURCE_CHARS:
            source_code = source_code[:self.MAX_SOURCE_CHARS] + "\n// ... [TRUNCATED]"

        prompt = _EXTRACT_PROMPT.format(func_name=func_name, source_code=source_code)

        for attempt in range(1, self.MAX_RETRIES + 1):
            result = self.router.complex(prompt, max_tokens=16384)
            content = result.get("content", "")

            if result.get("error"):
                print(f"  [condition_extractor] attempt {attempt}: API error: {result['error']}")
                continue

            if not content.strip():
                print(f"  [condition_extractor] attempt {attempt}: empty response (finish={result.get('finish_reason','?')})")
                continue

            try:
                start = content.index("{")
                end = content.rindex("}") + 1
                parsed = json.loads(content[start:end])
                parsed["function"] = func_name
                return parsed
            except (ValueError, json.JSONDecodeError) as e:
                print(f"  [condition_extractor] attempt {attempt}: JSON parse failed: {e}")
                if attempt < self.MAX_RETRIES:
                    continue

        return {
            "function": func_name,
            "error": "AI提取失败",
            "raw_response": content[:2000] if content else "(empty)",
        }

    @staticmethod
    def _extract_relevant_sections(text: str, func_name: str) -> str:
        """Extract code sections relevant to the given function."""
        return extract_relevant_sections(
            text, build_keyword_variants(func_name), context_lines=15, max_chunks=30,
        )

    def _extract_with_codegraph(self, func_name: str) -> list[str]:
        """Use CodeGraph to precisely locate relevant code sections.

        Returns list of markdown-formatted source code snippets.
        """
        result = []
        try:
            from .codegraph import CodeGraph
            from config import resolve_codegraph_db
            cg_path = resolve_codegraph_db(self.config, self.project_root)
            if not cg_path.exists():
                return result

            cg = CodeGraph(cg_path)

            # 1. Find functions in this module
            funcs = cg.get_functions_by_module(func_name)
            if not funcs:
                cg.close()
                return result

            # 2. For each function, read the actual source code
            seen_files = set()
            for func_info in funcs:
                # NodeInfo has file_id like "FILE:coem/.../file.c"
                file_id = getattr(func_info, 'file_id', '') or ''
                if not file_id:
                    continue
                file_rel = file_id.split(":", 1)[-1]  # strip "FILE:" prefix
                if file_rel in seen_files:
                    continue

                full_path = self.source_root / file_rel
                if not full_path.exists():
                    continue

                try:
                    text = full_path.read_text(encoding="utf-8", errors="replace")

                    # Get function start/end lines
                    func_name_attr = getattr(func_info, 'name', '')
                    func_start = getattr(func_info, 'start_line', 0) or 0
                    func_end = getattr(func_info, 'end_line', 0) or 0

                    if func_start and func_end:
                        # Extract exact function body + context
                        lines = text.split("\n")
                        ctx_start = max(0, func_start - 10)
                        ctx_end = min(len(lines), func_end + 5)
                        func_code = "\n".join(lines[ctx_start:ctx_end])
                    else:
                        # Fallback: keyword extraction
                        func_code = self._extract_relevant_sections(text, func_name_attr)

                    if func_code:
                        seen_files.add(file_rel)
                        result.append(
                            f"### {file_rel} (CodeGraph: {func_name_attr})\n"
                            f"```c\n{func_code[:5000]}\n```"
                        )
                except Exception:
                    pass

            # 3. Also include callers (upstream context)
            for func_info in funcs[:3]:  # top 3 functions only
                func_name_attr = getattr(func_info, 'name', '')
                callers = cg.find_callers(func_name_attr)
                for caller in callers[:2]:  # top 2 callers
                    caller_file_id = getattr(caller, 'file_id', '') or ''
                    if not caller_file_id or caller_file_id in seen_files:
                        continue
                    caller_file = caller_file_id.split(":", 1)[-1]

                    caller_path = self.source_root / caller_file
                    if caller_path.exists():
                        try:
                            text = caller_path.read_text(encoding="utf-8", errors="replace")
                            caller_name = getattr(caller, 'name', '?')
                            caller_code = self._extract_relevant_sections(text, caller_name)
                            if caller_code:
                                seen_files.add(caller_file)
                                result.append(
                                    f"### {caller_file} (Caller: {caller_name})\n"
                                    f"```c\n{caller_code[:3000]}\n```"
                                )
                        except Exception:
                            pass

            cg.close()
        except Exception:
            pass  # silent fallback to legacy

        return result

    @staticmethod
    def _load_cache(cache_path: Path) -> Optional[dict]:
        try:
            return json.loads(cache_path.read_text(encoding="utf-8"))
        except Exception:
            return None

    @staticmethod
    def _save_cache(cache_path: Path, data: dict):
        cache_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _source_changed(self, cached: dict, cache_path: Path) -> bool:
        """Check if any source file is newer than the cache."""
        cache_mtime = cache_path.stat().st_mtime
        for files in self._domain_sources.values():
            for rel_path in files:
                full_path = self.source_root / rel_path
                if full_path.exists():
                    if full_path.stat().st_mtime > cache_mtime:
                        return True
        return False


# ── Formatting Helper ────────────────────────────────────────────────

def format_conditions(conditions: dict) -> str:
    """Format conditions dict into a compact text table for experts."""
    if not conditions or "error" in conditions:
        return f"(条件提取失败: {conditions.get('error', '?')})"

    parts = []
    func = conditions.get("function", "?")
    parts.append(f"### {func} 激活条件")

    # Ego speed ranges
    spd = conditions.get("ego_speed_ranges", {})
    if spd:
        parts.append("\n**自车速度范围:**")
        for mode, vals in spd.items():
            if isinstance(vals, dict):
                parts.append(f"  {mode}: [{vals.get('low','?')}, {vals.get('high','?')}] {vals.get('unit','')}")

    # Target speed ranges
    tspd = conditions.get("target_speed_ranges", {})
    if tspd:
        parts.append("\n**目标速度范围:**")
        for mode, vals in tspd.items():
            if isinstance(vals, dict):
                parts.append(f"  {mode}: ({vals.get('low','?')}, {vals.get('high','?')}) {vals.get('unit','')}")

    # State transitions
    st = conditions.get("system_state", {})
    transitions = st.get("transitions", [])
    if transitions:
        parts.append("\n**状态转移条件:**")
        for tr in transitions:
            parts.append(f"  {tr.get('from','?')} → {tr.get('to','?')}:")
            for c in tr.get("conditions", []):
                parts.append(f"    - {c.get('condition','')} [{c.get('variable','')}={c.get('threshold','')}]")

    # Target filter
    tf = conditions.get("target_filter", {})
    tf_conds = tf.get("conditions", [])
    if tf_conds:
        parts.append(f"\n**目标过滤 ({tf.get('skip_function','?')}):**")
        for c in tf_conds:
            parts.append(f"  - {c.get('condition','')} [{c.get('variable','')}={c.get('threshold','')}] ({c.get('note','')})")

    # Detect enable
    de = conditions.get("detect_enable", {})
    de_conds = de.get("conditions", [])
    if de_conds:
        parts.append(f"\n**检测使能 ({de.get('flag','?')}):**")
        for c in de_conds:
            parts.append(f"  - {c.get('condition','')} [{c.get('variable','')}={c.get('threshold','')}]")

    # External suppression
    es = conditions.get("external_suppression", [])
    if es:
        parts.append("\n**★ 外部抑制条件(必查) ★:**")
        for s in es:
            src = s.get("source_system", "?")
            cond = s.get("condition", "?")
            var = s.get("variable", "?")
            can = s.get("can_signal", "")
            eff = s.get("effect", "抑制")
            thr = s.get("suppression_trigger") or s.get("threshold", "?")
            normal = s.get("normal_value", "")
            can_info = f" CAN={can}" if can else ""
            normal_info = f", 正常值={normal}" if normal else ""
            parts.append(f"  - [{src}] {cond} [{var}: 抑制当{thr}{normal_info}]{can_info} → {eff}")

    return "\n".join(parts)
