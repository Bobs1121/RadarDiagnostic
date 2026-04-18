# 优化需求规格说明书

本文档定义 radarAnalyze 项目的三项优化需求，供 AI 代理实现。

---

## 优化 2: 诊断置信度评分系统

### 目标

为每次诊断输出量化的置信度评分，帮助用户判断诊断结果的可信程度。

### 修改文件

1. `ai/expert_panel.py` - 在专家面板输出中增加置信度计算
2. `ai/orchestrator.py` - 在报告中展示置信度
3. `memory/memory_system.py` - 可选，存储历史置信度用于统计

### 详细设计

#### 2.1 置信度计算模型

```python
# ai/expert_panel.py 中新增

class ConfidenceScorer:
    """诊断置信度评分器"""
    
    def calculate(self, panel_result: dict, data_stats: dict) -> dict:
        """
        计算综合置信度评分
        
        Returns:
            {
                "overall_confidence": 0.0-1.0,
                "factors": {
                    "expert_agreement": 0.0-1.0,      # 专家一致性
                    "data_completeness": 0.0-1.0,     # 数据完整性
                    "code_evidence": 0.0-1.0,         # 代码证据强度
                    "pattern_match": 0.0-1.0          # 历史模式匹配
                },
                "confidence_level": "HIGH|MEDIUM|LOW", # 可读等级
                "uncertainty_notes": [...]            # 不确定性说明
            }
        """
        pass
```

#### 2.2 各因子计算逻辑

| 因子 | 计算方式 | 权重 |
|------|----------|------|
| **expert_agreement** | 5 位专家中同意根因的比例，矛盾点越多分数越低 | 35% |
| **data_completeness** | (实际获取的信号数 / 预期信号数) × 窗口覆盖率 | 25% |
| **code_evidence** | 是否有明确的代码行/条件作为证据 | 25% |
| **pattern_match** | 与历史相似案例的匹配度（来自 memory） | 15% |

```python
# 具体实现示例

def calc_expert_agreement(panel_result: dict) -> float:
    """专家一致性评分"""
    opinions = panel_result.get("expert_opinions", {})
    root_causes = [op.get("root_cause", "") for op in opinions.values()]
    
    # 统计相同根因的数量
    from collections import Counter
    counts = Counter(rc[:50] for rc in root_causes)  # 取前 50 字比较
    max_count = max(counts.values()) if counts else 0
    
    # 矛盾点扣分
    contradictions = len(panel_result.get("moderator_challenges", {}).get("contradictions", []))
    
    base_score = max_count / len(opinions) if opinions else 0.0
    penalty = contradictions * 0.1  # 每个矛盾扣 10%
    
    return max(0.0, base_score - penalty)


def calc_data_completeness(data_stats: dict) -> float:
    """数据完整性评分"""
    expected_signals = data_stats.get("expected_signal_count", 0)
    actual_signals = data_stats.get("actual_signal_count", 0)
    window_coverage = data_stats.get("window_coverage", 1.0)
    
    if expected_signals == 0:
        return 1.0
    
    signal_ratio = actual_signals / expected_signals
    return signal_ratio * window_coverage


def calc_code_evidence(diagnosis_text: str) -> float:
    """代码证据强度评分"""
    # 检查诊断中是否引用了具体代码
    evidence_indicators = [
        "adasFunc.c", "ASWIN_SystemState.c", "RteComMapping.c",
        "第", "行", "变量", "条件", "if ", "==", "!="
    ]
    
    score = 0.0
    for indicator in evidence_indicators:
        if indicator in diagnosis_text:
            score += 0.15
    
    return min(1.0, score)


def calc_pattern_match(memory_context: str, current_problem: str) -> float:
    """历史模式匹配评分"""
    # 检查 memory 中是否有相似案例
    if "相似历史案例" not in memory_context:
        return 0.0
    
    # 统计匹配的案例数量
    import re
    matches = re.findall(r"相似.*?->.*?根因", memory_context)
    match_count = len(matches)
    
    # 最多 3 个案例得满分
    return min(1.0, match_count / 3.0)
```

#### 2.3 综合评分

