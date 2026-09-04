# -*- coding: utf-8 -*-
"""
预置 BSD 条件集 — 用于集成测试和 smoke test。

覆盖以下类别：
- fct_suppression          : BSD 抑制条件
- object_selector           : 目标筛选条件
- warning_zone              : 警告区域
- necessity                 : BSD 生成必要性条件
- vx_suppression            : 相对速度抑制条件

每个条件都有一个简单的、可求值的 formula_str。
"""
from __future__ import annotations

from .models import ConditionDef

# ── BSD 抑制条件 ──────────────────────────────────────────────────────────

BFD_SUPPRESSION_CONDITIONS: list[dict] = [
    {
        "step": 1,
        "name": "Ego Speed Check",
        "category": "fct_suppression",
        "formula_str": "vx_self >= 2.78",
        "signal_names": ["vx_self"],
        "pad_params": {"MIN_BSDDIST_VX": 2.78},
        "pad_sources": ["bsddbstrgconst.h"],
        "code_files": ["bsddbstrg.c"],
        "expected_outcome": "pass",
        "description": "本车速度必须大于等于最小 BSD 距离速度阈值 2.78 m/s (10 km/h)。",
        "condition_id": "BSD-1.1",
    },
    {
        "step": 2,
        "name": "No Active BSD Warning",
        "category": "fct_suppression",
        "formula_str": "bsd_warning == 0",
        "signal_names": ["bsd_warning"],
        "pad_params": {"_": 0},
        "pad_sources": ["bsddbstrg.h"],
        "code_files": ["bsddbstrg.c"],
        "expected_outcome": "fail",
        "description": "BSD 警告未激活时，不抑制 BSD 生成。",
        "condition_id": "BSD-1.2",
    },
]

# ── 目标选择条件 ──────────────────────────────────────────────────────────

OBJECT_SELECTOR_CONDITIONS: list[dict] = [
    {
        "step": 3,
        "name": "Lateral Distance Threshold",
        "category": "object_selector",
        "formula_str": "abs(dist_y) < 4.12",
        "signal_names": ["dist_y"],
        "pad_params": {"MAX_DIST_Y_BSD": 4.12},
        "pad_sources": ["bsddbstrgconst.h"],
        "code_files": ["bbsdobjsel.c", "bsdobjectprocess.c"],
        "expected_outcome": "pass",
        "description": "目标横向距离必须小于最大 BSD 距离 4.12 米。",
        "condition_id": "BSD-2.1.1",
    },
    {
        "step": 4,
        "name": "Object Moving Check",
        "category": "object_selector",
        "formula_str": "abs(dy) < 1.8 and abs(dx) < 90",
        "signal_names": ["dy", "dx"],
        "pad_params": {"MAX_BSD_OBJ_DY": 1.8, "MAX_BSD_OBJ_DX": 90},
        "pad_sources": ["bsddbstrgconst.h"],
        "code_files": ["bsdobjectprocess.c"],
        "expected_outcome": "pass",
        "description": "目标必须处于相对运动状态（横向偏移<1.8m, 纵向偏移<90m）。",
        "condition_id": "BSD-2.1.2",
    },
    {
        "step": 5,
        "name": "Existence Probability Filter",
        "category": "object_selector",
        "formula_str": "existProb >= 0.6",
        "signal_names": ["existProb"],
        "pad_params": {"EXISTS_PROB_BSD": 0.6},
        "pad_sources": ["bsddbstrgconst.h"],
        "code_files": ["bsdobjectprocess.c"],
        "expected_outcome": "pass",
        "description": "目标存在概率必须大于等于 0.6。",
        "condition_id": "BSD-2.1.3",
    },
    {
        "step": 6,
        "name": "Object Width Filter",
        "category": "object_selector",
        "formula_str": "obj_width >= 0.5 and obj_width <= 12.0",
        "signal_names": ["obj_width"],
        "pad_params": {"MIN_OBJ_WIDTH": 0.5, "MAX_OBJ_WIDTH": 12.0},
        "pad_sources": ["bsddbstrgconst.h"],
        "code_files": ["bsdobjectprocess.c"],
        "expected_outcome": "pass",
        "description": "目标宽度必须在物理合理范围内 (0.5m ~ 12.0m)。",
        "condition_id": "BSD-2.1.4",
    },
]

# ── 警告区域条件 ──────────────────────────────────────────────────────────

