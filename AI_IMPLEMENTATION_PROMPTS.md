# radarAnalyze 增强功能实现提示词

> 使用方式：将对应章节复制给 AI 代理执行

---

## 提示词 1：AutoDream 架构知识增强

```
【任务】增强 radarAnalyze 的 AutoDream 系统，让它能够自动收集和整理项目架构知识，而不仅仅是诊断经验。

【项目背景】
radarAnalyze 是一个角雷达问题分析系统，基于 AI 驱动的自动化诊断平台。
项目位置：D:/RamboStar/idea/radarAnalyze
源码位置：D:/cr60_light（TI AWR2E44P 平台代码）

【当前状态】
auto_dream.py 目前只收集：
- 诊断会话记录
- 模式库（patterns.json）
- 功能知识（functions/*.json）
- 信号映射统计

【需要新增的能力】

### 1. 代码架构分析模块

在 auto_dream.py 中新增方法：

```python
def _gather_architecture_context(self) -> str:
    """收集项目架构知识"""
    # 1.1 扫描 #include 依赖，生成模块依赖图
    # 1.2 提取关键数据结构定义（struct/typedef）
    # 1.3 分析函数调用关系（重点：adasFunc.c, RteComMapping.c, ASWIN_SystemState.c）
    # 1.4 推断代码命名规范（变量前缀、函数命名模式）
```

### 2. 架构知识存储

创建 memory/architecture.json，结构如下：

```json
{
  "modules": {
    "adasFunc.c": {
      "path": "coem/GWM_B26/components/AswPerception/func/adasFunc.c",
      "dependencies": ["paraDefine.h", "structDefine.h"],
      "key_functions": ["FCTA_Calc", "FCTB_Calc", "BSD_Calc"],
      "responsible_for": "报警条件判断与阈值比较",
      "line_count": 6500
    },
    "RteComMapping.c": {
      "path": "coem/GWM_B26/components/AswIf/ASW_IN/RteComMapping.c",
      "dependencies": ["DBC 定义", "globalVariDef.c"],
      "responsible_for": "CAN 信号到内部变量的映射"
    }
  },
  "data_flow": [
    {
      "name": "报警触发链路",
      "steps": [
        {"layer": "L1", "component": "CAN 总线", "data": "CR_FctaWarnReq"},
        {"layer": "L2", "component": "RteComMapping.c", "data": "bFCTAEnable"},
        {"layer": "L3", "component": "adasFunc.c", "data": "FCTA_Calc()"},
        {"layer": "L4", "component": "ASWOUT_OutCalc.c", "data": "警告输出"}
      ]
    }
  ],
  "coding_conventions": {
    "bool_variable_prefix": "b",
    "float_variable_prefix": "f",
    "global_variable_prefix": "g_",
    "flag_suffix": "Flg",
    "function_naming": "PascalCase",
    "variable_naming": "camelCase"
  },
  "key_structures": [
    {
      "name": "DTCStruct",
      "file": "globalVariDef.c",
      "key_fields": ["bAEBBAActiveFlg", "bAEBIBActiveFlg", "DTCCode"]
    }
  ]
}
```

### 3. 集成到现有流程

修改 `_gather_all_memory_context()` 方法，在现有内容后追加：
- 架构知识摘要（modules 统计、data_flow 概览）
- 代码规范（命名规则、常见模式）

### 4. 验收标准

- architecture.json 自动生成，包含至少 5 个核心模块
- data_flow 至少包含 2 条完整链路（如报警触发、抑制检测）
- coding_conventions 能正确推断出 b/f/g_ 前缀规则
- AutoDream 运行后，架构知识自动更新到 project.md

【交付物】
1. 修改后的 auto_dream.py
2. 新增的 memory/architecture.json（初始版本）
3. 单元测试：验证架构提取准确性
```

---

## 提示词 2：Coding 助手（DBC → 代码生成）

