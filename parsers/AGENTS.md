# parsers/ 模块实现说明

> 用于「需求 ↔ 实现」review。AI 编辑 parsers/ 目录文件时参考本文档。

---

## 模块概览

| 文件 | 定位 |
|------|------|
| `__init__.py` | 聚合导出：BagParser, BlfParser, DbcLoader, FrameStore, TimeSync, load_case_data, CaseLoadResult |
| `plugins/` | **ParserPlugin SPI**：`base.py`（ParserContext/ParserResult/ParserPlugin 抽象）+ `bag_plugin.py`/`blf_plugin.py`/`mf4_plugin.py`（经 `PluginRegistry.register("parser", ext)` 注册） |
| `bag_parser.py` | ROS Bag v1 读取 + 手工反序列化 wfAutosarData / wfObjectMsg / egoCarInfo / UInt8MultiArray |
| `blf_parser.py` | BLF 读取 + 可选 DBC 解码 CAN 帧 |
| `dbc_loader.py` | cantools 加载多 DBC，同 frame_id 先到者优先 |
| `frame_store.py` | SQLite 内存数据库，统一存储 bag/can/radar_objects/radar_debug/warning_events |
| `time_sync.py` | BAG (ns) 与 BLF (epoch sec) 时间对齐 |
| `case_loader.py` | 一键加载案例目录 → FrameStore + 元数据 + TimeSync + warning_events（blf/mf4 走 ParserRegistry，bag 保留 legacy 深解析） |

---

## ParserPlugin SPI（parsers/plugins/）

新数据格式通过实现 `ParserPlugin` 子类 + `@PluginRegistry.register("parser", ".ext")` 接入，**零改 `case_loader`**：

- `ParserPlugin.extension` — 处理的文件扩展名（如 `.bag`）
- `ParserPlugin.load(path, store, ctx) -> ParserResult` — 解析并写 store；**不得对畸形输入抛异常**，应降级并在 `ParserResult.warnings` 记录
- `ParserContext`：config / project_root / workspace / dbc / on_status 共享上下文
- `case_loader` 优先查 `get_parser_plugin(ext)`；未注册格式走旧 glob fallback

---

## bag_parser.py

### 公开接口

| 签名 | 行号 |
|------|------|
| `@dataclass BagFrame` | 69-76 |
| `BagParser.__init__(self, bag_path: str \| Path)` | 99-102 |
| `BagParser.get_metadata(self) -> dict` | 105-127 |
| `BagParser.iter_frames(self, topics=None, skip_images=True) -> Iterator[BagFrame]` | 129-160 |
| `BagParser.get_warning_timeline(self) -> list[dict]` | 580-590 |

### BagFrame.fields 按消息类型

| 类型 | 关键字段 |
|------|---------|
| 未知/异常 | `raw_hex` (最多 64 字节) |
| `UInt8MultiArray` | `warning_bytes`, `radar_id`, `BSD_L`...`FCTB_R`, `any_warning_active` (需 ≥16 字节) |
| `egoCarInfo` | Header + `_EGO_FIELDS` + `trc_0..3_*` (每组 9 字段) |
| `wfObjectMsg` | Header + objects 数组 (ID, obj_class, distX/Y, velAbsX/Y, fTTC, 8 个 warningFlag) |
| `wfAutosarData` | Header + `outputData` → objects (36B struct) + debug (144B 尾部) |

### 模块级常量

| 常量 | 行号 | 含义 |
|------|------|------|
| `TOPIC_RADAR_ID` | 28-37 | topic → radar_id 映射 |
| `WARNING_SIGNAL_MAP` | 40-45 | 字节索引 → 功能名 |
| `_OBJ_STRUCT_SIZE=36`, `_DEBUG_INFO_SIZE=144` | 19-25 | wfAutosar outputData 布局 |
| `_WFSOBJ_SIZE=185` | 47-66 | wfObjectMsg 单目标序列化 |

### 魔数与容错

- 对象过滤: wfa `abs(dist) > 50` (厘米) 或 warning 非零或 `life_cycle > 3` (477-481)
- wfObjectMsg 过滤: `abs(distX/distY) > 0.01` 或 warning 非零 (380-386)
- ego/object 最短 raw `< 30` 字节早退 (272-273, 316-317, 400-401)
- 解码异常: `except Exception: pass` → `raw_hex` (182-184)

### Review 关注点