```python
def calculate_overall_confidence(factors: dict) -> tuple[float, str]:
    """
    计算综合置信度
    
    Returns:
        (score, level) - 分数和等级 (HIGH/MEDIUM/LOW)
    """
    weights = {
        "expert_agreement": 0.35,
        "data_completeness": 0.25,
        "code_evidence": 0.25,
        "pattern_match": 0.15,
    }
    
    score = sum(factors.get(k, 0.0) * v for k, v in weights.items())
    
    if score >= 0.7:
        level = "HIGH"
    elif score >= 0.4:
        level = "MEDIUM"
    else:
        level = "LOW"
    
    return round(score, 2), level
```

#### 2.4 输出格式

在 `expert_panel.py` 的 `run_panel` 返回值中增加：

```python
{
    "final_verdict": "...",
    "confidence": {
        "overall": 0.78,
        "level": "HIGH",
        "factors": {
            "expert_agreement": 0.80,
            "data_completeness": 0.75,
            "code_evidence": 0.90,
            "pattern_match": 0.50
        },
        "uncertainty_notes": [
            "抑制信号 CR_BsdSuppression 未在 BLF 中找到",
            "仅检测到 1 个相似历史案例"
        ]
    }
}
```

#### 2.5 报告展示

在 `orchestrator.py` 的 `_save_report` 中修改报告头部：

```markdown
| 置信度 | ⭐⭐⭐⭐ 0.78 (HIGH) |
| 专家一致性 | 0.80 (5 位专家中 4 位同意) |
| 数据完整性 | 0.75 (15/20 信号，窗口覆盖 100%) |
| 代码证据 | 0.90 (引用 adasFunc.c 第 234 行) |
| 历史匹配 | 0.50 (1 个相似案例) |

> ⚠️ 不确定性说明:
> - 抑制信号 CR_BsdSuppression 未在 BLF 中找到
> - 仅检测到 1 个相似历史案例
```

### 验收标准

1. 每次诊断输出包含 `confidence` 字段
2. 置信度分数在 0.0-1.0 之间
3. 报告头部清晰展示置信度等级和各项因子
4. 低置信度 (LOW) 时显示不确定性说明

---

## 优化 3: 可视化时间线生成

### 目标

生成 HTML/SVG 格式的交互式时间线图，直观展示测试窗口、状态跳变、抑制信号等时序关系。

### 修改文件

1. `ai/timeline_viz.py` - 新建文件，时间线可视化引擎
2. `ai/orchestrator.py` - 调用可视化生成，输出 HTML 文件

### 详细设计

#### 3.1 数据模型

```python
# ai/timeline_viz.py

from dataclasses import dataclass
from typing import List, Optional
from enum import Enum

class EventType(Enum):
    WINDOW_START = "window_start"
    WINDOW_END = "window_end"
    STATE_CHANGE = "state_change"
    SUPPRESSION = "suppression"
    WARNING = "warning"
    BRAKE = "brake"

@dataclass
class TimelineEvent:
    timestamp: float          # 秒
    event_type: EventType
    label: str                # 显示标签
    value: Optional[float] = None  # 数值（如 TTC 值）
    side: Optional[str] = None     # 左侧/右侧
    metadata: Optional[dict] = None

@dataclass
class TimelineTrack:
    name: str                 # 轨道名称（如"警告状态"、"抑制信号"）
    events: List[TimelineEvent]
    color: str                # 轨道颜色
```

#### 3.2 HTML 生成器