```
【任务】为 radarAnalyze 添加 Coding 助手功能，能够根据 DBC 文件和映射表自动生成 RteComMapping 代码。

【项目背景】
- 项目位置：D:/RamboStar/idea/radarAnalyze
- DBC 文件：CR_DBC_V3.2_20260331.dbc, GAC_CR_FR&FL_Private_CAN_V1.3.dbc
- 目标文件：D:/cr60_light/coem/GWM_B26/components/AswIf/ASW_IN/RteComMapping.c

【参考代码风格】

现有 RteComMapping.c 的代码模式：

```c
// 布尔信号映射
uint8_t u8tmp;
RteComMapping_ReadSignal(AEBBAActv_0x137, &u8tmp);
PERInputCapture.DTCCode.bAEBBAActiveFlg = (u8tmp != 0);

// 数值信号映射
RteComMapping_ReadSignal(EgoVehSpd_0x137, &u16tmp);
PERInputCapture.VehicleDynamics.fEgoSpeed = (float)u16tmp * 0.01f;

// 多值枚举映射
RteComMapping_ReadSignal(GearState_0x188, &u8tmp);
if (u8tmp == 1) {
    PERInputCapture.VehicleDynamics.eGearState = GEAR_P;
} else if (u8tmp == 2) {
    PERInputCapture.VehicleDynamics.eGearState = GEAR_R;
}
```

【需要实现的功能】

### 1. 新建模块：ai/code_generator.py

```python
class CodeGenerator:
    """基于 DBC + 映射表生成 RteComMapping 代码"""
    
    def __init__(self, dbc_loader, reference_file: Path):
        self.dbc = dbc_loader
        self.reference = reference_file  # 用于学习代码风格
        
    def generate_mapping_code(
        self,
        can_signal: str,      # 如 "CR_BsdSuppression"
        internal_var: str,    # 如 "PERInputCapture.bBSDSuppressionFlg"
        signal_type: str = "bool",  # bool/int/float/enum
        scale: float = 1.0,
        offset: float = 0.0,
        enum_mapping: dict = None  # {1: "ENUM_A", 2: "ENUM_B"}
    ) -> str:
        """
        生成单个信号的映射代码
        
        返回格式：
        ```c
        // CR_BsdSuppression → bBSDSuppressionFlg
        uint8_t u8tmp;
        RteComMapping_ReadSignal(CR_BsdSuppression_0x137, &u8tmp);
        PERInputCapture.bBSDSuppressionFlg = (u8tmp != 0);
        ```
        """
        pass
    
    def generate_from_excel(
        self,
        excel_path: Path,  # 映射表 Excel 文件
        output_file: Path  # 生成的 .c 文件
    ) -> None:
        """
        批量生成：从 Excel 映射表生成完整代码文件
        
        Excel 格式：
        | CAN 信号名 | 内部变量 | 类型 | Scale | Offset | 备注 |
        | CR_BsdSuppression | bBSDSuppressionFlg | bool | 1 | 0 | BSD 抑制 |
        """
        pass
    
    def validate_generated_code(
        self,
        generated_code: str,
        existing_code: str
    ) -> list[str]:
        """
        验证生成的代码：
        - 检查变量名是否已存在
        - 检查临时变量命名冲突（u8tmp, u16tmp 等）
        - 检查代码风格一致性
        """
        pass
```

### 2. CLI 接口扩展

在 cli.py 中新增命令：

```python
parser.add_argument("--generate-mapping", action="store_true",
                    help="生成 RteComMapping 代码")
parser.add_argument("--can-signal", help="CAN 信号名")
parser.add_argument("--internal-var", help="内部变量名")
parser.add_argument("--signal-type", choices=["bool", "int", "float", "enum"],
                    default="bool")
parser.add_argument("--dbc", help="DBC 文件路径")
parser.add_argument("--excel", help="批量生成：Excel 映射表路径")
```

使用示例：

```bash
# 单个信号生成
python cli.py --generate-mapping \
    --can-signal "CR_BsdSuppression" \
    --internal-var "PERInputCapture.bBSDSuppressionFlg" \
    --signal-type "bool" \
    --dbc "CR_DBC_V3.2_20260331.dbc"