- `TOPIC_RADAR_ID` / `TOPIC_ALIASES` 与实车 topic 漂移 → `radar_id=0`
- `_OBJ_STRUCT_FMT` / `_WFSOBJ_FMT` 与固件不同步会错字段
- wfa 与 wfObjectMsg 距离单位不一致 (厘米÷100 vs 已是 float 米)
- 宽泛异常吞错静默

---

## blf_parser.py

### 公开接口

| 签名 | 行号 |
|------|------|
| `@dataclass CanFrame` | 13-26 |
| `BlfParser.__init__(self, blf_path, dbc_loader=None)` | 33-37 |
| `BlfParser.get_metadata(self) -> dict` | 40-74 |
| `BlfParser.iter_frames(self, can_ids=None, decode=True) -> Iterator[CanFrame]` | 76-117 |
| `BlfParser.get_signal_timeline(self, can_id, signal_names=None) -> list[dict]` | 119-141 |

### Review 关注点

- `get_metadata` 全文件扫描，大 BLF 成本高
- 无 DBC 或 `decode=False` 时仅有原始 hex
- `channel` 缺省变 0，可能与真实 ch1 混淆
- ISO 时间用本地 `fromtimestamp`，跨时区需注意

---

## dbc_loader.py

### 公开接口

| 签名 | 行号 |
|------|------|
| `DbcLoader.__init__(self, dbc_paths, base_dir=None)` | 19-58 |
| `DbcLoader.known_ids -> set[int]` | 60-62 |
| `DbcLoader.get_message_name(self, can_id) -> Optional[str]` | 64-66 |
| `DbcLoader.get_signal_names(self, can_id) -> list[str]` | 68-72 |
| `DbcLoader.decode(self, can_id, data) -> Optional[dict]` | 74-88 |
| `DbcLoader.get_message_info(self, can_id) -> Optional[dict]` | 90-116 |
| `DbcLoader.get_all_messages_summary(self) -> list[dict]` | 118-130 |

### DBC 路由规则

- 同一 `frame_id` **先加载者优先**，冲突记录到 `conflicts` 列表
- `decode` 失败时截断到 `msg.length` 再试 (82-88)
- 加载顺序 = 配置中 `dbc_files` 列表顺序

---

## frame_store.py

### SQLite 表结构

**`bag_frames`** (24-33)
- `id` PK, `timestamp_ns` INT, `timestamp_sec` REAL, `topic` TEXT, `msg_type`, `data_size`, `fields_json`

**`can_frames`** (35-46)
- `id` PK, `timestamp` REAL, `datetime_str`, `channel`, `can_id` INT, `can_id_hex`, `dlc`, `message_name`, `raw_hex`, `signals_json`

**`radar_objects`** (50-75)
- `id` PK, `timestamp_ns`, `radar_id`, `frame_id`, `obj_id`, `obj_class`, `life_cycle`, `dist_x/y`, `vel_x/y`, `ttc`, `ddci`, `bsd_flag`..`fctb_flag`, `source` DEFAULT 'wfa'

**`radar_debug`** (78-105)
- `id` PK, `timestamp_ns`, `radar_id`, ego 字段, `bsd_enable`..`fctb_enable`, bld 字段

**`warning_events`** (108-121)
- `id` PK, `func_name`, `direction`, `radar_id`, `start_ns`, `end_ns`, `duration_ms`, `trigger_source`, `associated_obj_id`, `max_ttc`, `min_dist`

### 索引 (124-142)

- UNIQUE: `idx_bag_dedup(timestamp_ns, topic)`, `idx_can_dedup(timestamp, can_id, channel)`
- UNIQUE: `idx_ro_dedup(timestamp_ns, radar_id, obj_id, source)`, `idx_rd_dedup(timestamp_ns, radar_id)`
- 普通索引: bag_ts, bag_topic, can_ts, can_id, can_name, can_id_ts, ro_ts, rd_ts, we_func, we_ts

### 公开查询接口

| 签名 | 行号 |
|------|------|
| `query_objects_in_window(time_start_ns, time_end_ns, radar_id=None)` | 247-257 |
| `query_objects_with_warning(func_name)` | 259-270 |
| `get_object_trajectory(obj_id, radar_id)` | 272-275 |
| `query_debug_in_window(time_start_ns, time_end_ns, radar_id=None)` | 318-328 |
| `query_warning_events(func_name=None)` | 351-361 |
| `query_bag_by_topic(topic, time_start_ns=None, time_end_ns=None)` | 363-376 |
| `query_can_by_id(can_id, time_start=None, time_end=None)` | 378-391 |
| `query_can_by_name(message_name)` | 393-398 |
| `query_signal_timeline(can_id, signal_name)` | 400-415 |
| `get_bag_topics()` | 417-421 |
| `get_can_ids()` | 423-427 |
| `get_signal_inventory(sample_per_id=3)` | 429-458 |
| `get_time_range()` | 460-470 |

