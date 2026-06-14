# radarAnalyze v2 — Variant / Package / Material 设计稿（2026-06-13）

> 范围: 架构设计稿，指导后续实现
> 目标: 面向 ASW 工程师，满足可追溯、可复现、可审计、多项目可插拔

---

## 1. 设计结论

当前系统不应再用单一 `project_key` 表达“分析对象”。

真实工程对象至少包含 5 层：
- `platform_family`: 技术族/平台插件，例如 `gen6_c_radar`、`gen5_cpp_radar`
- `codebase`: 一份实际代码工作区，例如 `D:\GWM-CR60LIGHT\cr60_light`
- `variant`: 客户项目级变体，例如 `coem/GWM_B26`、`coem/BYD_SC6H`、`apl/byd`
- `package_profile`: 构建参数组合，决定最终软件包配置
- `snapshot`: 一次可复现分析对应的代码/DBC/配置快照

结论：
- 客户项目隔离边界按 `variant` 定义，而不是 repo、分支、单个文件路径
- 软件包差异按 `package_profile` 表达，而不是拆成新的 `variant`
- DBC/需求材料变化默认进入新的 `snapshot`，而不是立即新建 `variant`

---

## 2. 来自真实构建脚本的约束

### 2.1 Gen6 (`D:\GWM-CR60LIGHT\cr60_light`)

`coem\GWM_B26\buildscripts\build.bat` 的关键信息：
- 通过当前目录自动推导 `coemDir`
- 读取 `build.cfg`
- 最终调用 `scons_gen.bat %build_cfg% -d %coemDir% -b DEVELOP -f OFF`

`build.cfg` 示例：
```bat
-v GWM_B26
-p KL15
-a SYMMETRY
-ct T66MS
```

约束含义：
- `coemDir` 定义客户变体边界
- `-v/-p/-a/-ct/-b/-f/-t` 等参数定义软件包配置
- `patch.bat` 说明构建前可能对公共文件进行客户补丁注入

因此 Gen6 的包身份是：
`codebase_root + variant_path + build_flags + patch_state`

### 2.2 Gen5 (`C:\BYD_OVS_CB`)

`apl\byd\tools\build.bat` / `apl\gwm\tools\build.bat` 的关键信息：
- 从 `apl/<customer>` 目录进入通用 builder
- 转调 `reco_fw\tools\builder\cmake_gen.bat %ARGS%`

约束含义：
- 5 代和 6 代的源码组织不同，但“客户变体 + 构建参数”的本质相同
- 平台插件需要兼容 `coem/<variant>` 与 `apl/<customer>` 两种组织方式

---

## 3. 标识模型

### 3.1 PlatformFamily

定义核心能力插件，而不是客户差异。

字段建议：
- `platform_id`
- `language` (`c` / `cpp`)
- `build_system` (`scons` / `cmake`)
- `codegraph_plugin`
- `parser_plugin`
- `symbol_ruleset`
- `default_pipeline_profile`

### 3.2 Codebase

表示一份实际代码工作区。

字段建议：
- `codebase_id`
- `root_path`
- `repo_url` 可选
- `branch` 可选
- `commit` 可选
- `platform_id`

### 3.3 Variant

表示客户项目级边界，是知识沉淀和配置隔离的主键。

字段建议：
- `variant_id`，例如 `gen6/gwm_b26`
- `codebase_id`
- `scope.include_globs`
- `scope.exclude_globs`
- `build_entry`
- `default_package_profile`
- `dbc_sets`
- `file_hints`
- `signal_alias_overrides`
- `requirement_overlays`

原则：
- `variant` 只定义边界和差异，不承载具体构建快照
- 同客户项目下的小版本变化由 `snapshot` 承接

### 3.4 PackageProfile

表示“最终会产出哪种软件包”的构建配置组合。

字段建议：
- `package_profile_id`
- `variant_id`
- `build_flags`
- `macro_set`
- `patch_set`
- `artifact_rules`

Gen6 示例：
```yaml
package_profile_id: gen6/gwm_b26/default
variant_id: gen6/gwm_b26
build_flags:
  vehicleType: GWM_B26
  powerSupply: KL15
  antenna: SYMMETRY
  cyctime: T66MS
  swBuildType: DEVELOP
  funTestType: "OFF"
patch_set:
  source: coem/GWM_B26/buildscripts/patch
```

### 3.5 Snapshot

表示一次诊断/审计对应的精确快照。

字段建议：
- `snapshot_id`
- `variant_id`
- `package_profile_id`
- `code_snapshot`（commit 或文件 hash）
- `dbc_snapshot`（DBC 文件 hash 集）
- `material_snapshot`（需求材料 hash 集）
- `config_version`
- `model_profile`

原则：
- 任何诊断结论、知识沉淀、diff、Harness 评估都必须绑定到 `snapshot_id`