# 批量生成
python cli.py --generate-mapping \
    --excel "mapping_table.xlsx" \
    --output "generated_mapping.c"
```

### 3. 代码风格学习

从 reference_file（现有 RteComMapping.c）中学习：
- 临时变量命名模式（u8tmp, u16tmp_1, u16tmp_2...）
- 注释格式（// 信号名 → 变量名）
- 缩进风格（4 空格）
- 换行规则（长行是否换行）

### 4. 验收标准

- 单个信号生成：输出代码可直接粘贴到 RteComMapping.c
- 批量生成：生成的文件编译无错误
- 验证功能：能检测出变量名冲突
- 风格一致：生成的代码与现有代码风格一致

【交付物】
1. ai/code_generator.py（完整实现）
2. cli.py 修改（新增 --generate-mapping 命令）
3. 示例 Excel 模板：mapping_template.xlsx
4. 单元测试：验证代码生成正确性
```

---

## 提示词 3：可视化报告（HTML + 时间线）

```
【任务】为 radarAnalyze 添加 HTML 可视化报告生成，包含交互式时间线图。

【项目背景】
- 项目位置：D:/RamboStar/idea/radarAnalyze
- 现有报告：cases/<CASE>/report.md（Markdown 格式）
- 需要新增：cases/<CASE>/report.html（交互式 HTML）

【需要实现的功能】

### 1. 新建模块：ai/timeline_viz.py

```python
from dataclasses import dataclass
from typing import List, Optional
from enum import Enum

class EventType(Enum):
    WINDOW_START = "window_start"
    WINDOW_END = "window_end"
    STATE_CHANGE = "state_change"
    SUPPRESSION = "suppression"
    WARNING = "warning"
    SHORT_PULSE = "short_pulse"  # TPE 检测到的短脉冲

@dataclass
class TimelineEvent:
    timestamp: float
    event_type: EventType
    label: str
    value: Optional[float] = None
    side: Optional[str] = None  # Left/Right
    metadata: Optional[dict] = None

@dataclass
class TimelineTrack:
    name: str
    events: List[TimelineEvent]
    color: str

class TimelineViz:
    """生成交互式 HTML 时间线图"""
    
    def __init__(self, func_name: str, case_name: str):
        self.func_name = func_name
        self.case_name = case_name
        self.tracks: List[TimelineTrack] = []
        self.time_range: tuple[float, float] = (0, 10)
    
    def add_window_track(self, windows: List[dict]):
        """添加测试窗口轨道"""
        pass
    
    def add_state_track(self, transitions: List[dict]):
        """添加状态跳变轨道"""
        pass
    
    def add_suppression_track(self, suppression_data: List[dict]):
        """添加抑制信号轨道"""
        pass
    
    def add_tpe_patterns(self, tpe_results: dict):
        """添加 TPE 检测到的模式（短脉冲、震荡等）"""
        pass
    
    def add_signal_heatmap(self, signal_name: str, samples: List[tuple]):
        """添加信号值热力图（连续值如 TTC、距离）"""
        pass
    
    def generate(self, output_path: str) -> str:
        """生成 HTML 文件"""
        pass