```python
class TimelineHTMLGenerator:
    """生成交互式 HTML 时间线图"""
    
    def __init__(self, func_name: str, case_name: str):
        self.func_name = func_name
        self.case_name = case_name
        self.tracks: List[TimelineTrack] = []
        self.time_range: tuple[float, float] = (0, 10)  # 默认 0-10 秒
    
    def add_window_track(self, windows: List[dict]):
        """添加测试窗口轨道"""
        track = TimelineTrack(name="测试窗口", events=[], color="#3b82f6")
        for w in windows:
            track.events.append(TimelineEvent(
                timestamp=w["t_start"],
                event_type=EventType.WINDOW_START,
                label=w.get("trigger_reason", "窗口开始"),
                metadata={"t_end": w["t_end"]}
            ))
        self.tracks.append(track)
    
    def add_state_track(self, transitions: List[dict]):
        """添加状态跳变轨道"""
        track = TimelineTrack(name="状态跳变", events=[], color="#ef4444")
        for tr in transitions:
            track.events.append(TimelineEvent(
                timestamp=tr["t"],
                event_type=EventType.STATE_CHANGE,
                label=f"{tr['from']} → {tr['to']}",
                side=tr.get("side"),
                metadata={"field": tr.get("field")}
            ))
        self.tracks.append(track)
    
    def add_suppression_track(self, suppression_data: List[dict]):
        """添加抑制信号轨道"""
        track = TimelineTrack(name="抑制信号", events=[], color="#f59e0b")
        for sup in suppression_data:
            track.events.append(TimelineEvent(
                timestamp=sup["t"],
                event_type=EventType.SUPPRESSION,
                label=sup["signal_name"],
                value=sup.get("value"),
                metadata={"condition": sup.get("condition")}
            ))
        self.tracks.append(track)
    
    def add_warning_track(self, warning_timeline: List[dict]):
        """添加警告状态轨道"""
        track = TimelineTrack(name="警告状态", events=[], color="#10b981")
        for w in warning_timeline:
            track.events.append(TimelineEvent(
                timestamp=w["t"],
                event_type=EventType.WARNING,
                label=w["status"],
                value=w.get("ttc"),
                side=w.get("side")
            ))
        self.tracks.append(track)
    
    def generate(self, output_path: str) -> str:
        """生成 HTML 文件"""
        html_template = self._build_html()
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html_template)
        return output_path
    
    def _build_html(self) -> str:
        """构建 HTML 内容"""
        # 使用内联 SVG + JavaScript 实现交互
        return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <title>{self.func_name} 时间线 - {self.case_name}</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; margin: 20px; }}
        .timeline {{ border: 1px solid #ddd; border-radius: 8px; padding: 20px; overflow-x: auto; }}
        .track {{ height: 60px; border-bottom: 1px solid #eee; position: relative; }}
        .track-label {{ position: absolute; left: 0; top: 20px; font-weight: bold; background: white; padding: 0 10px; }}
        .event {{ position: absolute; top: 25px; padding: 4px 8px; border-radius: 4px; font-size: 12px; cursor: pointer; transform: translateX(-50%); }}
        .event:hover {{ transform: translateX(-50%) scale(1.1); z-index: 100; }}
        .event.window {{ background: #3b82f6; color: white; }}
        .event.state {{ background: #ef4444; color: white; }}
        .event.suppression {{ background: #f59e0b; color: white; }}
        .event.warning {{ background: #10b981; color: white; }}
        .tooltip {{ position: fixed; background: #1f2937; color: white; padding: 8px 12px; border-radius: 4px; font-size: 12px; pointer-events: none; display: none; z-index: 1000; }}
        .time-axis {{ position: relative; height: 30px; margin-top: 10px; }}
        .time-marker {{ position: absolute; top: 0; font-size: 11px; color: #666; }}
    </style>
</head>
<body>
    <h1>{self.func_name} 诊断时间线</h1>
    <p>案例：{self.case_name} | 时间范围：{self.time_range[0]:.1f}s ~ {self.time_range[1]:.1f}s</p>
    
    <div class="timeline" id="timeline">
        {self._render_tracks()}
        {self._render_time_axis()}
    </div>
    
    <div class="tooltip" id="tooltip"></div>
    
    <script>
        // 交互逻辑：悬停显示详情、点击缩放、拖动平移
        document.querySelectorAll('.event').forEach(event => {{
            event.addEventListener('mouseenter', (e) => {{
                const tooltip = document.getElementById('tooltip');
                tooltip.innerHTML = e.target.dataset.details || e.target.textContent;
                tooltip.style.display = 'block';
                tooltip.style.left = (e.clientX + 10) + 'px';
                tooltip.style.top = (e.clientY + 10) + 'px';
            }});
            event.addEventListener('mouseleave', () => {{
                document.getElementById('tooltip').style.display = 'none';
            }});
        }});
    </script>
</body>
</html>"""
    
    def _render_tracks(self) -> str:
        """渲染所有轨道"""
        # 计算时间轴缩放比例
        time_range = self.time_range[1] - self.time_range[0]
        
        html = ""
        for track in self.tracks:
            html += f'<div class="track" style="left: 100px;">'
            html += f'<div class="track-label" style="color: {track.color};">{track.name}</div>'
            
            for event in track.events:
                left_pct = ((event.timestamp - self.time_range[0]) / time_range) * 100
                event_class = event.event_type.value.replace("_", "")
                details = f"时间：{event.timestamp:.3f}s<br>类型：{event.event_type.value}"
                if event.value is not None:
                    details += f"<br>数值：{event.value}"
                if event.side:
                    details += f"<br>侧别：{event.side}"
                
                html += f'<div class="event {event_class}" style="left: {left_pct}%;" data-details="{details}">{event.label}</div>'
            
            html += "</div>"
        
        return html
    
    def _render_time_axis(self) -> str:
        """渲染时间轴"""
        time_range = self.time_range[1] - self.time_range[0]
        html = '<div class="time-axis" style="left: 100px; width: 90%;">'
        
        # 每 1 秒一个标记
        for sec in range(int(self.time_range[0]), int(self.time_range[1]) + 1):
            left_pct = ((sec - self.time_range[0]) / time_range) * 100
            html += f'<div class="time-marker" style="left: {left_pct};">| {sec}s</div>'
        
        html += "</div>"
        return html
```