WARNING_ZONE_CONDITIONS: list[dict] = [
    {
        "step": 7,
        "name": "BSD Warning Zone - Ttc",
        "category": "warning_zone",
        "formula_str": "ttc < 0 or ttc > 6.0",
        "signal_names": ["ttc"],
        "pad_params": {"MAX_TTC_BSD": 6.0},
        "pad_sources": ["bsddbstrgconst.h"],
        "code_files": ["bsddbstrg.c"],
        "expected_outcome": "fail",
        "description": "碰撞时间超过阈值或为负值时，目标不在 BSD 警告区域内。",
        "condition_id": "BSD-2.2.1",
    },
    {
        "step": 8,
        "name": "BSD Warning Zone - Dist X",
        "category": "warning_zone",
        "formula_str": "abs(dist_x) < 150",
        "signal_names": ["dist_x"],
        "pad_params": {"MAX_DIST_X_BSD": 150},
        "pad_sources": ["bsddbstrgconst.h"],
        "code_files": ["bsddbstrg.c"],
        "expected_outcome": "pass",
        "description": "目标纵向距离必须小于最大 BSD 纵向距离 150 米。",
        "condition_id": "BSD-2.2.2",
    },
    {
        "step": 9,
        "name": "Relative Speed Check",
        "category": "warning_zone",
        "formula_str": "vx >= -4.0",
        "signal_names": ["vx"],
        "pad_params": {"MIN_VX_BSD": -4.0},
        "pad_sources": ["bsddbstrgconst.h"],
        "code_files": ["bsddbstrg.c"],
        "expected_outcome": "pass",
        "description": "相对速度 vx 必须大于等于 -4.0 m/s（目标不能比本车快太多）。",
        "condition_id": "BSD-2.2.3",
    },
]

# ── BSD 生成必要性条件 ────────────────────────────────────────────────────

NECESSITY_CONDITIONS: list[dict] = [
    {
        "step": 10,
        "name": "Deceleration Required",
        "category": "necessity",
        "formula_str": "decel_req > 0.3",
        "signal_names": ["decel_req"],
        "pad_params": {"MIN_DECEL_BSD": 0.3},
        "pad_sources": ["bsddbstrgconst.h"],
        "code_files": ["bsddist.c", "bsdobjectprocess.c"],
        "expected_outcome": "pass",
        "description": "需要减速度大于 0.3 m/s^2 时才生成 BSD 警告。",
        "condition_id": "BSD-3.1",
    },
    {
        "step": 11,
        "name": "TTC Valid Flag",
        "category": "necessity",
        "formula_str": "ttc_valid == 1",
        "signal_names": ["ttc_valid"],
        "pad_params": {"_": 1},
        "pad_sources": ["bsddbstrg.h"],
        "code_files": ["bsddist.c"],
        "expected_outcome": "pass",
        "description": "TTC 必须为有效值。",
        "condition_id": "BSD-3.2",
    },
]

# ── VX 抑制条件 ───────────────────────────────────────────────────────────

VX_SUPPRESSION_CONDITIONS: list[dict] = [
    {
        "step": 12,
        "name": "Overtaking Check",
        "category": "vx_suppression",
        "formula_str": "vx <= -4.0",
        "signal_names": ["vx"],
        "pad_params": {"OVERTAKING_VX": -4.0},
        "pad_sources": ["bsddbstrgconst.h"],
        "code_files": ["bsdobjectprocess.c"],
        "expected_outcome": "fail",
        "description": "相对速度小于等于 -4 m/s 时为目标正在超越本车，抑制 BSD 警告。",
        "condition_id": "BSD-4.1",
    },
    {
        "step": 13,
        "name": "Same Direction Speed Diff",
        "category": "vx_suppression",
        "formula_str": "vx > -2.0",
        "signal_names": ["vx"],
        "pad_params": {"SAME_DIR_VX": -2.0},
        "pad_sources": ["bsddbstrgconst.h"],
        "code_files": ["bsdobjectprocess.c"],
        "expected_outcome": "fail",
        "description": "同向行驶时相对速度差小于 2 m/s 不触发 BSD。",
        "condition_id": "BSD-4.2",
    },
]

# ── 完整条件集 ────────────────────────────────────────────────────────────

ALL_BSD_CONDITIONS: list[dict] = (
    BFD_SUPPRESSION_CONDITIONS
    + OBJECT_SELECTOR_CONDITIONS
    + WARNING_ZONE_CONDITIONS
    + NECESSITY_CONDITIONS
    + VX_SUPPRESSION_CONDITIONS
)


def get_bsd_condition_defs() -> list[ConditionDef]:
    """返回完整的 BSD ConditionDef 列表。"""
    return [ConditionDef.from_dict(c) for c in ALL_BSD_CONDITIONS]


def get_bsd_condition_json() -> str:
    """返回完整的 BSD 条件 JSON 字符串。"""
    import json
    return json.dumps(
        {"conditions": ALL_BSD_CONDITIONS},
        ensure_ascii=False,
    )