### Review 关注点

- `INSERT OR IGNORE` 依赖 UNIQUE 索引，重复静默丢弃
- JSON 字段无法 SQL 内嵌索引，复杂筛选需应用层
- `warning_events.insert` 非 `OR IGNORE`，重复运行可能重复插入
- `_row_to_dict` 将 `fields_json`/`signals_json` 反序列化为 dict (472-480)

---

## time_sync.py

### 公开接口

| 签名 | 行号 |
|------|------|
| `TimeSync.__init__(self, bag_start_ns=None, bag_end_ns=None, blf_start_sec=None, blf_end_sec=None, manual_offset_sec=None)` | 16-35 |
| `offset_sec -> float` | 37-40 |
| `bag_ns_to_blf_sec(bag_ns) -> float` | 42-44 |
| `blf_sec_to_bag_ns(blf_sec) -> int` | 46-48 |
| `bag_ns_to_relative_sec(bag_ns) -> float` | 50-54 |
| `get_overlap_range() -> Optional[tuple[float, float]]` | 62-78 |

### 对齐算法

1. 有 `manual_offset_sec` → 直接用
2. 有 bag_start_ns 和 blf_start_sec → `offset = blf_start - bag_start/1e9`
3. 否则 `offset = 0.0`

---

## case_loader.py

### 公开接口

| 签名 | 行号 |
|------|------|
| `class CaseLoadResult` (slots: store, bag_meta, blf_meta, sync, dbc) | 40-49 |
| `load_case_data(case_dir, config, project_root, on_status=None, workspace=None) -> CaseLoadResult` | 59-238 |

### 加载流程

1. 若传入 `workspace`，先取 `workspace.get_dbc_files()`，再追加 `config["paths"]["dbc_files"]` 作为 fallback，按顺序建 `DbcLoader`（workspace 优先，重复路径去重）
2. 每个 `.bag` → BagParser → iter_frames → insert_bag_frame; wfAutosarData/wfObjectMsg → obj_rows/dbg_rows (79-156)
3. `bulk_insert_radar_objects` + `bulk_insert_radar_debug` (158-164)
4. 每个 `.blf` → BlfParser → bulk_insert_can (166-171)
5. 合并元数据，构造 TimeSync (176-188)
6. `_build_warning_events` — 500ms 间隙切分 (190-191)

### warning_events 构造

- `_GAP_NS = 0.5 * 1e9` (500ms)
- 按功能 `_FLAG_COL_MAP` 查 `radar_objects` 非零行
- 按 `(radar_id, obj_id, timestamp_ns)` 排序，间隔 > 500ms 或键变化则 flush
- `min_dist` 哨兵 999.0，flush 时 ≥999 则置 None

### Review 关注点

- bag 逐帧 insert_bag_frame 非 bulk，大 bag 性能问题
- 仅 `glob("*.bag")` / `glob("*.blf")`，无递归子目录
- workspace DBC 仅影响 `DbcLoader` 输入顺序；空 workspace / 缺失 DBC 时仍退化到 legacy config 或无解码
- warning_events 仅来自 `radar_objects` 标志位，不含 `warning_status_raw`

---

## msg_defs/

### canfd_sgu_pub.py

ROS1 节点：通过 CAN-FD 上的 XCP 读 ECU 内存，发布 `egoCarInfo`。与 `bag_parser._decode_ego_car_info` 字段布局同源。

- `BASE_SIGNAL_SPECS` + `TRC_OUT_SIGNAL_TEMPLATES` × 4 组 = `SIGNAL_SPECS`
- A2L 路径默认 `../config/CR60Light.A2L`
- XCP ID: left_tx=0x0F3, left_rx=0x6F3, right_tx=0x0F2, right_rx=0x6F2
- 发布频率默认 15 Hz

### egoCarInfo.msg

定义 `arbe_msgs/egoCarInfo` 全部字段 (69 字段)：Header + gear/spd/acc/yaw + 功能 state/enable + 门状态 + warning + trc_0..3 × 9 字段。