#### 3.3 调用集成

在 `ai/orchestrator.py` 的 `run_diagnosis` 方法末尾添加：

```python
# Phase 5 之后，生成可视化时间线
status("timeline_viz", "Generating timeline visualization...")
from ai.timeline_viz import TimelineHTMLGenerator

viz = TimelineHTMLGenerator(func_name, case_dir.name)

# 添加测试窗口
if windows:
    viz.add_window_track([
        {"t_start": w.t_start, "t_end": w.t_end, "trigger_reason": w.trigger_reason}
        for w in windows
    ])

# 添加状态跳变
if transitions:
    viz.add_state_track(transitions)

# 添加抑制信号（从 suppression_text 解析）
# ... 解析逻辑 ...

# 添加警告状态（从 evidence 提取）
# ... 提取逻辑 ...

timeline_html_path = case_dir / "timeline.html"
viz.generate(str(timeline_html_path))
status("timeline_viz", f"Timeline saved: {timeline_html_path}")
```

#### 3.4 输出文件

每个案例目录生成：
- `report.md` - 文本报告（已有）
- `timeline.html` - 交互式时间线图（新增）
- `expert_opinions.md` - 专家意见（已有）

### 验收标准

1. 生成的 HTML 可在浏览器中打开
2. 时间轴清晰展示测试窗口、状态跳变、抑制信号
3. 悬停事件显示详细信息
4. 支持拖动平移和缩放（可选）

---

## 优化 6: 诊断模式模板系统

### 目标

为不同 ADAS 功能定义标准化的诊断模板，确保诊断覆盖所有关键检查点，减少遗漏。

### 修改文件

1. `ai/diagnosis_templates.py` - 新建文件，定义各功能的诊断模板
2. `ai/expert_panel.py` - 在专家提示中注入对应功能的模板
3. `ai/orchestrator.py` - 根据识别的功能加载对应模板

### 详细设计

#### 6.1 模板数据结构

```python
# ai/diagnosis_templates.py

from dataclasses import dataclass
from typing import List, Optional

@dataclass
class Checkpoint:
    """诊断检查点"""
    name: str                    # 检查点名称
    description: str             # 检查点描述
    required_signals: List[str]  # 需要的信号
    code_files: List[str]        # 相关代码文件
    common_issues: List[str]     # 常见问题
    priority: int                # 优先级 (1-最高)

@dataclass
class DiagnosisTemplate:
    """功能诊断模板"""
    func_name: str               # 功能名称 (RCTA/FCTA/...)
    description: str             # 功能描述
    checkpoints: List[Checkpoint] # 检查点列表
    typical_root_causes: List[str] # 典型根因
    suppression_signals: List[str] # 已知抑制信号
```

#### 6.2 各功能模板定义