```

### 2. HTML 报告结构

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <title>{func_name} 诊断报告 - {case_name}</title>
    <style>
        /* 响应式布局、暗色主题、交互式组件样式 */
    </style>
</head>
<body>
    <!-- 1. 报告头部 -->
    <div class="header">
        <h1>{func_name} 诊断报告</h1>
        <table class="meta-table">
            <tr><td>案例</td><td>{case_name}</td></tr>
            <tr><td>问题</td><td>{problem}</td></tr>
            <tr><td>置信度</td><td>⭐⭐⭐⭐ {confidence}/100</td></tr>
        </table>
    </div>

    <!-- 2. 交互式时间线 -->
    <div class="timeline-container">
        <div class="timeline-controls">
            <button id="zoom-in">放大</button>
            <button id="zoom-out">缩小</button>
            <button id="reset">重置</button>
        </div>
        <div class="tracks">
            <!-- 测试窗口轨道 -->
            <div class="track window-track">
                <span class="track-label">测试窗口</span>
                <div class="window" data-start="2.5" data-end="5.0">
                    窗口 1 (2.5s~5.0s)
                </div>
            </div>
            
            <!-- 状态跳变轨道 -->
            <div class="track state-track">
                <span class="track-label">状态跳变</span>
                <div class="event state-change" data-t="3.2" data-from="1" data-to="2">
                    t=3.2s: Standby→Active
                </div>
            </div>
            
            <!-- 抑制信号轨道 -->
            <div class="track suppression-track">
                <span class="track-label">抑制信号</span>
                <div class="event suppression" data-t="3.1" data-value="1">
                    ⚠ AEBBAActv=0 (抑制)
                </div>
            </div>
            
            <!-- TPE 短脉冲轨道 -->
            <div class="track tpe-track">
                <span class="track-label">TPE 短脉冲</span>
                <div class="event short-pulse" data-t="3.15" data-duration="120ms">
                    ⚡ AEBBAActv 短脉冲 (120ms)
                </div>
            </div>
            
            <!-- 信号热力图轨道 -->
            <div class="track heatmap-track">
                <span class="track-label">TTC 值</span>
                <svg class="heatmap">
                    <!-- 用颜色深浅表示 TTC 值 -->
                </svg>
            </div>
        </div>
        
        <!-- 时间轴 -->
        <div class="time-axis">
            <span class="marker">0s</span>
            <span class="marker">2s</span>
            <span class="marker">4s</span>
            <span class="marker">6s</span>
            <span class="marker">8s</span>
            <span class="marker">10s</span>
        </div>
    </div>

    <!-- 3. 根因分析 -->
    <div class="root-cause">
        <h2>根因分析</h2>
        <div class="causal-chain">
            <!-- 可折叠的因果链树形图 -->
        </div>
    </div>

    <!-- 4. 条件检查表 -->
    <div class="condition-table">
        <table>
            <tr><th>条件</th><th>阈值</th><th>实际值</th><th>满足？</th></tr>
            <tr class="pass"><td>车速范围</td><td>5-15 km/h</td><td>8 km/h</td><td>✅</td></tr>
            <tr class="fail"><td>AEB 未激活</td><td>== FALSE</td><td>== TRUE</td><td>❌</td></tr>
        </table>
    </div>

    <!-- 5. 专家意见 -->
    <div class="expert-opinions">
        <!-- 5 专家结论对比 -->
    </div>

    <script>
        // 交互逻辑：悬停显示详情、点击缩放、拖动平移
    </script>
</body>
</html>
```

### 3. 集成到 orchestrator.py

在 `_save_report` 方法后调用：

```python
def _save_visualization(self, case_dir: Path, windows, transitions, 
                        suppression_text, tpe_results, evidence):
    """生成 HTML 可视化报告"""
    from ai.timeline_viz import TimelineViz
    
    viz = TimelineViz(self.func_name, case_dir.name)
    
    # 添加各轨道
    if windows:
        viz.add_window_track([
            {"t_start": w.t_start, "t_end": w.t_end, "reason": w.trigger_reason}
            for w in windows
        ])
    
    if transitions:
        viz.add_state_track(transitions)
    
    # 解析 suppression_text 并添加
    # ...
    
    # 生成 HTML
    html_path = case_dir / "report.html"
    viz.generate(str(html_path))
```

### 4. 验收标准

- HTML 可在浏览器中打开（Chrome/Edge/Firefox）
- 时间线支持悬停显示详情
- 支持缩放和平移（鼠标滚轮 + 拖动）
- 短脉冲事件高亮显示（红色闪烁）
- 热力图颜色正确反映数值大小
- 响应式布局（适配不同屏幕尺寸）

【交付物】
1. ai/timeline_viz.py（完整实现）
2. orchestrator.py 修改（集成可视化生成）
3. 静态资源：CSS 样式、JavaScript 交互逻辑
4. 示例报告：cases/FCATB001/report.html
```

---

## 提示词 4：误报分析专用增强

```
【任务】为 radarAnalyze 添加误报（False Positive）分析专用功能。