---

## 4. 客户需求材料设计

### 4.1 材料分层

必须区分两类：

- `AuthoritativeMaterial`
  - 客户需求文档
  - 状态机/功能规范
  - DBC
  - 参数表/阈值表
  - 验收标准

- `LearnedKnowledge`
  - 根因模式
  - 修复逻辑
  - 历史启发式

优先级规则：
- 生成结论时，权威材料优先级高于经验知识

### 4.2 Material 身份模型

字段建议：
- `material_id`
- `variant_id`
- `material_type` (`pdf` / `docx` / `md` / `xlsx` / `dbc` / `json` / `yaml`)
- `source_path`
- `hash`
- `version`
- `authoritative` (`true/false`)
- `tags`
- `created_at`

### 4.3 StructuredRequirementSet

解析与转化后，不直接存原文给诊断链路，而是存结构化需求集。

核心对象建议：
- `RequirementSpec`
- `SignalConstraint`
- `StateMachineConstraint`
- `ThresholdRule`
- `AcceptanceCriterion`
- `ProjectGlossary`

字段建议：
- `requirement_id`
- `material_id`
- `variant_id`
- `scope`（功能/模块/信号/状态）
- `statement`
- `normalized_logic`
- `linked_signals`
- `linked_files`
- `linked_functions`
- `priority`
- `evidence_policy`

### 4.4 材料接入流程

```text
Raw Materials
  -> Material Registry
  -> Format Parsers
  -> Normalizers / Transformers
  -> StructuredRequirementSet
  -> VariantOverlay / Diagnosis / Harness / Review
```

要求：
- 支持增量导入，不要求每次全量重建
- 材料更新后可追踪哪些知识和诊断需要失效

---

## 5. 可审计诊断产物

### 5.1 DiagnosisBundle

不能只输出 `report.md`，应输出结构化诊断包。

建议结构：
- `bundle_meta`
- `problem_statement`
- `snapshot_ref`
- `evidence_chain`
- `reasoning_graph`
- `root_cause_assessment`
- `code_localization`
- `change_proposal`
- `requirement_trace`
- `report_artifacts`

### 5.2 输出分级

诊断结论必须分级：
- `confirmed_root_cause`
- `candidate_root_causes`
- `evidence_summary_only`

门禁规则：
- 无完整证据链，不输出 `confirmed_root_cause`
- 无可靠定位，不输出可执行 `diff`

### 5.3 ChangeProposal

字段建议：
- `proposal_id`
- `bundle_id`
- `root_cause_pattern_ids`
- `target_files`
- `target_functions`
- `diff_text`
- `risk_notes`
- `expected_effect`
- `required_simulation`
- `approval_state`

---

## 6. 知识沉淀模型

### 6.1 RootCausePattern

优先沉淀的知识对象。

字段建议：
- `pattern_id`
- `variant_scope`（variant 级或 platform 级）
- `trigger_conditions`
- `evidence_signature`
- `associated_signals`
- `associated_states`
- `associated_code_locations`
- `confidence`
- `source_case_ids`
- `source_snapshot_ids`

### 6.2 FixPlaybook

与根因模式一一关联或多对一关联。

字段建议：
- `playbook_id`
- `pattern_id`
- `applicable_variants`
- `change_templates`
- `preconditions`
- `risk_checks`
- `post_change_checks`
- `simulation_recommendations`
- `validated_case_ids`

原则：
- `FixPlaybook` 不能脱离 `RootCausePattern` 单独存在
- 任何修复逻辑都要有来源案例和验证记录

---

## 7. 插件边界

### 7.1 PlatformPlugin

负责跨项目共享的核心技术能力：
- 语言解析
- CodeGraph 构建
- 符号抽取
- 构建脚本适配
- 默认诊断链路

### 7.2 VariantOverlay

负责客户项目级差异：
- 源码扫描边界
- DBC 集
- 关键文件提示
- 客户需求材料
- 信号别名/阈值覆盖
- 抑制/输出/状态机规则补丁

### 7.3 SimulationAdapter

当前只预留接口，不落实现。

建议字段：
- `adapter_id`
- `variant_id` / `platform_id`
- `entry_command`
- `artifact_parser`
- `result_metrics`

---

## 8. 推荐实现顺序

P0：
- 落地 `variant / package_profile / snapshot` 身份模型
- 落地 `DiagnosisBundle` schema 和输出分级门禁
- 落地 `RootCausePattern / FixPlaybook` schema

P1：
- 落地 `Material Registry + StructuredRequirementSet`
- 将权威材料接入 `VariantOverlay`
- 将 Harness 接入 `snapshot` 和 `DiagnosisBundle`

P2：
- 接入 `SimulationAdapter`
- 建立“诊断 -> diff -> 仿真 -> 回灌知识”闭环