```python
# ai/diagnosis_templates.py

TEMPLATES: dict[str, DiagnosisTemplate] = {
    "RCTA": DiagnosisTemplate(
        func_name="RCTA",
        description="倒车横向交通预警 (Rear Cross Traffic Alert)",
        checkpoints=[
            Checkpoint(
                name="目标检测",
                description="确认雷达是否正确检测到横向目标",
                required_signals=["radar_objects", "radar_debug"],
                code_files=["adas/symmetry/perception/src/track.c"],
                common_issues=[
                    "目标被过滤（概率阈值、尺寸过滤）",
                    "跟踪丢失（目标短暂遮挡）",
                    "目标分类错误（误识别为静止物体）"
                ],
                priority=1
            ),
            Checkpoint(
                name="TTC 计算",
                description="验证时间到碰撞 (TTC) 计算是否正确",
                required_signals=["ttc", "target_speed", "ego_speed"],
                code_files=["coem/GWM_B26/components/AswPerception/func/adasFunc.c"],
                common_issues=[
                    "TTC 阈值配置错误",
                    "速度值异常（单位转换错误）",
                    "预测轨迹不准确"
                ],
                priority=2
            ),
            Checkpoint(
                name="触发条件",
                description="检查 FCTA 触发条件是否满足",
                required_signals=["gear_state", "ego_speed", "brake_status"],
                code_files=["coem/GWM_B26/components/AswPerception/func/adasFunc.c"],
                common_issues=[
                    "档位状态不满足（非 R 档）",
                    "车速超过阈值（>15km/h）",
                    "制动状态异常"
                ],
                priority=3
            ),
            Checkpoint(
                name="抑制信号",
                description="检查外部抑制信号状态",
                required_signals=["CR_RctaSuppression", "turn_signal", "lca_active"],
                code_files=["coem/GWM_B26/components/AswIf/ASW_IN/RteComMapping.c"],
                common_issues=[
                    "LCA 功能激活抑制 RCTA",
                    "转向灯抑制同侧预警",
                    "外部系统强制抑制"
                ],
                priority=1  # 高优先级，先检查
            ),
            Checkpoint(
                name="输出协调",
                description="验证左右雷达输出协调逻辑",
                required_signals=["CR_RctaWarnL", "CR_RctaWarnR"],
                code_files=["coem/GWM_B26/components/AswIf/ASW_OUT/ASWOUT_OutCalc.c"],
                common_issues=[
                    "左右雷达从属逻辑错误",
                    "CAN 输出映射错误",
                    "状态保持时间不足"
                ],
                priority=4
            ),
        ],
        typical_root_causes=[
            "抑制信号激活（LCA/转向灯/外部系统）",
            "目标过滤阈值过严",
            "TTC 计算误差",
            "档位/车速条件不满足",
            "RteComMapping 信号映射错误"
        ],
        suppression_signals=[
            "CR_RctaSuppression",
            "TurnSignalLeft",
            "TurnSignalRight", 
            "LcaActive",
            "GearNotReverse"
        ]
    ),
    
    "FCTA": DiagnosisTemplate(
        func_name="FCTA",
        description="前进横向交通预警 (Front Cross Traffic Alert)",
        checkpoints=[
            Checkpoint(
                name="目标检测",
                description="确认前方横向目标检测",
                required_signals=["radar_objects_front", "radar_debug"],
                code_files=["adas/symmetry/perception/src/track.c"],
                common_issues=[
                    "目标被过滤",
                    "跟踪丢失",
                    "目标分类错误"
                ],
                priority=1
            ),
            Checkpoint(
                name="触发条件",
                description="检查 FCTA 触发条件",
                required_signals=["gear_state", "ego_speed", "steering_angle"],
                code_files=["coem/GWM_B26/components/AswPerception/func/adasFunc.c"],
                common_issues=[
                    "车速超过阈值（<10km/h）",
                    "方向盘角度过大",
                    "非 D/R 档"
                ],
                priority=2
            ),
            # ... 更多检查点
        ],
        typical_root_causes=[
            "车速条件不满足",
            "目标检测失败",
            "抑制信号激活"
        ],
        suppression_signals=[
            "CR_FctaSuppression",
            "BrakeApplied",
            "AebActive"
        ]
    ),
    
    "BSD": DiagnosisTemplate(
        func_name="BSD",
        description="盲点检测 (Blind Spot Detection)",
        checkpoints=[
            # ... BSD 检查点
        ],
        typical_root_causes=[
            # ...
        ],
        suppression_signals=[
            # ...
        ]
    ),
    
    # ... 其他功能模板 (LCA, DOW, RCW, RCTB, FCTB)
}

def get_template(func_name: str) -> Optional[DiagnosisTemplate]:
    """获取指定功能的诊断模板"""
    return TEMPLATES.get(func_name.upper())

def get_all_templates() -> List[DiagnosisTemplate]:
    """获取所有模板"""
    return list(TEMPLATES.values())
```