【问题场景】
误报常见原因：
1. 目标属性在阈值边界震荡（如 TTC 在 2.0s 附近频繁穿越）
2. 测量噪声导致误触发
3. 防抖机制失效

【需要实现的功能】

### 1. 目标属性震荡检测

在 temporal_analyzer.py 中新增：

```python
def analyze_boundary_oscillation(
    self,
    timeline: SignalTimeline,
    threshold: float,
    tolerance: float = 0.1  # 阈值附近的容忍范围
) -> dict:
    """
    检测信号是否在阈值边界震荡
    
    返回：
    {
        "oscillation_detected": true,
        "crossing_count": 5,  # 穿越次数
        "avg_oscillation_duration": 0.3,  # 平均震荡时长
        "crossing_times": [2.1, 2.4, 2.7, 3.0, 3.3],  # 穿越时刻
        "max_deviation": 0.15,  # 最大偏离阈值幅度
        "verdict": "边界震荡导致误触发"
    }
    """
    pass
```

### 2. 误报诊断模板

在 ai/diagnosis_templates.py 中新增：

```python
DiagnosisTemplate(
    func_name="FP_ANALYSIS",
    description="误报分析专用模板",
    checkpoints=[
        Checkpoint(
            name="边界震荡检查",
            description="目标属性是否在触发阈值附近震荡",
            required_signals=["ttc", "dist_x", "vel_x"],
            code_files=["adasFunc.c"],
            common_issues=[
                "TTC 在阈值 2.0s 附近频繁穿越",
                "目标距离测量噪声导致误触发",
                "速度计算抖动"
            ],
            priority=1
        ),
        Checkpoint(
            name="防抖机制检查",
            description="防抖计数/时长是否足够",
            required_signals=["warning_flag", "debounce_cnt"],
            code_files=["adasFunc.c", "postProcess.c"],
            common_issues=[
                "防抖时长过短",
                "防抖计数被清零",
                "边沿触发条件过于敏感"
            ],
            priority=2
        ),
        Checkpoint(
            name="目标稳定性检查",
            description="目标跟踪是否稳定",
            required_signals=["track_id", "track_age", "confidence"],
            code_files=["track.c", "objAttribCal.c"],
            common_issues=[
                "目标 ID 跳变",
                "跟踪年龄不足",
                "置信度过低仍触发"
            ],
            priority=3
        )
    ]
)
```

### 3. 误报分析视图

在 timeline_viz.py 中新增误报专用视图：

```python
def add_oscillation_view(self, signal: str, threshold: float, 
                         samples: List[tuple]):
    """
    添加震荡分析视图
    
    显示：
    - 信号曲线（带阈值线）
    - 穿越点高亮
    - 震荡区间标记
    """
    pass
```

### 4. 验收标准

- 能正确检测 TTC 在 2.0s 附近的震荡
- 穿越次数统计准确
- 误报模板能正确引导专家分析
- 可视化视图清晰展示震荡模式

【交付物】
1. temporal_analyzer.py 修改（新增震荡检测）
2. diagnosis_templates.py 修改（新增误报模板）
3. timeline_viz.py 修改（新增震荡视图）
4. 测试案例：验证误报检测准确性
```

---

## 使用建议

### 执行顺序

1. **先执行提示词 1**（AutoDream 架构增强）— 让系统了解项目结构
2. **再执行提示词 3**（可视化报告）— 提升分析体验
3. **然后执行提示词 2**（Coding 助手）— 提升开发效率
4. **最后执行提示词 4**（误报分析）— 完善诊断能力

### 交付验收

每个提示词执行完成后，检查：
- 代码能否编译/运行
- 单元测试是否通过
- 功能是否符合验收标准
- 文档是否完整

---

*生成时间：2026-04-17*
*适用项目：radarAnalyze (D:/RamboStar/idea/radarAnalyze)*
