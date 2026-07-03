# core/ 模块实现说明

`core/` 承载身份、材料、诊断包等可审计模型，供 CLI、Orchestrator、Harness 共享。

## 模块概览

| 文件 | 定位 |
|------|------|
| `identity.py` | PlatformFamily / Codebase / Variant / PackageProfile / Snapshot 等身份模型 |
| `materials.py` | MaterialRegistry / StructuredRequirementSet / RequirementSpec / 材料摘要渲染 |
| `diagnosis_bundle.py` | DiagnosisBundle、Evidence、CodeLocation、结论等级与结构化诊断产物 |
| `snapshot_store.py` | Snapshot 文件存储与加载 |

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

## Review 关注点

- 权威材料 (`category=authoritative`) 优先级高于 learned knowledge。
- 材料摘要必须确定性排序、限长、无 LLM 依赖。
- 修改材料/需求 schema 时，同步更新 Orchestrator 的 requirement trace 和相关测试。