#### 6.3 专家面板集成

在 `ai/expert_panel.py` 的专家提示中注入模板：

```python
# ai/expert_panel.py

def build_expert_prompt(self, func_name: str, data_summary: str, ...) -> str:
    """构建专家诊断提示"""
    
    from ai.diagnosis_templates import get_template
    
    template = get_template(func_name)
    template_section = ""
    
    if template:
        checkpoints_text = "\n".join([
            f"{i+1}. [{cp.name}] (优先级{cp.priority})\n   {cp.description}\n   信号：{', '.join(cp.required_signals)}\n   常见问题：{', '.join(cp.common_issues)}"
            for i, cp in enumerate(sorted(template.checkpoints, key=lambda x: x.priority))
        ])
        
        template_section = f"""

## {func_name} 诊断检查表 (必读)

请按照以下优先级顺序进行检查:

{checkpoints_text}

### 典型根因参考
{chr(10).join('- ' + rc for rc in template.typical_root_causes)}

### 已知抑制信号
{chr(10).join('- ' + ss for ss in template.suppression_signals)}
"""
    
    prompt = f"""你是 {func_name} 功能诊断专家。

## 问题描述
{problem}

## 预期结果
{expected}

{template_section}

## 数据摘要
{data_summary}

请按照诊断检查表逐项分析，给出根因判断。
"""
    
    return prompt
```

#### 6.4 报告增强

在诊断报告中增加"检查表完成情况"：

```markdown
## 诊断检查表完成情况

| 检查点 | 状态 | 发现 |
|--------|------|------|
| [1] 抑制信号 | ✅ 已检查 | CR_RctaSuppression=0，未抑制 |
| [2] 目标检测 | ⚠️ 异常 | 目标在 t=3.2s 时被过滤 |
| [3] TTC 计算 | ✅ 已检查 | TTC=1.8s < 阈值 2.0s |
| [4] 触发条件 | ✅ 已检查 | 档位=R，车速=8km/h |
| [5] 输出协调 | ⚠️ 异常 | 左雷达未输出警告 |

**结论**: 目标过滤 + 输出协调问题导致漏报
```

### 验收标准

1. 为所有 8 个功能 (BSD/LCA/DOW/RCW/RCTA/RCTB/FCTA/FCTB) 定义模板
2. 每个模板至少包含 4 个检查点
3. 专家提示中自动注入对应功能的模板
4. 报告中展示检查表完成情况

---

## 实现优先级

| 优先级 | 优化项 | 预计工时 | 依赖 |
|--------|--------|----------|------|
| P0 | 优化 6: 诊断模板 | 4 小时 | 无 |
| P1 | 优化 2: 置信度评分 | 3 小时 | 无 |
| P2 | 优化 3: 可视化时间线 | 6 小时 | 无 |

**建议实现顺序**: 先实现诊断模板（提升诊断质量），再实现置信度评分（量化质量），最后实现可视化（提升体验）。

---

## 测试建议

```python
# tests/test_optimizations.py

def test_confidence_score():
    """测试置信度评分"""
    result = run_diagnosis("cases/FCTA001")
    assert "confidence" in result
    assert 0.0 <= result["confidence"]["overall"] <= 1.0
    assert result["confidence"]["level"] in ["HIGH", "MEDIUM", "LOW"]

def test_timeline_generation():
    """测试时间线生成"""
    from pathlib import Path
    case_dir = Path("cases/FCTA001")
    run_diagnosis(case_dir)
    assert (case_dir / "timeline.html").exists()

def test_template_coverage():
    """测试模板覆盖"""
    from ai.diagnosis_templates import get_all_templates
    templates = get_all_templates()
    assert len(templates) >= 8  # 至少 8 个功能
    for t in templates:
        assert len(t.checkpoints) >= 4  # 每个至少 4 个检查点
```
