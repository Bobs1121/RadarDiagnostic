# core/ 模块实现说明

`core/` 承载身份、材料、诊断包等可审计模型，供 CLI、Orchestrator、Harness 共享。

## 模块概览

| 文件 | 定位 |
|------|------|
| `identity.py` | PlatformFamily / Codebase / Variant / PackageProfile / Snapshot 等身份模型 |
| `workspace.py` | V3 Workspace 运行时资源沙盒，负责 Core+COEM 继承、DBC/源码/需求路径解析 |
| `materials.py` | MaterialRegistry / StructuredRequirementSet / RequirementSpec / 材料摘要渲染 |
| `diagnosis_bundle.py` | DiagnosisBundle、Evidence、CodeLocation、结论等级与结构化诊断产物 |
| `snapshot_store.py` | Snapshot 文件存储与加载 |
| `freshness.py` | variant 级 freshness manifest：源码/DBC/requirements/identity 指纹与 stale 对比 |
| `knowledge_guard.py` | AI 上下文读取闸门 + `knowledge_manifest.json` 模块级成功发布与输入签名校验 |
| `plugin.py` | **统一插件注册表** `PluginRegistry`：`register/get/registered/clear(kind)/discover`，装饰器 + importlib 自动扫包 |

## plugin.py — 统一插件注册表

`core/plugin.py` 提供单一装饰器驱动的插件注册表，使新 parser / platform adapter / 记忆后端**零改核心**接入：

- `PluginRegistry.register(kind, key)` — 装饰器注册（如 `@PluginRegistry.register("parser", ".bag")`）
- `PluginRegistry.get(kind, key)` — 按 kind+key 取类
- `PluginRegistry.registered(kind)` — 列出某 kind 所有 key
- `PluginRegistry.clear(kind=None)` — 清空；**传 `kind` 只清该类**（测试用，避免误清内置插件）
- `PluginRegistry.discover(package, on_error=...)` — importlib 扫包触发注册（替换硬编码导入列表）

**消费方**：`parsers/plugins/`（Parser SPI）、`ai/platform_adapters/factory.py`（平台适配器）。**约定**：包内模块**禁止**在 import 时执行文件写入副作用（见 P0-4 事故）。

## knowledge_guard.py

- `KnowledgeFreshnessGuard.decision(category)` 在 variant 模式 fail closed；freshness 缺失、不可用或签名不匹配时禁止读取
- `runtime_knowledge_decision()` 仅为无 variant 身份的 legacy 模式保留兼容放行
- scope 支持 `conditions:RCTA` / `source_docs:RCTA` / `code_knowledge:RCTA`，同一项目不同功能独立更新
- `publish_knowledge_categories()` 原子写入 variant memory 下的 `knowledge_manifest.json`；只调用成功的能力模块可以发布
- manifest 记录当前输入签名而非复制知识内容；commit/hash、DBC、需求或 identity 变化会自动使命中失效
- Dream 发布前比较每个 scope 刷新前后的输入签名；运行期间输入发生变化的 scope 不发布

## workspace.py 关键 API

| API | 职责 |
|-----|------|
| `Workspace(name, workspaces_dir)` | 打开 `.workspaces/<name>`，读取本地 `config.yaml` 并解析 `inherits_from` |
| `Workspace.from_variant(variant, workspaces_dir)` | 从 Variant 或 variant_id 派生 workspace 目录名（`/`、`\` 转 `_`） |
| `Workspace.get_config()` | 递归合并 base + local 配置，local 标量/list 覆盖 base，嵌套 dict 保留未覆盖字段 |
| `Workspace.get_dbc_files()` | 返回 base DBC + local `dbc/*.dbc`，用于 Core+COEM 叠加 |
| `Workspace.get_source_paths()` | 返回源码扫描优先级：local `coem/` 优先；缺失时 fallback 到 `common/`/`code/`；再追加 base 路径 |
| `Workspace.get_requirements_schema()` | 合并 `requirements/*.yaml`，local 按 `feature`/`function` 覆盖 base |

## materials.py 关键 API

| API | 职责 |
|-----|------|
| `MaterialRegistry.for_variant(project_root, variant_id)` | 打开 `materials/<variant_safe>/registry.json` |
| `MaterialRegistry.register(...)` | 注册材料文件，计算 SHA256 与 `mat-xxxxxxxxxxxx` ID |
| `StructuredRequirementSet.for_variant(project_root, variant_id)` | 读取或创建 `requirements.json` |
| `render_material_summary(project_root, variant_id, max_materials=8, max_requirements=12, max_chars=4000)` | 生成诊断可注入的限长摘要 |

`render_material_summary()` 返回 dict，关键字段：

- `variant_id`
- `material_count`
- `authoritative_count`
- `requirement_count`
- `critical_requirement_count`
- `material_ids`
- `requirement_ids`
- `prompt_text`

空 registry 时 `prompt_text == ""`；调用方应只在非空时注入专家 prompt。

## freshness.py 关键 API

| API | 职责 |
|-----|------|
| `compute_variant_fingerprint(config, project_root)` | 计算当前 variant 的确定性指纹：`variant_id`、`source_root`、git branch/commit（best-effort）、`key_source_files_hash`、`source_scope_hash`、`constants_source_hash`、`dbc_hash`、`requirements_hash`、`config_identity_hash` |
| `load_freshness_state(memory_dir_or_workspace_dir)` | 读取 `freshness_state.json`；兼容直接传 memory 目录或 workspace 目录 |
| `write_freshness_state(memory_dir_or_workspace_dir, fingerprint)` | 在 variant memory 下写入 `freshness_state.json`，记录 `updated_at` 与 `fingerprint` |
| `compare_freshness(previous, current)` | 输出 `code_changed` / `constants_changed` / `dbc_changed` / `requirements_changed` / `identity_changed` / `any_changed` / `changed_keys` |

### freshness 指纹约定

- `source_scope_hash` 只扫描 variant `scope.include_globs` 命中的 `.c/.h/.cpp/.hpp`，并应用 `exclude_globs`
- `constants_source_hash` 只聚合已命中的参数/条件关键文件（如 `paraDefine.h`、`dotCalibDefine.h`、`adasFunc.c`）
- requirements 目录只纳入 `*.yaml|yml|md|txt|pdf|docx|xlsx`，单文件最多读取 5 MB
- 该模块只做**只读指纹计算**，不 watch 文件，也不 checkout/fetch/pull git

## Review 关注点

- 权威材料 (`category=authoritative`) 优先级高于 learned knowledge。
- 材料摘要必须确定性排序、限长、无 LLM 依赖。
- 修改材料/需求 schema 时，同步更新 Orchestrator 的 requirement trace 和相关测试。
- freshness manifest 仅表示“当前输入是否漂移”；写 state 不代表已经自动修复或重建全部缓存，调用方需在 prewarm/dream 成功后再更新 state。
