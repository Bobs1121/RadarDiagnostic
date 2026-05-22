# Visualizer — 交互式 HTML 报告生成器

## 职责

将管线所有产物 (FrameStore, test windows, TPE evidence, parameter sensitivity, expert verdict) 整合为单个独立的 `report.html` 文件。

## 设计目标

1. **Data-first**: 用户能从图表自行推导 AI 结论，即使文字分析有误
2. **Offline**: plotly.js 内联，无需联网即可打开
3. **专业排版**: 蓝灰配色、卡片布局、粘性目录、Markdown 渲染的专家文字
4. **通用**: 不泄漏 FCTB/front-corner 特例，同一模板服务所有 8 个功能和 4 种任务类型

## 技术栈

- **Plotly.js**: 内联，离线渲染交互式图表
- **Markdown-it**: 渲染专家文字为 HTML (表格、代码块、列表)
- **纯 HTML/CSS**: 无框架依赖，单个文件

## 配色方案

```python
_PALETTE = [
    "#2563eb",  # primary blue
    "#0ea5e9",  # sky
    "#14b8a6",  # teal
    "#8b5cf6",  # violet
    "#f59e0b",  # amber
    "#ef4444",  # red
    "#10b981",  # emerald
    "#ec4899",  # pink
]
```

## 报告结构

```
┌─────────────────────────────────────────────────┐
│  Sticky TOC (左侧固定目录)                        │
├─────────────────────────────────────────────────┤
│  Header: 案例标题 + 功能 + 时间                   │
│                                                │
│  Section 1: 问题描述                             │
│  Section 2: 测试窗口                             │
│  Section 3: 关键事实摘要                          │
│  Section 4: 数据图表                             │
│    - 自车速度时序                                 │
│    - 目标属性时序 (dist_x, vel_x, ttc)          │
│    - 状态机时序                                   │
│    - 告警标志时序                                 │
│    - CAN 信号时序                                 │
│  Section 5: TPE 时序模式分析                     │
│  Section 6: 外部抑制分析                         │
│  Section 7: 专家面板结论                          │
│  Section 8: 根因分析                             │
│  Section 9: 建议                                 │
└─────────────────────────────────────────────────┘
```

## 图表构建

每个图表生成器返回 `ChartSection`，统一渲染为卡片 (anchor + title + caption)。

### 支持的图表类型

| 图表 | 数据源 | 用途 |
|------|--------|------|
| 速度时序 | car_spd | 自车速度变化 |
| 目标距离时序 | dist_x, dist_y | 目标相对位置 |
| 目标速度时序 | vel_x, vel_y | 目标相对速度 |
| TTC 时序 | ttc | 碰撞时间 |
| 状态机时序 | *SystemState | 状态变化 |
| 告警标志时序 | *_flag | 告警触发 |
| 信号热力图 | CAN 信号 | 信号分布 |
| 边际直方图 | 参数 vs 观测 | 灵敏度分析 |

### Plotly 布局默认

```python
def _plotly_layout_defaults() -> dict:
    return dict(
        template="plotly_white",
        font=dict(
            family='"Inter", "Segoe UI", ..., sans-serif',
            size=12,
            color="#1e293b",
        ),
        paper_bgcolor="white",
        plot_bgcolor="#f8fafc",
        colorway=_PALETTE,
        margin=dict(l=48, r=24, t=56, b=48),
        ...
    )
```

## Markdown 渲染

```python
# 专家文字用 Markdown 渲染，保留:
# - 表格 → HTML table
# - 代码块 → <pre><code>
# - 列表 → <ul>/<ol>
# - 加粗/斜体 → <strong>/<em>
# 而不是渲染为纯等宽文本
```

## 构建入口

```python
def build_report(
    case_dir: Path,
    func_name: str,
    evidence: dict,
    tpe_report: dict,
    expert_result: dict,
    windows: list[TestWindow],
    output_path: Path,
) -> str:
    """
    生成完整报告，返回文件路径。
    """
```

## 输出

```
cases/FCTA001/report.html
cases/RCTB002/report.html
...
```

单个 HTML 文件，< 5MB，离线可打开。
