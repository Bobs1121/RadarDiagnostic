# radarAnalyze 代码实现文档

> **用途**：本文档作为「需求 ↔ 实现」review 的基准参考。后续 AI 将对照本文档 review 代码是否有偏差。
>
> **生成日期**：2026-04-18 19:55
>
> **项目路径**：`D:\RamboStar\idea\radarAnalyze`

---

## 目录

| 章节 | 涵盖模块 |
|------|----------|
| 第一章 | parsers/（BagParser, BlfParser, DbcLoader, FrameStore, TimeSync, CaseLoader）+ msg_defs/ |
| 第二章 | ai/orchestrator.py — 10+ 步诊断管线编排 |
| 第三章 | ai/frame_analyzer, test_window_detector, temporal_analyzer, parameter_analyzer, data_probe, problem_classifier |
| 第四章 | ai/signal_mapper, condition_extractor, causal_aligner, variable_query_planner |
| 第五章 | ai/expert_panel, data_query_engine, problem_classifier（补充视角） |
| 第六章 | ai/code_learner, tpe, pattern_extractor, visualizer |
| 第七章 | memory/memory_system（L1-L6）, memory/auto_dream |
| 第八章 | ai/model_router, context_budget, utils, __init__; scripts/; tools/; tests/; source_docs/ 文件 schema; .env/.gitignore |
| 附录 | 文档维护规则 |

---



================================================================================

# 第一章 数据解析层（parsers/ + msg_defs/）

说明：`msg_defs/canfd_sgu_pub.py` 在磁盘上的内容即为已读取的 XCP/egoCarInfo 节点实现（与文件名不完全一致，下文按实际代码描述）。

---

# radarAnalyze 数据解析层 — 代码实现说明

## 模块 0：`parsers/__init__.py`

### 定位
- 聚合导出解析与时间同步相关符号，供上层 `from parsers import ...` 使用。

### 公开 API（`parsers/__init__.py:1-6`）
- 无独立函数；导出：`BagParser`、`BlfParser`、`DbcLoader`、`FrameStore`、`TimeSync`、`load_case_data`、`CaseLoadResult`。

### 关键数据结构
- 无；仅为 re-export。

### 处理流程
- 无运行时逻辑。

### 外部依赖
- 同各子模块（见下文）。

### 隐藏假设 / 边界
- 导出列表变更即影响全项目 import 面。

### Review 关注点
- 新增解析类时是否应在此注册导出，避免上层散落路径 import。

---

## 模块 1：`parsers/bag_parser.py`

### 定位
- ROS Bag v1 读取与**按消息类型手工反序列化**：`wfAutosarData`（含 `outputData` 深解析）、`wfObjectMsg`（`wfSObj` 数组）、`egoCarInfo`、`std_msgs/UInt8MultiArray`（`warning_status_raw`）。未匹配类型时退回 `raw_hex` 预览。
- 依赖 `rosbags.rosbag1.Reader`。

### 公开 API / 类 / 函数签名（含 `文件:行号`）

**模块级常量 / 映射**
- `TOPIC_RADAR_ID`：`bag_parser.py:28-37`
- `WARNING_SIGNAL_MAP`：`bag_parser.py:40-45`

**`@dataclass BagFrame`**（`bag_parser.py:69-76`）
- 字段：`timestamp_ns: int`，`topic: str`，`msg_type: str`，`data_size: int`，`raw_bytes: bytes`，`fields: dict`（默认 `default_factory=dict`）

**`class BagParser`**
- `def __init__(self, bag_path: str | Path)` — `bag_parser.py:99-102`
- `def get_metadata(self) -> dict` — `bag_parser.py:105-127`
- `def iter_frames(self, topics: Optional[list[str]] = None, skip_images: bool = True) -> Iterator[BagFrame]` — `bag_parser.py:129-160`
- `def get_warning_timeline(self) -> list[dict]` — `bag_parser.py:580-590`

（以下为首下划线，属内部实现，供流程说明：` _normalize_msgtype`、` _decode_fields`、` _decode_uint8_multi_array`、` _decode_ego_car_info`、` _decode_object_msg`、` _decode_autosar_data`、` _parse_wfa_objects`、` _parse_wfa_debug`。）

### 关键数据结构 / 返回值字段

**`get_metadata()` 返回 dict**（`bag_parser.py:117-126`）
- `file`：bag 文件名  
- `size_mb`：`stat().st_size / 1024/1024`  
- `duration_sec`：`reader.duration / 1e9`  
- `start_ns` / `end_ns`：`reader.start_time` / `reader.end_time`  
- `message_count`、`topic_count`  
- `topics`：`{topic_name: {msg_type, msg_count, alias}}`，`alias` 来自 `TOPIC_ALIASES` 或原 topic  

**`BagFrame.fields`（按类型）**

1. **未知 / 解码异常**（`bag_parser.py:182-184`）：`{"raw_hex": str}`（最多 64 字节十六进制，空格分隔）

2. **`std_msgs/msg/UInt8MultiArray`**（`bag_parser.py:186-218`）  
   - `warning_bytes`、`warning_hex`、`byte_count`  
   - 若 `len(data_bytes) >= 16`：`radar_id`，`BSD_L`…`FCTB_R`（索引 1–15 对应 `WARNING_SIGNAL_MAP`），`any_warning_active`  

3. **`arbe_msgs/msg/egoCarInfo`**（`bag_parser.py:269-308`）  
   - Header：`seq`、`stamp_sec`、`stamp_nsec`、`frame_id`（UTF-8，`errors="replace"`）  
   - `_EGO_FIELDS` 所列名（`actual_gear`…`fctb_enable_capture`）  
   - `trc_0_*` … `trc_3_*`：每组 `_TRC_FIELDS` 9 个字段  

4. **`arbe_msgs/msg/wfObjectMsg`**（`bag_parser.py:310-390`）  
   - Header 同上；`object_count`；`objects`：每项含 `ID`、`obj_class`、`age`、`objID`、`distX`、`distY`、`velAbsX`、`velAbsY`、`fTTC`、`fDDCI`、8 个 `obj*WarningFlag`、`pos_x`、`pos_y`、`vel_x`、`vel_y`、`Rng`、`Spd`  
   - `active_object_count`：过滤后对象数（见魔数）  

5. **`arbe_msgs/msg/wfAutosarData`**（`bag_parser.py:392-458`）  
   - Header；`wfa_frame_id`、`lgu_num`、`sgu_num`；跳过 `uintData`、`floatData` 数组；`output_data` → `payload_size`  
   - `radar_id`：`TOPIC_RADAR_ID.get(topic, 0)`  
   - 若有对象：`objects`、`active_object_count`  
   - 若有 debug：`debug_info`  

**`_parse_wfa_objects` 单对象 dict**（`bag_parser.py:485-507`）  
- `obj_id`、`obj_class`、`life_cycle`、`dist_x/dist_y/vel_*`（米）、`ttc`、`ddci`、`length`、`width`、`bsd_flag`…`fctb_flag`（int）  

**`_parse_wfa_debug` 返回**（`bag_parser.py:510-578`）  
- `ego`：`actual_spd`、`yaw_rate`、`lat_accel`、`long_accel`、多个 uint8 状态/有效位、`steer_angle`、四轮速、`mileage` 等（float 四舍五入 4 位）  
- `calibration`：`egoCarSpdCoef`、`finalAziResult`、`finalEleResult`  
- `adas_enables`：`bsd`…`user_define`（bool）  
- `bld`：`LGUDeleteNum`、`noDymObjFlg`、`noObjFlg`、`bld_warning_flag`、`bld_percent`、`bld_score`  

**`get_warning_timeline()`**（`bag_parser.py:583-589`）  
- 每项：`timestamp_ns`、`timestamp_sec`，再 `update(frame.fields)`  

### 处理流程步骤
1. `Reader` 打开 bag；`iter_frames` 遍历 `reader.messages()`。  
2. 可选跳过相机 topic；可选按 `topics` 过滤。  
3. `_normalize_msgtype` 将 `pkg/Type` 规范为 `pkg/msg/Type`。  
4. `_decode_fields` 按类型分支；失败吞异常返回 `raw_hex`。  
5. `wfAutosarData`：跳过 ROS 数组头，取 `outputData`，对象区从偏移 8 起按 36 字节 struct 解析；尾部 144 字节为 debug。  
6. `wfObjectMsg`：`uint32` 数量 + 每项 `_WFSOBJ_SIZE` 字节 unpack。  

### 外部依赖
- **第三方**：`rosbags.rosbag1.Reader`、`struct`、`math`（文件 import 了 `math` 但未在片段内使用，以实际文件为准：`bag_parser.py:8` 有 import）  
- **项目内**：无  

### 魔数 / 默认阈值 / 容错

| 位置 | 值 | 含义 |
|------|-----|------|
| `bag_parser.py:19-25` | `_OBJ_TRANS_OFFSET=8`，`_OBJ_STRUCT_SIZE=36`，`_FIXED_LENGTH=728`，`_DEBUG_INFO_SIZE=144`，`_DEBUG_INFO_OFFSET=584` | wfAutosar `outputData` 布局 |
| `bag_parser.py:21` | `_OBJ_STRUCT_FMT` | 小端 struct |
| `bag_parser.py:22-23` | `_MAX_OBJ_COUNT=68`，`_FIXED_LENGTH` | 对象数上限 / 固定总长 |
| `bag_parser.py:47-66` | `_WFSOBJ_SIZE=185`，`_WFSOBJ_FMT` | 单目标序列化 |
| `wfObjectMsg` 过滤 | `abs(distX/distY) > 0.01` 或 warning 字节非零 | `bag_parser.py:380-386` |
| `wfa` 对象过滤 | `abs(dist_x/dist_y) > 50`（注释：厘米，>0.5m）或任 warning 非零或 `life_cycle > 3` | `bag_parser.py:477-481` |
| `ego` / `object` 最短 raw | `< 30` 字节则早退 | `bag_parser.py:272-273`、`316-317`、`400-401` |
| `UInt8MultiArray` | 语义解码需 `>= 16` 字节 | `bag_parser.py:212-217` |
| 解码异常 | `except Exception: pass` → `raw_hex` | `bag_parser.py:182-184` |

### BAG topic 名（代码中显式出现）
- **雷达 ID 映射**（`TOPIC_RADAR_ID` / `TOPIC_ALIASES`）：`/wf/corner_radar/lgu_data_{1-4}`、`/wf/objectlist_{1-4}`、`/wf/ego_car_info/front_left|front_right/parsed`、`/corner_radar/warning_status_raw`、`/cv_camera_0|2/image_raw/compressed`（`bag_parser.py:28-37`、`83-97`）  
- **`get_warning_timeline` 固定 topic**：`/corner_radar/warning_status_raw`（`bag_parser.py:583`）  

### 隐藏假设 / 边界条件 / 错误处理
- Bag 不存在：`FileNotFoundError`（`bag_parser.py:101-102`）。  
- ROS1 序列化布局与 `egoCarInfo.msg`、内部 C struct 强绑定；`frame_id` 为 ROS string（4 字节长度 + 数据）。  
- `wfAutosarData` 中 `bytelength`、`padding` 等字段 unpack 后未强校验与 `output_len` 一致性。  
- 图像 topic 默认跳过以换性能。  

### Review 关注点
- `TOPIC_RADAR_ID` / `TOPIC_ALIASES` 与实车录制 topic 漂移即导致 `radar_id=0` 或别名缺失。  
- `_OBJ_STRUCT_FMT` / `_WFSOBJ_FMT` 与固件/消息定义不同步会直接错字段。  
- 宽泛 `except Exception: pass` 会静默丢解码错误，仅见 `raw_hex`。  
- `wfa` 与 `wfObjectMsg` 对距离单位处理不一致（厘米÷100 vs 已是 float 米）。  

---

## 模块 2：`parsers/blf_parser.py`

### 定位
- 使用 `python-can` 的 `BLFReader` 遍历帧；可选 `DbcLoader` 按 CAN ID 解码信号；产出 `CanFrame` 迭代器或按信号时间线。

### 公开 API / 类 / 函数签名

**`@dataclass CanFrame`**（`blf_parser.py:13-26`）  
- `timestamp: float`，`datetime_str: str`，`channel: int`，`can_id: int`，`can_id_hex: str`，`dlc: int`，`is_extended: bool`，`is_fd: bool`，`raw_data: bytes`，`raw_hex: str`，`message_name: Optional[str] = None`，`signals: dict = field(default_factory=dict)`

**`class BlfParser`**
- `def __init__(self, blf_path: str | Path, dbc_loader: Optional[DbcLoader] = None)` — `blf_parser.py:33-37`
- `def get_metadata(self) -> dict` — `blf_parser.py:40-74`
- `def iter_frames(self, can_ids: Optional[set[int]] = None, decode: bool = True) -> Iterator[CanFrame]` — `blf_parser.py:76-117`
- `def get_signal_timeline(self, can_id: int, signal_names: Optional[list[str]] = None) -> list[dict]` — `blf_parser.py:119-141`

### 关键数据结构 / 返回值字段

**`get_metadata()`**（`blf_parser.py:60-73`）  
- `file`、`size_mb`、`message_count`、`duration_sec`（末帧−首帧时间戳差）  
- `start_time` / `end_time`：ISO 字符串（`datetime.fromtimestamp`）  
- `unique_can_ids`、`channels`（channel→计数）  
- `top_ids`：出现次数最多的 20 个 `can_id`（`0x` 十六进制 + `count`）  

**`get_signal_timeline` 每条**（`blf_parser.py:132-140`）  
- `timestamp`、`datetime`；若指定 `signal_names` 则只含这些键，否则 `frame.signals` 全量  

### 处理流程步骤
1. `BLFReader` 顺序读 `msg`。  
2. 可选按 `can_ids` 过滤。  
3. `decode and self.dbc`：`get_message_name`、`dbc.decode`。  
4. 组装 `CanFrame`；`channel` 为 `msg.channel or 0`。  

### 外部依赖
- **第三方**：`can`（`BLFReader`）、`datetime`  
- **项目内**：`DbcLoader`（`blf_parser.py:10`）  

### BLF「消息 ID」说明
- 代码**不硬编码** CAN ID；仲裁 ID 来自 BLF 内每条 `msg.arbitration_id`，与 DBC 中 `frame_id` 对应由 `DbcLoader` 维护。  
- `get_metadata` 统计的是**原始 `arbitration_id` 整数**（及十六进制展示）。  

### 魔数 / 容错
- `top_ids` 最多 **20** 条（`blf_parser.py:71`）。  
- 无 DBC 或 `decode=False`：`message_name=None`，`signals={}`。  

### 隐藏假设 / 边界
- `get_metadata` **全文件扫描**，大 BLF 成本高。  
- `duration_sec` 依赖首末帧时间戳；单帧或异常时间戳时可能为 0。  

### Review 关注点
- DBC 未加载时仅有原始 hex，无信号名。  
- `channel` 缺省变 0，可能与真实 ch1 混淆。  
- ISO 时间用本地 `fromtimestamp`，跨时区/夏令时需知悉。  

---

## 模块 3：`parsers/dbc_loader.py`

### 定位
- 用 `cantools` 加载多个 DBC；**同一 `frame_id` 先加载者优先**（冲突记录到 `conflicts`），实现多 DBC 并存时的 ID 路由。

### 公开 API / 类 / 函数签名

**`class DbcLoader`**
- `def __init__(self, dbc_paths: list[str | Path], base_dir: Optional[Path] = None)` — `dbc_loader.py:19-58`
- `@property def known_ids(self) -> set[int]` — `dbc_loader.py:60-62`
- `def get_message_name(self, can_id: int) -> Optional[str]` — `dbc_loader.py:64-66`
- `def get_signal_names(self, can_id: int) -> list[str]` — `dbc_loader.py:68-72`
- `def decode(self, can_id: int, data: bytes) -> Optional[dict]` — `dbc_loader.py:74-88`
- `def get_message_info(self, can_id: int) -> Optional[dict]` — `dbc_loader.py:90-116`
- `def get_all_messages_summary(self) -> list[dict]` — `dbc_loader.py:118-130`

### 关键数据结构 / 返回值字段

**`decode` 返回**  
- `Optional[dict]`：`{signal_name: physical_value}`；未知 ID → `None`（`dbc_loader.py:74-88`）  
- `decode_choices=False`（枚举显示物理值而非 choice 名）  

**`get_message_info`**（`dbc_loader.py:95-116`）  
- `name`、`frame_id`、`frame_id_hex`、`length`、`comment`  
- `signals`：每项 `name`、`start_bit`、`length`、`byte_order`、`scale`、`offset`、`min`、`max`、`unit`、`comment`  

**`get_all_messages_summary` 每项**（`dbc_loader.py:121-129`）  
- `can_id`、`can_id_hex`、`name`、`length`、`signal_count`、`signal_names`  

**`conflicts` 列表元素**（`dbc_loader.py:39-46`）  
- `frame_id`、`hex`、`kept_name`、`kept_dbc`、`skipped_name`、`skipped_dbc`  

### DBC 路由规则
- 遍历 `dbc_paths`；相对路径与 `base_dir` 拼接（`dbc_loader.py:27-29`）。  
- 每个 `msg.frame_id`：若已存在则**跳过新 DBC 定义**并记 conflict；否则注册 `_id_to_db`、`_id_to_msg`、`_id_to_dbc_name`（`dbc_loader.py:36-50`）。  
- `decode` 仅用**保留**的 `Message`（`dbc_loader.py:79-88`）。  

### 处理流程步骤
1. 逐路径 `cantools.database.load_file`。  
2. 合并消息表，冲突打印 `[INFO]`（`dbc_loader.py:54-58`）。  
3. `decode`：先全 `data`，失败则 `data[:msg.length]` 再试（`dbc_loader.py:82-88`）。  

### 外部依赖
- **第三方**：`cantools`  
- **项目内**：无  

### 魔数 / 容错
- 文件不存在：`print [WARN]` 跳过（`dbc_loader.py:30-32`）。  
- 加载异常：`print [WARN]`（`dbc_loader.py:51-52`）。  

### 隐藏假设 / 边界
- **加载顺序 = 配置中 `dbc_files` 顺序**；顺序变化会改变“谁赢得冲突”。  
- 打印到 stdout，非 logging。  

### Review 关注点
- 同 ID 不同报文在不同物理总线：依赖“先加载 DBC”业务约定，易与真实总线混淆。  
- `decode` 二次截断依赖 DBC `msg.length`，与 FD 实际 DLC 不符时仍可能失败。  

---

## 模块 4：`parsers/frame_store.py`

### 定位
- SQLite 持久化：`bag_frames`、`can_frames`、`radar_objects`、`radar_debug`、`warning_events`；JSON 存 bag `fields` 与 CAN `signals`；提供批量插入与查询。

### 公开 API / 类 / 函数签名

**`class FrameStore`**
- `def __init__(self, db_path: str | Path = ":memory:")` — `frame_store.py:15-19`
- `def insert_bag_frame(self, frame) -> None` — `frame_store.py:145-156`
- `def insert_can_frame(self, frame) -> None` — `frame_store.py:158-172`
- `def bulk_insert_bag(self, frames, batch_size: int = 1000) -> int` — `frame_store.py:174-191`
- `def bulk_insert_can(self, frames, batch_size: int = 1000) -> int` — `frame_store.py:193-211`
- `def bulk_insert_radar_objects(self, objects: list[dict], batch_size: int = 500) -> int` — `frame_store.py:215-245`
- `def query_objects_in_window(self, time_start_ns: int, time_end_ns: int, radar_id: Optional[int] = None) -> list[dict]` — `frame_store.py:247-257`
- `def query_objects_with_warning(self, func_name: str) -> list[dict]` — `frame_store.py:259-270`
- `def get_object_trajectory(self, obj_id: int, radar_id: int) -> list[dict]` — `frame_store.py:272-275`
- `def bulk_insert_radar_debug(self, records: list[dict], batch_size: int = 500) -> int` — `frame_store.py:279-316`
- `def query_debug_in_window(self, time_start_ns: int, time_end_ns: int, radar_id: Optional[int] = None) -> list[dict]` — `frame_store.py:318-328`
- `def insert_warning_events(self, events: list[dict]) -> int` — `frame_store.py:332-349`
- `def query_warning_events(self, func_name: Optional[str] = None) -> list[dict]` — `frame_store.py:351-361`
- `def query_bag_by_topic(self, topic: str, time_start_ns: Optional[int] = None, time_end_ns: Optional[int] = None) -> list[dict]` — `frame_store.py:363-376`
- `def query_can_by_id(self, can_id: int, time_start: Optional[float] = None, time_end: Optional[float] = None) -> list[dict]` — `frame_store.py:378-391`
- `def query_can_by_name(self, message_name: str) -> list[dict]` — `frame_store.py:393-398`
- `def query_signal_timeline(self, can_id: int, signal_name: str) -> list[dict]` — `frame_store.py:400-415`
- `def get_bag_topics(self) -> list[dict]` — `frame_store.py:417-421`
- `def get_can_ids(self) -> list[dict]` — `frame_store.py:423-427`
- `def get_signal_inventory(self, sample_per_id: int = 3) -> list[dict]` — `frame_store.py:429-458`
- `def get_time_range(self) -> dict` — `frame_store.py:460-470`
- `def close(self)` — `frame_store.py:482-483`

### SQLite schema（表、列、索引）

**`bag_frames`**（`frame_store.py:24-33`）  
- 列：`id` INTEGER PK AUTOINCREMENT，`timestamp_ns` INTEGER NOT NULL，`timestamp_sec` REAL NOT NULL，`topic` TEXT NOT NULL，`msg_type` TEXT，`data_size` INTEGER，`fields_json` TEXT  

**`can_frames`**（`frame_store.py:35-46`）  
- 列：`id` PK，`timestamp` REAL NOT NULL，`datetime_str` TEXT，`channel` INTEGER，`can_id` INTEGER NOT NULL，`can_id_hex` TEXT，`dlc` INTEGER，`message_name` TEXT，`raw_hex` TEXT，`signals_json` TEXT  

**`radar_objects`**（`frame_store.py:50-75`）  
- 列：`id` PK，`timestamp_ns` NOT NULL，`radar_id` NOT NULL，`frame_id` INTEGER，`obj_id` NOT NULL，`obj_class`、`life_cycle` INTEGER，`dist_x`…`ddci` REAL，`*_flag` INTEGER DEFAULT 0（bsd/lca/dow/rcw/rcta/rctb/fcta/fctb），`source` TEXT DEFAULT `'wfa'`  

**`radar_debug`**（`frame_store.py:78-105`）  
- 列：`id` PK，`timestamp_ns`、`radar_id` NOT NULL，`frame_id`，ego 相关 REAL/INTEGER，`bsd_enable`…`fctb_enable` INTEGER，`bld_warning_flag`、`bld_percent`、`bld_score`  

**`warning_events`**（`frame_store.py:108-121`）  
- 列：`id` PK，`func_name` NOT NULL，`direction` TEXT，`radar_id` INTEGER，`start_ns` NOT NULL，`end_ns` INTEGER，`duration_ms` REAL，`trigger_source` TEXT，`associated_obj_id` INTEGER，`max_ttc`、`min_dist` REAL  

**索引**（`frame_store.py:124-142`）  
- `idx_bag_ts`(`timestamp_ns`)，`idx_bag_topic`(`topic`)，`idx_can_ts`(`timestamp`)，`idx_can_id`(`can_id`)，`idx_can_name`(`message_name`)，`idx_can_id_ts`(`can_id`,`timestamp`)  
- UNIQUE：`idx_bag_dedup`(`timestamp_ns`,`topic`)，`idx_can_dedup`(`timestamp`,`can_id`,`channel`)  
- `idx_ro_ts`、`idx_ro_radar_ts`、`idx_ro_dedup` UNIQUE(`timestamp_ns`,`radar_id`,`obj_id`,`source`)  
- `idx_rd_ts`、`idx_rd_dedup` UNIQUE(`timestamp_ns`,`radar_id`)  
- `idx_we_func`(`func_name`)、`idx_we_ts`(`start_ns`)  

### `_row_to_dict` 查询结果键（`frame_store.py:472-480`）
- 将 `fields_json` → 解析为 `fields`（删除 `fields_json`）；`signals_json` → `signals`。  

### 魔数 / 默认
- `bulk_insert_bag` / `bulk_insert_can`：`batch_size=1000`（`frame_store.py:174`、`193`）  
- `bulk_insert_radar_objects` / `bulk_insert_radar_debug`：`batch_size=500`（`215`、`279`）  
- `get_signal_inventory`：`sample_per_id=3`（`429`）  

### 隐藏假设 / 边界
- `INSERT OR IGNORE` 依赖 UNIQUE 索引；重复 `(timestamp_ns,topic)` 等会被静默丢弃。  
- `query_objects_with_warning` 用 `col_map` 仅接受大写功能名键（内部 `.upper()`）（`frame_store.py:261-268`）。  

### Review 关注点
- JSON 字段无法 SQL 内嵌套索引；复杂筛选需应用层。  
- `warning_events.insert` 非 `OR IGNORE`，重复运行可能重复插入（取决于调用方）。  

---

## 模块 5：`parsers/time_sync.py`

### 定位
- Bag 时间（ROS 纳秒）与 BLF（Unix epoch 秒）对齐：**默认 offset = blf_start_sec − bag_start_sec**；可 `manual_offset_sec` 覆盖。

### 公开 API / 类 / 函数签名

**`class TimeSync`**
- `def __init__(self, bag_start_ns: Optional[int] = None, bag_end_ns: Optional[int] = None, blf_start_sec: Optional[float] = None, blf_end_sec: Optional[float] = None, manual_offset_sec: Optional[float] = None)` — `time_sync.py:16-35`
- `@property def offset_sec(self) -> float` — `time_sync.py:37-40`（注释：加到 bag 秒得到 blf 秒）  
- `def bag_ns_to_blf_sec(self, bag_ns: int) -> float` — `time_sync.py:42-44`  
- `def blf_sec_to_bag_ns(self, blf_sec: float) -> int` — `time_sync.py:46-48`（`round`）  
- `def bag_ns_to_relative_sec(self, bag_ns: int) -> float` — `time_sync.py:50-54`  
- `def blf_sec_to_relative_sec(self, blf_sec: float) -> float` — `time_sync.py:56-60`  
- `def get_overlap_range(self) -> Optional[tuple[float, float]]` — `time_sync.py:62-78`  
- `def summary(self) -> dict` — `time_sync.py:80-86`  

### 时间对齐算法（实际代码）
1. 若 `manual_offset_sec is not None`：` _offset_sec = manual_offset_sec`（`time_sync.py:29-30`）。  
2. 否则若 `bag_start_ns` 与 `blf_start_sec` 均有：` _offset_sec = blf_start_sec - bag_start_ns/1e9`（`time_sync.py:31-33`）。  
3. 否则：` _offset_sec = 0.0`（`time_sync.py:34-35`）。  
4. 转换：`blf_sec = bag_ns/1e9 + offset`；`bag_ns = round((blf_sec - offset)*1e9)`（`time_sync.py:42-48`）。  

**`get_overlap_range`**（`time_sync.py:67-78`）  
- 需四角齐全；将 bag 起止换到 blf 时间轴，`overlap_start/end` 取交集；若 `overlap_start >= overlap_end` 返回 `None`。  
- 返回值两分量均为**相对秒**：`(overlap_start - min(bag_start_blf, blf_start), overlap_end - min(...))`。  

**`summary()`**  
- `offset_sec`、`bag_duration_sec`、`blf_duration_sec`、`overlap`  

### 外部依赖
- 仅 typing。  

### 魔数
- `1e9` 纳秒换算（多处）。  

### Review 关注点
- 多段 bag/BLF 合并时 `case_loader` 用合并后的 `start_ns`/`end_time` 建 `TimeSync`，语义为“整体首尾对齐”，非逐文件。  
- `blf_sec_to_bag_ns` 使用 `round`，与浮点误差敏感场景需注意。  

---

## 模块 6：`parsers/case_loader.py`

### 定位
- 扫描 `case_dir` 下 `*.bag`、`*.blf`：bag 全量入 `bag_frames`；从 `wfAutosarData` / `wfObjectMsg` 抽取行写入 `radar_objects` 与 `radar_debug`；BLF DBC 解码入 `can_frames`；合并元数据并构造 `TimeSync`；从 `radar_objects` 用**500ms 间隙**切分 `warning_events`。

### 公开 API / 类 / 函数签名

**`class CaseLoadResult`**（`case_loader.py:40-49`）  
- `__slots__`：`store`、`bag_meta`、`blf_meta`、`sync`、`dbc`  
- `__init__(self)`：上述初始为 `None`（`store` 在 `load_case_data` 中赋值）  

**`def load_case_data(case_dir: Path, config: dict, project_root: Path, on_status=None) -> CaseLoadResult`** — `case_loader.py:52-193`  

### `load_case_data` 行为摘要
- `config["paths"].get("dbc_files", [])` 建 `DbcLoader`（`case_loader.py:70-71`）。  
- 每个 `.bag`：`BagParser` → `iter_frames` → `insert_bag_frame`；对 `_WFA_TOPICS` 填 `obj_rows`/`dbg_rows`；对 `_WFO_TOPICS` 仅 `obj_rows`（`case_loader.py:79-156`）。  
- `bulk_insert_radar_objects`、`bulk_insert_radar_debug`（`case_loader.py:158-164`）。  
- 每个 `.blf`：`BlfParser(..., decode=True)`，`bulk_insert_can(iter_frames(...))`（`case_loader.py:166-171`）。  
- 元数据 `_merge_metas`（`case_loader.py:173-174`）。  
- 若 bag+blf 元数据俱在：从 `blf_meta` ISO 时间解析 `timestamp` 建 `TimeSync`（`case_loader.py:176-188`）。  
- `_build_warning_events`（`case_loader.py:190-191`）。  

### `_WFA_TOPICS` / `_WFO_TOPICS`（`case_loader.py:20-31`）
- 与 `bag_parser.TOPIC_RADAR_ID` 键集合一致的前缀分组。  

### `warning_events` 构造（`case_loader.py:196-254`）
- `_GAP_NS = 0.5 * 1e9`（500ms）。  
- 按功能 `_FLAG_COL_MAP` 查 `radar_objects` 中非零行，按 `(radar_id, obj_id, timestamp_ns)` 排序。  
- 同键下若时间间隔 > `_GAP_NS` 或键变化则 flush 段。  
- 段内：`min_dist = min(abs(dist_x))`，`max_ttc` 取最大；`min_dist` 初值/哨兵 `999.0`，flush 时若仍 ≥999 则置 `None`（`case_loader.py:214-229`）。  
- 字段：`func_name`、`direction=None`、`radar_id`、`start_ns`、`end_ns`、`trigger_source="obj_flag"`、`associated_obj_id`、`max_ttc`、`min_dist`。  
- `insert_warning_events` 内 `duration_ms = (end_ns - start_ns)/1e6`（`frame_store.py:339`）。  

### 外部依赖
- `bag_parser`（含 `TOPIC_RADAR_ID`）、`blf_parser`、`dbc_loader`、`frame_store`、`time_sync`、`datetime`、`pathlib`。  

### 魔数
- `_GAP_NS`：500ms（`case_loader.py:198`）。  
- `seg_min_dist` 哨兵 999.0（`case_loader.py:214-229`）。  

### 隐藏假设 / 边界
- `FrameStore()` 默认内存库；进程结束即失（除非上层换路径）。  
- 仅 `glob("*.bag")` / `glob("*.blf")`，无递归子目录。  
- `wfo` 分支 `frame_id` 固定 0（`case_loader.py:134`）。  

### Review 关注点
- bag 逐帧 `insert_bag_frame` 非 bulk，大 bag 性能。  
- `TimeSync` 依赖 BLF `start_time`/`end_time` 字符串 ISO 解析，与 `BlfParser.get_metadata` 一致。  
- `warning_events` 仅来自 `radar_objects` 标志位，不含 `warning_status_raw` 字节流。  

---

## 模块 7：`msg_defs/canfd_sgu_pub.py`（实际内容：XCP 读内存发布 `egoCarInfo`）

### 定位
- ROS1 节点：经 Kvaser `canlib` 在 CAN-FD 上跑 XCP，按 A2L 中 `ECU_ADDRESS` 读测量量，填充 `arbe_msgs/egoCarInfo` 并发布。文件头注释为 “XCP over CAN-FD… publish to egoCarInfo topic”。**非** BLF/BAG 解析代码；与 `bag_parser._decode_ego_car_info` 字段布局同源（同一 `.msg`）。

### 公开 API / 模块级符号

**模块级**（`canfd_sgu_pub.py:23-79`）  
- `BASE_SIGNAL_SPECS`：tuple 列表 `(A2L名, ROS字段名, dtype)`  
- `TRC_OUT_SIGNAL_TEMPLATES`：9 个模板字段  
- `SIGNAL_SPECS`：`BASE` + 4×`TRC` 展开  

**`class EgoCarInfoNode`**
- `def __init__(self)` — `canfd_sgu_pub.py:82-154`
- `def load_a2l_file(self)` — `canfd_sgu_pub.py:157-166`
- `def get_ecu_address(self, symbol_name)` — `canfd_sgu_pub.py:168-179`
- `def send_can_frame(self, tx_id, data_bytes)` — `canfd_sgu_pub.py:229-236`
- `def send_xcp_command(self, cmd, is_left)` — `canfd_sgu_pub.py:238-240`
- `def send_and_wait(self, cmd, is_left, expect_pred, timeout_sec=0.2)` — `canfd_sgu_pub.py:242-248`
- `def build_read_memory_cmd(self, address)` — `canfd_sgu_pub.py:250-257`
- `def read_memory_chunked(self, addr, total_len, is_left)` — `canfd_sgu_pub.py:259-288`
- `def read_ego_signals(self)` — `canfd_sgu_pub.py:325-340`
- `def connect(self)` — `canfd_sgu_pub.py:343-362`
- `def run(self)` — `canfd_sgu_pub.py:364-371`

（`_open_can_bus_initial`、`_rx_worker`、`_read_f32` 等为内部实现。）

### 对应 ROS 消息与字段映射
- **消息类型**：`from arbe_msgs.msg import egoCarInfo`（`canfd_sgu_pub.py:18`）  
- **映射规则**：`SIGNAL_SPECS` 中每项 `(a2l_name, field_name, dtype)` → `setattr(msg, field_name, value)`（`canfd_sgu_pub.py:330-333`）  
- **dtype → 读法**：`f32` → 4 字节 `<f`；`u8` → 1 字节；`s8` → `struct.unpack("<b", ...)`（`canfd_sgu_pub.py:318-323`、`291-316`）  
- **BASE 字段 A2L 名**（节选，完整见 `canfd_sgu_pub.py:23-56`）：如 `g_egoCarAddInfo.actual_gear`→`actual_gear`，`fctaSystemState`→`fcta_system_state`，`PERInputUpdate.adasEnable.bFCTAEnable`→`fcta_enable` 等。  
- **TRC 字段**：`PEROutput.objInfo.trcOutData._{0-3}_.{velX|distX|...}` → `trc_{i}_{field_tail}`；注意模板中 `velX`→ROS 名 `vel_x`（`canfd_sgu_pub.py:58-79`），与 `egoCarInfo.msg` 中 `trc_*_vel_x` 一致。  

### ROS 参数默认值（魔数 / 阈值）
- `~a2l_path`：默认 `../config/CR60Light.A2L` 相对脚本目录（`canfd_sgu_pub.py:87-90`）  
- `~channel`：0；`~use_fd`：True；`~use_brs`：True；`~read_timeout_ms`：10（`canfd_sgu_pub.py:93-96`）  
- `~is_left`：False；`~topic_name`：`/wf/ego_car_info/parsed`（`canfd_sgu_pub.py:97-99`）——与 `BagParser.TOPIC_ALIASES` 中 `front_left/front_right/parsed` **路径不完全相同**（bag 侧别名是 `/wf/ego_car_info/front_left/parsed` 等）。  
- XCP ID：`xcp_left_tx_id=0x0F3`，`xcp_left_rx_id=0x6F3`，`xcp_right_tx_id=0x0F2`，`xcp_right_rx_id=0x6F2`（`canfd_sgu_pub.py:103-106`）  
- `~f5_max_len`：`max(1, min(param, 0x3F))`（`canfd_sgu_pub.py:109`）  
- RX 队列 `maxlen=512`（`canfd_sgu_pub.py:115-118`）  
- XCP：`SET_MTA` `0xF6`，读 `0xF5`；CONNECT `0xFF,0x00`；超时 0.2s（`canfd_sgu_pub.py:250-288`、`349-354`）  
- `connect` 重试 10 次（`canfd_sgu_pub.py:344-347`）  
- `run`：`~rate_hz` 默认 15（`canfd_sgu_pub.py:365`）  

### 处理流程步骤
1. 打开 CAN FD 总线、启动 RX 线程入队。  
2. 解析 A2L，正则取 `MEASUREMENT ... ECU_ADDRESS 0x...`。  
3. `connect` XCP。  
4. 循环：`read_ego_signals` 填 `egoCarInfo`（`header.stamp=now`，`frame_id=radar_label`），`publish`。  

### 外部依赖
- `rospy`、`canlib`（Kvaser）、`arbe_msgs`、`struct`、`threading` 等。  

### 隐藏假设 / 错误处理
- A2L 缺测量：地址 `None`，读返回 0 并 `logwarn`（`canfd_sgu_pub.py:137-145`、`291-307`）。  
- `egoCarInfo` 缺字段：`logerr_throttle`（`canfd_sgu_pub.py:333-338`）。  

### Review 关注点
- 本文件属**车载发布工具链**，与 `radarAnalyze` 解析层通过 **同一 `egoCarInfo` 布局**间接耦合；topic 命名与 bag 录制是否一致需业务确认。  
- `is_left` 决定 XCP 左右 ID 与默认 `radar_label`。  

---

## 模块 8：`msg_defs/egoCarInfo.msg`

### 字段定义（全文列出，`egoCarInfo.msg:1-69`）

```
std_msgs/Header header
uint8 actual_gear
float32 car_spd
float32 car_acc_xr
float32 yaw_rate
uint8 fcta_system_state
uint8 fctb_system_state
uint8 sys_power_mod
int8 fcta_enable
int8 fctb_enable
float32 steer_wheel_spd
uint8 acc_ped_pos_diag
uint8 trailer_sts
uint8 esp_diag_actv
float32 steer_angle
uint8 esp_fun
int8 get_rdafcta_error_status
int8 get_rdafctb_error_status
uint8 msr_actv
uint8 vdc_actv
uint8 ptc_actv
uint8 btc_actv
uint8 ptc_actv_ra
uint8 btc_actv_ra
uint8 msr_actv_ra
uint8 drv_door_sts
uint8 passenger_door_sts
uint8 lr_door_sts
uint8 rr_door_sts
uint8 left_fcta_warning
uint8 right_fcta_warning
int8 fcta_enable_capture
int8 fctb_enable_capture
int8 trc_0_obj_fcta_warning_flag
int8 trc_0_obj_fctb_warning_flag
float32 trc_0_dist_x
float32 trc_0_dist_y
float32 trc_0_vel_x
int8 trc_0_left_fcta_flag
int8 trc_0_right_fcta_flag
float32 trc_0_ttc
float32 trc_0_ddci
（trc_1 … trc_3 同上结构，共 4 组）
```

（`trc_1`～`trc_3` 字段名与 `trc_0` 平行，见源文件第 43–69 行。）

---

以上为基于当前仓库**实际代码全文**整理的“数据解析层”实现说明，可直接用于需求–实现对照 review。


================================================================================

# 第二章 诊断编排器（orchestrator.py）

以下为基于 `orchestrator.py` **全文逐段阅读**（第 1–1497 行，文件在此结束）整理的实现说明。文件中**未出现** `diagnosis_context`、`analysis_result` 等名称；贯穿流程的是 `func_info`、`classification`、`evidence`、`conditions`、`panel_result` 等对象，第 5 节按实际变量说明。

---

# `orchestrator.py` 实现说明（诊断编排器）

## 1. 类/模块级概览

### 1.1 模块定位与文档字符串

- 文件头说明：基于 Qwen3.5 的任务编排器，负责规划、分发与协调分析；用户只需提供问题与预期结果（V2：窗口检测 + 条件提取管线）。见 ```1:7:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```。
- 导入：`ModelRouter`、`CodeLearner`、`FrameAnalyzer`、`ExpertPanel`、`TestWindowDetector`、`ConditionExtractor`、`ProblemClassifier`、`parameter_analyzer` 若干函数、`visualizer.build_report`、`utils.parse_json_from_llm` 与 `ALL_FUNCTIONS`、`ContextBudget`、`DataProbe`、`VariableQueryPlanner` 等（```9:28:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```）。

### 1.2 模块级常量、全局符号与辅助函数

| 名称 | 行号 | 说明 |
|------|------|------|
| `_signal_overlap_ok` | ```31:43:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py``` | 模块级函数：用正则分词 + 集合交叠比例（默认 `min_ratio=0.45`）判断 `hint` 与候选 CAN 信号名是否足够语义重叠；内部嵌套 `_tokens(s)`。 |
| `ORCHESTRATOR_SYSTEM` | ```45:60:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py``` | 传给「问题理解」阶段 `router.complex` 的系统提示：角雷达调度器角色、ADAS 功能列表、双状态机架构、信号链路、simple/complex 分流规则、输出语言要求。 |

无其它模块级可变全局状态（除上述常量字符串外）。

### 1.3 `Orchestrator` 类定位

- **定位**：自动化完整诊断管线的总编排类；对外主入口为 `run_diagnosis`（```63:67:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```）。

### 1.4 `__init__` 签名、参数与成员字段

- **签名**：`def __init__(self, config: dict, project_root: Path)`（```69:77:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```）。
- **参数**：
  - `config`：工程配置（含 `paths.source_code`、`ai.variable_probe` 等，在管线中多处使用）。
  - `project_root`：雷达分析项目根（`source_docs`、`memory` 等相对此路径）。
- **成员属性（attribute）清单**：
  - `self.config`
  - `self.project_root`
  - `self.router`：`ModelRouter(config)`
  - `self.memory`：延迟导入 `MemorySystem(project_root)`（```74:75:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```）
  - `self._last_tpe_result`：初始 `None`；TPE 成功运行后缓存 `TemporalPatternEngine.run` 的 live 结果对象，供 HTML 可视化等使用（```77:77:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```，写入逻辑在 ```658:658:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```）。

---

## 2. 入口方法 `run_diagnosis`

### 2.1 完整签名（含默认参数）

```79:85:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py
    def run_diagnosis(
        self,
        case_dir: Path,
        problem: str,
        expected: str,
        on_status=None,
    ) -> str:
```

### 2.2 返回值

- 返回类型注解为 `str`：最终为 **`report.md` 的文件路径字符串**（由 `_save_report` 返回）（```505:511:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```、`548:549:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py`）。

### 2.3 调用流程（按 `on_status` 的 step 分段编号）

内部闭包 `status(step, detail="")`：若传入 `on_status` 则调用 `on_status(step, detail)`（```103:105:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```）。

**Step 1 — `init`**  
- 文案：`Checking prerequisites...`（```108:108:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```）

**Step 2 — `source_docs`（由 `_ensure_source_docs` 内回调触发，非 `run_diagnosis` 顶层直接写 step 名）**  
- `CodeLearner.ensure_overview_docs` 通过 `status_cb=lambda step, msg: status("source_docs", msg)` 上报（```1249:1252:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```）；可能还有 `signal_mapping` 构建消息（```1259:1266:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```）。

**Step 3 — `understand`**  
- `AI is understanding the problem...` → 调用 `_understand_problem` → 再报 `Identified function: {func_name}`（```112:117:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```）。

**Step 4 — `classify`**  
- `Classifying task type...` → `ProblemClassifier.classify` → 汇总 `task_type`、`func`、`focus`、`conf`（```120:137:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```）。

**Step 5 — `parse`**  
- `Parsing data files...` → `_parse_case_data`（```141:142:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```）。

**Step 6 — `detect_window`**  
- 窗口检测相关多条 `status`（阈值说明、找到/未找到窗口）（```150:168:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```）。

**Step 7 — `analyze`**  
- 帧分析、证据提取等多条 `status`（```178:190:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```）；`_run_frame_analysis_with` 内另有 `analyze` + `Extracting warning timeline...`（```1331:1332:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```）。

**Step 8 — `conditions`**  
- 条件提取结果或错误信息（```193:200:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```）。

**Step 9 — `tpe`**  
- TPE 运行；`_run_tpe` 内部失败时也会 `status("tpe", ...)`（```207:219:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```、```577:579:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py``` 等）。

**Step 10 — `probe`**  
- 变量探测规划与执行；异常时 `Variable probe skipped`（```235:268:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```）。

**Step 11 — `suppression`**  
- 外部抑制信号检查或跳过原因；`_check_suppression_signals` 内逐信号也会 `status("suppression", ...)`（```271:283:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```、```948:948:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```）。

**Step 12 — `output_signals`**  
- 输出信号分析；`_analyze_output_signals` 内列出目标信号（```287:295:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```、```684:684:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```）。

**Step 13 — （无独立 `on_status`）**  
- `_load_threshold_reference`：仅读文件，不调用 `status`（```298:298:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```）。

**Step 14 — `params`**  
- 当 `task_type in ("tune", "verify")` 时：敏感性扫描、What-if、或失败信息（```304:342:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```）。

**Step 15 — `diagnose`**  
- 专家面板启动说明（```346:346:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```）。  
- **注意**：`ExpertPanel.run_panel(..., on_status=on_status)` 会把同一回调继续传给子模块，**可能产生本文件未列出的额外 step 名称**（```481:491:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```）。

**Step 16 — `panel_prompt`**  
- `ContextBudget.format_report()` 的预算报告字符串（```479:479:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```）。

**Step 17 — `report`**  
- `Generating report...`（```504:504:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```）。

**Step 18 — `visualize`**  
- HTML 可视化成功或失败（```517:539:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```）。

**Step 19 — `done`**  
- 参数为 `report_path`（```546:546:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```）。

**收尾**：`store.close()`，返回 `report_path`（```548:549:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```）。

---

## 3. 管线每一步的详细说明

### 步骤 1：`init` + 源码文档保障

- **`on_status`**：`init`（```108:108:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```）。
- **调用**：`_ensure_source_docs(status)`（```109:109:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```）。
- **输入**：`self.config`、`self.project_root`、`ALL_FUNCTIONS`（经 `CodeLearner`）。
- **输出**：`source_docs` 下概览文档与可能的 `signal_mapping.json`；**不**在 `run_diagnosis` 内返回变量，副作用见第 7 节。
- **关键代码**：```107:109:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```、```1247:1266:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```。
- **分支/错误**：`ensure_overview_docs` 返回 `failed` 列表时逐条 `source_docs` WARN（```1256:1257:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```）；mapping 构建失败不抛到 `run_diagnosis` 外层。
- **Prompt**：无（`CodeLearner` 内部可能有 AI，本文件不展开）。

---

### 步骤 2：`understand` — 问题理解

- **`on_status`**：`understand`（```112:117:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```）。
- **调用**：`self.memory.create_session`；`_understand_problem`；`self.memory.log_step(session_id, "understand", func_info)`。
- **输入**：`problem`、`expected`、`case_dir`；`memory.build_context_for_diagnosis("UNKNOWN", ...)` 在 `_understand_problem` 内（```1269:1269:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```）；功能 MD 预筛选（```1273:1291:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```）。
- **输出**：`func_info`（dict，见第 5 节）；`session_id`；内存日志。
- **关键代码**：```111:117:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```、```1268:1324:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```。
- **分支/错误**：`parse_json_from_llm` 带 fallback（```1318:1324:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```）。
- **Prompt 构造**：中文指令 + 问题/预期/历史记忆/功能文档概要 + 固定 JSON schema（```1293:1316:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```）；**AI**：`self.router.complex(prompt, system=ORCHESTRATOR_SYSTEM)`（```1318:1318:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```）。

---

### 步骤 3：`classify` — 任务类型分类

- **`on_status`**：`classify`（```120:137:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```）。
- **调用**：`ProblemClassifier(router=self.router).classify(...)`。
- **输入**：`problem`、`expected`、`memory_hint=build_context_for_diagnosis(func_name, problem, case_dir)`（注意此处 `func_name` 已来自上一步，可能仍为 `UNKNOWN`）。
- **输出**：`classification`；可能**覆盖** `func_name`（条件：分类器给出 `target_function` 且非 `UNKNOWN`，且原 `func_name` 为 `UNKNOWN` 或 `confidence>=0.8`）（```128:131:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```）；`task_type = classification.task_type`（```131:131:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```）；`log_step(..., "classify", classification.to_dict())`。
- **关键代码**：```119:138:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```。
- **分支/错误**：分类失败行为在 `ProblemClassifier` 内；本处无 try/except。
- **Prompt**：在 `ProblemClassifier` 内（本文件不展示）。

---

### 步骤 4：`parse` — 数据解析

- **`on_status`**：`parse`（```141:142:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```）。
- **调用**：`_parse_case_data(case_dir, status)` → `parsers.case_loader.load_case_data(..., on_status=status)`。
- **输入**：`case_dir`、`config`、`project_root`；`status` 原样下传（故可能出现 loader 自定义 step，不限于 `parse`）。
- **输出**：`store`、`bag_meta`、`blf_meta`、`sync`（```142:142:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```）；`parse_summary` 写入 session（```143:147:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```）。
- **关键代码**：```140:147:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```、```1326:1329:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```。
- **分支/错误**：无本地包裹；依赖 loader。
- **Prompt**：无。

---

### 步骤 5：`detect_window` — 测试窗口检测

- **`on_status`**：`detect_window`（```150:168:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```）。
- **调用**：`TestWindowDetector()`；`self._collect_speed_thresholds(func_name)`；`detector.detect(store, func_name, speed_thresholds=...)`；`format_windows` 仅用于后续文案（在步骤 15 组装 prompt 时用 `windows_text`）。
- **输入**：`store`、`func_name`、阈值列表（可能为空）。
- **输出**：`windows`（窗口对象列表）；`memory.log_step(..., "windows", {...})`（```169:175:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```）。
- **关键代码**：```149:175:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```、```1186:1223:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```。
- **分支/错误**：无窗口时使用全数据（状态文案 ```168:168:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```）。
- **Prompt**：无。

---

### 步骤 6：`analyze` — 帧级分析与窗口内取证

- **`on_status`**：`analyze`（```178:190:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```及 `_run_frame_analysis_with`）。
- **调用**：`FrameAnalyzer(self.router, var_path 或 None)`；`_run_frame_analysis_with`；`analyzer.extract_evidence(store, func_name, windows=windows or None)`。
- **输入**：`store`、`func_name`、`func_info`、`windows`。
- **输出**：`frame_analysis`（字符串）；`evidence`（dict，含 `KEY_FACTS`、`timeline`、`state_transitions` 等）；`memory.log_step(..., "evidence", {...})`（```185:190:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```）。
- **关键代码**：```177:190:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```、```1331:1351:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```。
- **分支/错误**：`variables.json` 不存在则 `FrameAnalyzer` 无 var 路径（```179:180:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```）。
- **Prompt（帧摘要）**：`_run_frame_analysis_with` 内中文简洁总结模板 + `warning_analysis` 统计（```1337:1344:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```）；**AI**：`self.router.chat(..., complexity="simple", max_tokens=1024)`（```1346:1350:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```）。`FrameAnalyzer` 其它 LLM 调用不在本文件。

---

### 步骤 7：`conditions` — 源码条件提取

- **`on_status`**：`conditions`（```193:200:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```）。
- **调用**：`ConditionExtractor(self.router, self.project_root, self.config).extract(func_name)`；`format_conditions(conditions)`。
- **输入**：`func_name`。
- **输出**：`conditions`（dict，通常含 `external_suppression` 等；若失败含 `error`）；`conditions_text`；`log_step`（```201:204:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```）。缓存路径提示 `source_docs/{func_name}_conditions.json`（```198:198:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```）。
- **关键代码**：```192:204:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```。
- **分支/错误**：`"error" in conditions` 时分支状态文案（```197:200:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```）。
- **Prompt**：在 `ConditionExtractor` 内。

---

### 步骤 8：`tpe` — 时序模式引擎（TPE）

- **`on_status`**：`tpe`（```207:219:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```及 `_run_tpe` 内）。
- **调用**：`_run_tpe(store, evidence, func_name, windows, status)`；成功时 `FrameAnalyzer.append_tpe_block(evidence, tpe_text, tpe_report)`（```211:212:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```）。
- **输入**：`evidence`（至少 `state_transitions`）、`store`、`func_name`（**注意**：`_run_tpe` 内 `engine.run(..., time_window=None)` 未使用 `windows` 参数）（```604:607:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```）。
- **输出**：`tpe_text`、`tpe_report`（结构化 dict）；可能写入 `evidence` 的 `KEY_FACTS`（拼接）、`tpe_block`、`tpe_report`（由 `append_tpe_block` 完成，见 `frame_analyzer`）；`self._last_tpe_result`；`memory.log_step`（```213:218:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```）。
- **关键代码**：```206:219:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```、```553:659:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```。
- **分支/错误**：导入失败、mapping/chains/TPE run 任一异常则返回 `("", {})` 并 `status("tpe", ...)`，不中断主流程（```577:611:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```）。
- **Prompt**：TPE 本体无 LLM；输出为规则/模式对齐生成的叙述块。

---

### 步骤 9：`probe` — 变量查询探测（LLM 规划 + DataProbe）

- **`on_status`**：`probe`（```235:268:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```）。
- **调用**：`VariableQueryPlanner(self.router, self.memory, self.project_root).plan(...)`；`DataProbe(store, windows=windows or []).query`；`render_probe_results_for_prompt`。
- **输入**：`probe_cfg = config["ai"]["variable_probe"]`；`enabled` 默认 `True`；`max_queries` 默认 6；`use_thinking` 默认 `False`；`max_chars` 默认 6000（```231:246:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```）；`store is not None` 才进入（```233:233:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```）。
- **输出**：`probe_section`（注入专家 prompt 的文本）；`probe_plans`、`probe_results`；`log_step(..., "variable_probe", ...)`（```258:266:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```）。
- **关键代码**：```221:268:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```。
- **分支/错误**：整块 `try/except`，失败则 `status("probe", f"Variable probe skipped: {e}")`；单条 query 异常追加 error 结果（```251:257:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```）。
- **Prompt**：在 `VariableQueryPlanner.plan`；`use_thinking` 来自配置（```245:245:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```）。

---

### 步骤 10：`suppression` — 外部抑制信号检查

- **`on_status`**：`suppression`（```271:283:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```）。
- **调用**：`self._check_suppression_signals(store, suppression_signals, windows, func_name, status)`（**注意**：函数签名含 `windows`，实现体内**未使用** `windows`）（```796:799:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```）。
- **输入**：`conditions.get("external_suppression", [])`；需 `store.get_can_ids()` 为真（```272:273:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```）。
- **输出**：`suppression_text`（Markdown 片段）；可选 `log_step`（```278:281:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```）。
- **关键代码**：```270:283:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```、```796:952:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```。
- **分支/错误**：有抑制配置但无 CAN：`No CAN data available`（```282:283:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```）。
- **Prompt**：无。

---

### 步骤 11：`output_signals` — 输出信号分析

- **`on_status`**：`output_signals`（```287:295:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```）。
- **调用**：`_analyze_output_signals(store, func_name, windows, status)`（**注意**：`_analyze_output_signals` 签名含 `windows`，**实现未使用**）（```663:665:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```）。
- **输入**：`store.get_can_ids()` 为真才进入（```287:287:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```）。
- **输出**：`output_signal_text`；可选 `log_step`（```292:295:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```）。
- **关键代码**：```285:295:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```、```663:792:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```。
- **Prompt**：无。

---

### 步骤 12：权威阈值参考（无 `status`）

- **调用**：`_load_threshold_reference(func_name)`（```298:298:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```）。
- **输入**：`source_docs/{func_name}.md`。
- **输出**：`threshold_ref`（最多 4000 字符）或 `""`（```1118:1127:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```）。
- **关键代码**：```297:298:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```、```425:432:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```（组装 `threshold_section`）。

---

### 步骤 13：`params` — 参数敏感性与 What-if（仅 `tune`/`verify`）

- **`on_status`**：`params`（```304:342:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```）。
- **调用**：`analyze_sensitivity`、`render_sensitivity_markdown`；`_parse_proposals`；`what_if`；`render_what_if_markdown`（在后续组装 `params_section` 时使用 `whatif_entries`）（```434:447:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```）。
- **输入**：`classification.focus_parameters`；`Path(self.config["paths"]["source_code"])`；`store`。
- **输出**：`param_section_md`、`param_report_obj`、`whatif_entries`；`log_step`（```320:338:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```）。
- **关键代码**：```300:342:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```。
- **分支/错误**：`try/except` 失败则清空 `param_section_md`（```340:342:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```）。
- **Prompt**：`analyze_sensitivity` / `parameter_analyzer` 内部可能有；本文件无直接 `router` 调用。

---

### 步骤 14：`diagnose` + `panel_prompt` — 专家面板

- **`on_status`**：`diagnose`（```346:346:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py`）；`panel_prompt`（```479:479:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```）。
- **调用**：`ExpertPanel(self.router, self.config, self.project_root).run_panel(...)`。
- **输入（数据侧）**：
  - 从 `evidence` **弹出** `KEY_FACTS`、`timeline`、`state_transitions`、`tpe_block`、`tpe_report`（```350:354:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```）。
  - `evidence_text` 为剩余 `evidence` 的 JSON（截断 20000）（```356:358:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```）。
  - `key_facts`、`timeline_text`、`windows_text`、`transitions_text`（```360:369:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```）。
  - **TPE 独立段落**：`tpe_block = evidence.get("tpe_block") or ""`（```371:372:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```）——由于在 ```353:354:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py``` 已从 `evidence` **pop** 掉 `tpe_block`，此处 **`tpe_block` 恒为空字符串**，`tpe_section` 通常为空；TPE 叙述仍可能存在于 **`key_facts`**（因 `append_tpe_block` 会拼入 `KEY_FACTS`，见 `frame_analyzer.append_tpe_block`）。
  - `suppression_section`、`output_section`、`threshold_section`、`params_section`（```391:447:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```）。
  - `ContextBudget` 合并：`methodology_block` + 上述各块（```452:477:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```）。
  - `combined_data = budget.concat()`（```478:478:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```）。
- **输出**：`panel_result`；`diagnosis = panel_result.get("final_verdict", "Diagnosis failed.")`（```492:492:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```）；`log_step(..., "expert_panel", ...)`（```493:497:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```）。
- **关键代码**：```344:497:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```。
- **分支/错误**：无本地对 `run_panel` 的 try/except。
- **Prompt 构造**：本文件完成「数据面」拼装；**方法论**固定块（```452:458:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```）；**预算裁剪**由 `ContextBudget`（总预算 `60_000`，各块 `priority`/`min_chars`）（```460:476:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```）。具体专家轮次 prompt 在 `ExpertPanel` 内。

---

### 步骤 15：`report` — 报告落盘

- **`on_status`**：`report`（```504:504:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```）。
- **调用**：`_save_report(...)`；`_save_expert_appendix`（```505:514:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```）。
- **输入**：`diagnosis`、`task_type`、`param_section_md`、`whatif_md` 等。
- **输出**：`case_dir / "report.md"`；`case_dir / "expert_opinions.md"`。
- **关键代码**：```503:514:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```、```1383:1454:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```。
- **Prompt**：无。

---

### 步骤 16：`visualize` — HTML 可视化

- **`on_status`**：`visualize`（```517:539:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```）。
- **调用**：`build_html_report(...)`（```518:532:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```）。
- **输入**：`self._last_tpe_result`、`param_report_obj`、`whatif_entries`、元数据等。
- **输出**：`viz.html_path` 等经 `status` 报告；`memory.log_step(..., "visualize", viz.to_dict())`（```537:537:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```）。
- **关键代码**：```516:539:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```。
- **分支/错误**：`except` 捕获，`status` 报错（```538:539:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```）。

---

### 步骤 17：记忆更新与 `done`

- **调用**：`_update_memories`（`try/except` 吞异常）（```541:544:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```）；`self.memory.complete_session`（```545:545:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```）；`status("done", report_path)`（```546:546:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```）；`store.close()`（```548:548:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```）。
- **关键代码**：```541:549:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```、```1456:1496:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```。

---

## 4. 每个私有方法 `_xxx` 的职责与签名

下列为 **类内** `def _...` 及 **模块级** 辅助（含 `staticmethod`）。**按源码出现顺序**。

| 方法 | 签名要点 | 职责摘要 | 被谁调用 | 内部/外部调用 |
|------|-----------|----------|----------|----------------|
| `_signal_overlap_ok`（模块） | `(hint, candidate, min_ratio=0.45) -> bool` | 语义 token 重叠比例校验 | `_resolve_can_signal`（```1111:1111:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```） | 嵌套 `_tokens` |
| `_run_tpe` | `(self, store, evidence, func_name, windows, status) -> tuple[str, dict]` | 加载 mapping/chains，运行 `TemporalPatternEngine`，生成专家块与结构化摘要 | `run_diagnosis` | `extract_signal_mapping`、`load_variable_chains`、`trace_variable_chains`、`TemporalPatternEngine` |
| `_analyze_output_signals` | `(self, store, func_name, windows, status) -> str` | 按功能拉取输出 CAN 信号，统计与激活段/跳变 | `run_diagnosis` | `extract_output_signal_mapping`、`get_output_signals_for_function`、`store` 查询 |
| `_check_suppression_signals` | `(self, store, suppression_signals, windows, func_name, status) -> str` | 解析抑制条件对应 CAN，阈值判定与极性交叉检查 | `run_diagnosis` | `_resolve_can_signal`、`_semantic_fallback`、`_evaluate_threshold`、`_invert_threshold` |
| `_evaluate_threshold`（静态） | `(values, threshold_str) -> dict` | 解析阈值串，计算满足比例与描述 | `_check_suppression_signals` | `re` |
| `_invert_threshold`（静态） | `(threshold_str) -> str` | 布尔类阈值的逻辑反用于交叉检查 | `_check_suppression_signals` | 字典映射 |
| `_semantic_fallback` | `(self, condition, system, all_signals, all_signal_names, sig_mapping) -> tuple[list[str], str]` | 复合变量无法解析时的关键词信号搜索 | `_check_suppression_signals` | `re` |
| `_resolve_can_signal`（静态） | 见 ```1064:1072:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py``` | 内部变量/hint → BLF 中 CAN 名 | `_check_suppression_signals` | `resolve_internal_to_can`、`_signal_overlap_ok` |
| `_load_threshold_reference` | `(self, func_name) -> str` | 读 `source_docs/{func}.md` 前 4000 字符 | `run_diagnosis` | `Path.read_text` |
| `_parse_proposals`（静态） | `(problem, expected, param_report) -> dict[str, float]` | 从自然语言提取 `{参数名: 新值}` | `run_diagnosis`（tune/verify） | 正则 `_re` |
| `_collect_speed_thresholds` | `(self, func_name) -> list[float]` | 从 `{FUNC}_conditions.json` 收集速度上下界 | `run_diagnosis` | `_parse_speed_value`、`json.loads` |
| `_parse_speed_value`（静态） | `(raw) -> float \| None` | 从字符串提取数值 | `_collect_speed_thresholds` | `_re.search` |
| `_ensure_source_docs` | `(self, status)` | 保障概览文档与 signal_mapping | `run_diagnosis` | `CodeLearner.ensure_overview_docs`、`extract_signal_mapping` |
| `_understand_problem` | `(self, problem, expected, case_dir) -> dict` | LLM 识别功能与失败类型等 | `run_diagnosis` | `memory.build_context_for_diagnosis`、`router.complex`、`parse_json_from_llm` |
| `_parse_case_data` | `(self, case_dir, status)` | 加载案例 SQLite 与元数据 | `run_diagnosis` | `load_case_data` |
| `_run_frame_analysis_with` | `(self, analyzer, store, func_name, func_info, status) -> str` | BAG 时间线 + LLM 短摘要 | `run_diagnosis` | `analyzer.analyze_bag_timeline`、`router.chat` |
| `_build_data_summary` | `(self, store, bag_meta, blf_meta, sync) -> str` | 人类可读数据概览 | `run_diagnosis`（专家 prompt） | `store.query_bag_by_topic`、`store.get_can_ids` |
| `_save_report` | 见 ```1383:1387:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py``` | 写 `report.md` | `run_diagnosis` | 文件写入 |
| `_save_expert_appendix` | `(self, path, panel_result) -> None` | 写 `expert_opinions.md` | `run_diagnosis` | 文件写入 |
| `_update_memories` | `(self, session_id, case_dir, func_name, func_info, diagnosis, problem)` | case memory、pattern、function knowledge | `run_diagnosis` | `write_case_memory`、`router.chat`、`add_pattern`、`read/write_function_knowledge` |

---

## 5. 关键数据结构（贯穿上下文的 dict / 对象）

**说明**：文件中**没有**名为 `diagnosis_context` / `analysis_result` 的变量。以下为实际贯穿字段。

### 5.1 `func_info`（`_understand_problem` 返回）

- **写入**：`parse_json_from_llm` 解析 LLM JSON（```1318:1324:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```）；fallback 含 `function`、`confidence`、`fail_type`、`key_variables` 等。
- **期望字段**（来自 prompt 模板 ```1307:1315:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```）：`function`、`confidence`、`reasoning`、`fail_type`、`key_variables`、`related_functions`。
- **读取**：初始 `func_name`（```115:115:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```）；`fail_type` 用于专家选择与 `VariableQueryPlanner.plan`（```241:241:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```、`345:345:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```）；`key_variables` 用于帧分析 prompt（```1337:1337:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```）；`ExpertPanel.select_experts(fail_type)`（```345:345:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```）；`_update_memories` 传入（```542:542:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```）。

### 5.2 `classification`（`ProblemClassifier.classify`）

- **字段使用**：`target_function`、`confidence`、`focus_parameters`、`task_type`（```128:136:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```）；`to_dict()` 写入 session（```138:138:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```）。
- **读取**：覆盖 `func_name`；`task_type` 控制标题/方法描述与 `params` 分支；`focus_parameters` 传入 `VariableQueryPlanner` 与 `analyze_sensitivity`（```242:242:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```、`312:312:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```）。

### 5.3 `evidence`（`FrameAnalyzer.extract_evidence` + TPE 拼接）

- **写入**：`extract_evidence`（```184:184:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```）；`append_tpe_block` 可能追加 `KEY_FACTS` 并设置 `tpe_block`、`tpe_report`（在 TPE 成功分支 ```211:212:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```）。
- **读取/变形**：`memory.log_step("evidence", keys/KEY_FACTS 预览…)`（```185:190:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```）；随后 `pop` 出 `KEY_FACTS`、`timeline`、`state_transitions`、`tpe_block`、`tpe_report`（```350:354:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```）；剩余部分 JSON 为 `evidence_text`（```356:357:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```）。

### 5.4 `conditions`（`ConditionExtractor.extract`）

- **读取**：`conditions.get("external_suppression", [])`（```272:272:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```）；`"error" in conditions` 分支（```197:197:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```）；`format_conditions` → `conditions_text` 进预算块（```196:196:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```、`470:470:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```）。

### 5.5 `tpe_report`（结构化，`_run_tpe` 内 `structured`）

- **写入**：`_run_tpe` 内构造（```614:651:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```）。
- **读取**：`memory.log_step("tpe", ...)`（```213:218:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```）；**不**再进入 `evidence_text`（因已从 `evidence` pop）。

### 5.6 `panel_result`（`ExpertPanel.run_panel`）

- **读取字段**：`final_verdict`（```492:492:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```）；`rounds`、`moderator_challenges`（```494:495:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```）；`expert_opinions`、`moderator_challenges`（```1441:1452:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```）。

### 5.7 `parse_summary` / `windows` 日志结构

- `parse_summary`：`bag_frames`、`can_frames`（```143:146:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```）。
- `windows` 日志：`count` 与 `windows` 列表字典（```169:175:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```）。

### 5.8 `param_report_obj` / `whatif_entries`

- **写入**：`analyze_sensitivity`、`what_if`（```307:330:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```）。
- **读取**：`render_sensitivity_markdown`、报告附录、`build_html_report`、`_parse_proposals` 的 `param_report.entries`（```1132:1151:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```）。

---

## 6. AI 调用点汇总（`orchestrator.py` 内直接调用）

本文件**无** `router.complete_*` 方法名；`ModelRouter` 在本文件中仅使用：

| 行号 | 调用 | Prompt / 参数要点 | thinking | 返回解析 |
|------|------|-------------------|----------|----------|
| ```1318:1318:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py``` | `self.router.complex(prompt, system=ORCHESTRATOR_SYSTEM)` | 问题理解 JSON 任务；系统提示为 `ORCHESTRATOR_SYSTEM` | 未在本行指定（由 `complex` 默认） | `parse_json_from_llm(result.get("content",""), fallback=...)` |
| ```1346:1350:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py``` | `self.router.chat([{"role":"user","content":prompt}], complexity="simple", max_tokens=1024)` | 帧分析中文短摘要 | 未指定 | 取 `result.get("content", ...)`，缺省回退 JSON 截断 |
| ```1474:1477:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py``` | `self.router.chat(..., complexity="simple", max_tokens=512)` | 从诊断提取可复用 pattern 的 JSON | 未指定 | `parse_json_from_llm`；truthy 则 `add_pattern` |

**间接持有 `self.router` 并可能调用 AI 的组件**（本文件构造/传入）：`CodeLearner`、`FrameAnalyzer`、`ProblemClassifier`、`ConditionExtractor`、`VariableQueryPlanner`、`ExpertPanel`。其中 **`variable_probe.use_thinking`** 显式传入 `planner.plan(..., use_thinking=bool(probe_cfg.get("use_thinking", False)))`（```245:245:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```）。

---

## 7. 持久化副作用

| 路径/产物 | 何时/如何写入 |
|-----------|----------------|
| `case_dir / "report.md"` | `_save_report`（```1432:1436:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```） |
| `case_dir / "expert_opinions.md"` | `_save_expert_appendix`（```513:514:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```、`1454:1454:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```） |
| `case_dir / "memory.json"` | `write_case_memory`（```1457:1462:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```） |
| `project_root / memory / sessions / {session_id}.json` | `create_session`、`log_step`、`complete_session`（多次）（```113:113:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py``` 等） |
| `memory / patterns.json` | `add_pattern`（```1481:1481:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```） |
| `memory / functions / {FUNC}.json` | `write_function_knowledge`（```1496:1496:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```） |
| `source_docs` 下概览、`signal_mapping.json` | `_ensure_source_docs` / `CodeLearner` / `extract_signal_mapping`（```1247:1266:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```） |
| `source_docs/{func}_conditions.json` | `ConditionExtractor.extract`（状态文案 ```198:198:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```，实际写入在提取器内） |
| HTML 报告路径 | `build_html_report` 返回对象中的 `html_path`（```518:532:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```） |

---

## 8. Review 关注点

1. **`func_name` 双源融合**：先 `_understand_problem`，再 `ProblemClassifier`，覆盖条件在 ```128:131:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py``` —— 改分类器置信度阈值会改变功能判定。
2. **`ORCHESTRATOR_SYSTEM` 与问题理解 JSON 模板**：任一改动会改变功能/`fail_type`/变量列表，进而牵动窗口阈值文件键名、专家类型、TPE 的 `func_name` 等。
3. **`ContextBudget` 参数**：`total_chars=60_000` 与各块 `priority`/`min_chars`（```460:476:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```）决定裁剪顺序；调整会导致专家可见证据集合变化。
4. **`tpe_section` 与 `evidence.pop` 顺序**：```353:354:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py``` 在 ```371:372:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py``` 之前执行，导致 **`tpe_section` 通常为空**，依赖 `append_tpe_block` 写入 **`KEY_FACTS`**（经 `key_facts` 变量）进入 `budget.add("key_facts", ...)`；若未来修改 pop 顺序或不再拼接 `KEY_FACTS`，TPE 可能从专家输入中消失。
5. **未使用的 `windows` 参数**：`_run_tpe`（`time_window=None`）、`_check_suppression_signals`、`_analyze_output_signals` 签名含 `windows` 但未用于限制查询 —— Review 需求若要求「窗口内」抑制/输出分析，当前实现可能不符预期。
6. **`variable_probe` 默认**：`enabled` 默认 `True`（```232:232:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```）；`max_queries`/`max_chars` 影响成本与 prompt 长度。
7. **`task_type` 默认文案**：`title_map`/`method_map`（```1390:1403:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```）与 `task_type` 分支（```304:304:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```）需与 `ProblemClassifier` 输出枚举一致。
8. **`store.close()`**：总在返回前调用（```548:548:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```）；若上游 `store` 为 `None` 会异常 —— 需与 `load_case_data` 约定一致（本文件未校验 `store` 非空）。
9. **`_update_memories` 静默失败**：```541:544:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py```、`1456:1496:d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py``` 内部多处 `except: pass` 会隐藏记忆写入或 pattern 学习失败。
10. **子模块 `on_status` 透传**：`ExpertPanel.run_panel(on_status=on_status)` 与 `load_case_data(on_status=status)` 使 **UI 上出现的 step 名可能超出本文件列出的集合**，做需求对照时需同步追踪子模块。

---

以上 Markdown 已按你要求的章节组织，行号均来自对 `d:\RamboStar\idea\radarAnalyze\ai\orchestrator.py` 的全文阅读（共 **1497** 行）。若你需要把 **ExpertPanel / ConditionExtractor / VariableQueryPlanner** 的 prompt 与 `router` 调用也做成同级 review 文档，可在 Agent 模式下继续拆文件分析。


================================================================================

# 第三章 数据分析模块（frame_analyzer / test_window / temporal / parameter / data_probe / problem_classifier）

以下为六个模块的实现说明（行号均来自你给出的源码路径）。

---

## 模块：`frame_analyzer.py`  
路径：`D:\RamboStar\idea\radarAnalyze\ai\frame_analyzer.py`

### 定位  
逐帧分析 bag 话题与雷达相关表，抽取**状态跳变、警告时间线、自车/目标速度、雷达目标与调试摘要**，并拼成供下游 LLM/专家使用的 `evidence` 与可读 `KEY_FACTS`。支持可选 `TestWindow`：在窗口内全分辨率查询，否则对 ego 帧均匀抽样。

### 公开接口  
（类实例方法含 `self`；静态方法无 `self`。）

- `def __init__(self, router: ModelRouter, variables_path: Optional[str | Path] = None) -> None` — 23:29  
- `def get_variables_for_function(self, func_name: str) -> list[dict]` — 31:36  
- `def analyze_bag_timeline(self, store, topic: str, func_name: Optional[str] = None) -> dict` — 38:66  
- `def extract_evidence(self, store, func_name: str, windows: Optional[list[TestWindow]] = None) -> dict` — 103:180  
- `def append_tpe_block(evidence: dict, tpe_block: str, tpe_report: dict) -> None` — 183:194  
- `def format_timeline(timeline: list[dict], max_lines: int = 200, func_name: str = "") -> str` — 575:615  

### 关键数据结构  

**`analyze_bag_timeline` 返回**（57:66）：`topic`, `frame_count`, `change_count`, `changes`（每项 `timestamp`, `changes`: `{field, old, new}`）, `time_range.start/end`。

**`extract_evidence` 返回**（聚合，含动态键）：  
- 若有窗口：`test_windows`: `t_start`, `t_end`, `duration`, `reason`  
- `warning_states`: `total_frames`, `sampled`（`t`, `bytes`）  
- `ego_{side}`：每侧样本列表（`t`, `side`, 诊断字段、`trc_{i}_*`）  
- `timeline`：合并排序后的样本  
- `state_transitions`：`t`, `side`, `field`, `from`, `to`  
- `radar_objects_warned` / `radar_objects_summary`（见 223:240）  
- `adas_enable_states`, 可选 `bld_summary`  
- `warning_events`  
- `can_summary`（最多 15 条）  
- `KEY_FACTS`：字符串  
- `tpe_report`, `tpe_block`：默认 `None`，可由 `append_tpe_block` 写入  

**内部状态**：`self.router`（构造传入但**本文件内未使用**）、`self.variables`（可选 JSON 列表）。

### 处理流程  

1. **`extract_evidence`**：可选写入 `test_windows` → `_extract_warnings` → 对 `get_func_fields(func_name)["ego_topics"]` 逐 topic：有 `windows` 则 `_query_windowed`，否则全量；`_extract_from_frames` 得样本与跳变 → `_compute_stats` → 合并 `timeline` / `state_transitions` → `_extract_object_evidence` → `_extract_debug_evidence` → `_extract_warning_events` → CAN 摘要 → `_build_key_facts` → `setdefault` TPE 占位。  
2. **FrameStore 读取**：`store.query_bag_by_topic`（可加 `time_start_ns`/`time_end_ns`）、`query_objects_with_warning`、`query_debug_in_window`、`query_warning_events`、`get_can_ids`。  
3. **状态跳变**：对 `state_fields`（`state`/`enable` + `warnings` 映射名）逐帧比较 `prev_states`（369:382）。  
4. **警告时间线**：topic 固定 `"/corner_radar/warning_status_raw"`，取 `warning_bytes` 前 20 字节（395:398）。  
5. **目标速度等**：`trc_{i}_*` 仅在 `|vel_x|>0.1` 或 `|dist_x|>0.1` 时展开到 sample（357:365）。  
6. **`_build_key_facts`**：窗口说明、跳变摘要（最多 20 条）、按侧统计 `car_spd`、状态枚举说明、警告计数、trc 速度与 TTC/dist、因果分层（观测层雷达 vs 配置层 ADAS 使能）。

### AI 调用点  
**无**。`ModelRouter` 仅保存在 `__init__`，本文件无任何 `router.*` 调用。

### 隐式规则 / 阈值 / 魔数  
- 抽样：无窗口时 ego `step = max(1, len//50)`，最多 50 帧（342:343）。  
- 目标通道展开阈值：`0.1`（361）。  
- `warning_states` 超过 60 则再抽样到 60（400:402）。  
- 雷达告警对象：循环最多 200 条快照，保留 `radar_objects_warned` 最多 100（210:223）。  
- `warning_events` 最多 50（299）。  
- `can_summary` 前 15 条（168）。  
- `_extract_debug_evidence` 无窗口时 `query_debug_in_window(0, int(9e18))`（254）。  
- `KEY_FACTS` 跳变最多 20、warning_events 展示 5（453:551）。  
- `format_timeline`：`max_lines` 默认 200，步进 `len//max_lines`（588:589）；轨迹行 `|vx|>0.1`（605）。

### 外部依赖  
- `ModelRouter`（未使用）、`TestWindow`、`get_func_fields`（`utils`）。  
- **数据源**：`FrameStore`（SQLite 封装）；**无**直接读 `source_docs`/`memory`。

### Review 关注点  
- `router` 未使用是否为死代码或预留。  
- `analyze_bag_timeline` 的 `func_name` 参数未使用。  
- 窗口重叠时 `_query_windowed` 按 `timestamp_ns` 去重（313:321）。  
- TPE 与 `KEY_FACTS` 拼接约定（183:192）。

---

## 模块：`test_window_detector.py`  
路径：`D:\RamboStar\idea\radarAnalyze\ai\test_window_detector.py`

### 定位  
**纯规则、无 AI**：从长时间 bag 中自动估计「功能活跃」时间段，输出 `TestWindow` 列表，供 `FrameAnalyzer.extract_evidence` 等聚焦分析。

### 公开接口  
- `@property def duration(self) -> float`（`TestWindow`，31:33）  
- `def contains(self, t: float) -> bool`（35:36）  
- `def detect(self, store, func_name: str, speed_thresholds: list[float] | None = None) -> list[TestWindow]`（`TestWindowDetector`，50:99）  
- `def format_windows(windows: list[TestWindow]) -> str`（388:403）  

（`TestEvent` 为数据类，无自定义方法。）

### 关键数据结构  
- **`TestEvent`**：`t`, `event_type`, `detail`（16:21）。  
- **`TestWindow`**：`t_start`, `t_end`, `trigger_reason`, `events`（24:33）。  
- **`detect` 输出**：`list[TestWindow]`，按合并后区间生成；`trigger_reason` 为中文标签集合拼接（319:333）。

### 处理流程（如何从 state / target_warning / ego_speed 等确定窗口）  

1. **`get_func_fields(func_name)`** 取 `ego_topics`，对每 topic `store.query_bag_by_topic`，`_build_series` 抽出时间序列（169:184）：  
   - 恒有：`t`, `car_spd`, `actual_gear`；  
   - 若有映射：`state`, `enable`, 各 `warnings` 字段名；  
   - `trc_{0..3}_{vel_x,dist_x,dist_y}`。  

2. **事件检测**（可并行叠加）：  
   - **`_detect_target_events`**（188:226）：每 track `|vel| > 0.5` 或 `|dist| > 0.3` 视为 present；连续 present 至少 **3 帧** 才在消失时发 `target_appear`/`target_disappear`（末尾未消失且够长也发 appear）。  
   - **`_detect_state_transitions`**（228:244）：`fmap["state"]` 默认键名 fallback `fcta_system_state`；相邻帧状态变化 → `state_change`。  
   - **`_detect_warning_events`**（246:261）：对 `fmap["warnings"]` 每个键，值相对前一帧变化 → `warning_on` / `warning_off`（由 `val > prev_val` 判 on）。  
   - **`_detect_speed_events`**（263:283）：`car_spd` 相对 **阈值列表** 上穿/下穿；阈值默认 `_GENERIC_SPEED_THRESHOLDS` 或调用方传入（如 conditions JSON）。  
   - **`_detect_warning_edge_events`**（101:121）：`store.query_warning_events(func_name)` 的 `start_ns`/`end_ns` → `warning_edge_on`/`warning_edge_off`。  
   - **`_detect_object_approach_events`**（124:152）：`query_objects_with_warning` 按 `(radar_id,obj_id)` 分组；若首末距离满足 `first_dist > 1.0` 且 `last_dist < first_dist * 0.5` → 中点时间 `object_approach`。  

3. **合并**（288:334）：每个事件扩展为 `[t - 2, t + 2]` 秒（`_PADDING_SEC`），区间重叠则合并；第二遍再合并相交区间。对每个窗口从事件类型映射 `trigger_reason`：`目标出现` / `状态跳变` / `报警变化` / `速度变化`。  

4. **回退**（337:381）：无任何事件时，在 ego 序列上找「非零目标 track 数」最大的时刻，窗口 `[best_t-5, best_t+5]`（`_FALLBACK_WINDOW_SEC=10`）；再不行取时间序列中点 ± `min(5, (t1-t0)/2)`。

### AI 调用点  
**无**。

### 隐式规则 / 阈值 / 魔数  
- `_PADDING_SEC = 2.0`（38）  
- `_MIN_TARGET_FRAMES = 3`（39）  
- `_TARGET_VEL_THRESH = 0.5`，`_TARGET_DIST_THRESH = 0.3`（40:41）  
- `_FALLBACK_WINDOW_SEC = 10.0`（42）  
- `_GENERIC_SPEED_THRESHOLDS = [0.5, 5.0, 10.0, 21.0]`（44）  
- 接近检测：`first_dist > 1.0`，距离减半（144:146）  
- `format_windows` 每窗口最多列 15 个事件（399:402）  

**Review**：`_detect_speed_events` 中 `car_spd` 来自 bag 字段（通常为 **m/s**），与详情字符串中写的 `km/h`（277:281）及阈值语义可能不一致，需与实车数据单位核对。

### 外部依赖  
- `get_func_fields`（`utils`）；`FrameStore` 的 `query_bag_by_topic`、`query_warning_events`、`query_objects_with_warning`。  
- **无** `parameters.json` / memory 层级。

### Review 关注点  
- 速度阈值单位与 `car_spd` 单位是否一致。  
- `state` 默认名 `fcta_system_state` 对非 FCTA 功能是否总正确。  
- `warning` 边沿用 `val > prev_val` 定义 on，多电平信号是否满足预期。

---

## 模块：`temporal_analyzer.py`  
路径：`D:\RamboStar\idea\radarAnalyze\ai\temporal_analyzer.py`

### 定位  
**确定性、无 AI**：把单条信号时间线转为 **边（Edge）/ 连续段（Run）/ 统计 / 模式标签**，弥补仅用 `Counter` 丢失的时序信息（文档 8:30）。与「TTC 物理公式」无关；若分析 TTC **信号**，应用 `load_bag_field(..., "trc_X_ttc")` 再 `analyze`。

### 公开接口（节选，满足「不遗漏」）  
- `TemporalFeature.to_dict(self) -> dict` — 130:151  
- `TemporalFeature.duration` / `edge_rate` — 102:109  
- `TemporalFeature.min_run_duration` / `max_run_duration` / `total_time_at` / `brief_runs_at` — 111:128  
- `def analyze(self, timeline: SignalTimeline) -> Optional[TemporalFeature]` — 168:199  
- `def load_can_signal(store, message_name: str, signal_name: str) -> SignalTimeline` — 290:298  
- `def load_bag_field(store, topic: str, field_name: str, time_start_ns: Optional[int] = None, time_end_ns: Optional[int] = None) -> SignalTimeline` — 301:313  
- `def analyze_many(self, timelines: Iterable[SignalTimeline]) -> dict[str, TemporalFeature]` — 315:324  
- `def format_temporal_features(features: dict[str, TemporalFeature], highlight_value: object = 0, brief_threshold_ms: float = 500.0) -> str` — 340:381  
- `def dump_features_json(features: dict[str, TemporalFeature]) -> str` — 384:389  

### 关键数据结构  
- **`TemporalFeature.to_dict`**：`signal_name`, `sample_count`, `span_sec`, `t_start`, `t_end`, `value_distribution`（键转 str）, `edge_count`, `edge_rate_hz`, `edges_preview`（前 20）, `runs_preview`（前 20）, `stats`, `pattern_tag`。  
- **`stats`**：含 `edge_count`, `run_count`, `run_durations_ms`（min/max/median）, `per_value`, 可选 `brief_pulses`。

### 处理流程（时序算法 / 「时间竞争」相关）  

1. **`analyze`**：空则 `None`；样本按时间排序；`_runs_and_edges` 单次扫描生成 runs 与边（201:222）。  
2. **`_compute_stats`**：按 value 聚合 run 的时长统计；**短脉冲**：`duration < BRIEF_PULSE_THRESHOLD_SEC`（251:261）。  
3. **`_classify_pattern`**（265:285）：  
   - `runs<=1` → `stable`  
   - `edge_rate = (len(runs)-1)/span >= HIGH_EDGE_RATE_HZ` → `oscillating`  
   - 存在 `brief_pulses` 且脉冲总数 ≥1 且 `len(runs_by_value)>=2` → `brief_pulses`  
   - 两值且 `edge_rate>0.1` → `edge_dominated`  
   - 否则 `stable`  

「时间竞争」在本模块中体现为：**短持续时间 run**、**高跳变率**、**边主导** 等标签，用于描述两状态快速争抢/振荡，而非碰撞 TTC 计算。

### AI 调用点  
**无**。

### 隐式规则 / 阈值 / 魔数  
- `BRIEF_PULSE_THRESHOLD_SEC = 0.5`（165）  
- `HIGH_EDGE_RATE_HZ = 2.0`（166）  
- `brief_pulses` 分类条件：`pulse_total >= 1` 且 `len(runs_by_value) >= 2`（278:280）  
- `edge_dominated`：`len(runs_by_value)==2` 且 `edge_rate > 0.1`（282:283）  
- `format_temporal_features`：`brief_threshold_ms` 默认 500（343），仅用于文案  
- `_SafeEvaluator`：`max_statement_length=500`（frame_store 无关，本文件无此；在 data_probe 有）— 略  

### 外部依赖  
- `FrameStore.query_can_by_name`、`query_bag_by_topic`（经 `load_*`）。  
- **无** `source_docs`/`memory`。

### Review 关注点  
- TTC 仅当 bag 中存在对应字段时作为普通标量时间线分析；**不**计算运动学 TTC。  
- 样本非时间单调时仍先 `sorted`（173），重复时间点合并为同一 run 逻辑需知悉。

---

## 模块：`parameter_analyzer.py`  
路径：`D:\RamboStar\idea\radarAnalyze\ai\parameter_analyzer.py`

### 定位  
扫描 ECU 侧阈值源码 → 缓存 **`source_docs/parameters.json`**（按源码 hash 失效）；对录制数据做 **穿越次数 / 超阈帧数 / margin**，并支持 **what-if** 改阈值后的对比。**不**仿真完整 ECU 逻辑。

### 公开接口  
- `def scan_parameters(source_root: Path | str, cache_dir: Path | str | None = None, force: bool = False) -> ParameterScanResult` — 277:392  
- `def analyze_sensitivity(source_root: Path | str, cache_dir: Path | str, store, func_name: str, focus_categories: Iterable[str] | None = None) -> SensitivityReport` — 555:622  
- `def what_if(sensitivity: SensitivityReport, proposals: dict[str, float], store=None) -> list[WhatIfEntry]` — 644:685  
- `def render_sensitivity_markdown(report: SensitivityReport, max_rows_per_cat: int = 8) -> str` — 690:769  
- `def render_what_if_markdown(entries: list[WhatIfEntry]) -> str` — 772:788  

Dataclass：`Parameter.to_dict`、`ParameterScanResult.to_dict`/`by_function`、`CrossingStats.to_dict`、`SensitivityEntry.to_dict`、`SensitivityReport.to_dict`、`WhatIfEntry.to_dict`。

### 关键数据结构  
- **`parameters.json`**（经 `scan_parameters` 写入）：`source_hash`, `count`, `parameters[]`（`Parameter` 各字段）。  
- **`SensitivityReport.to_dict`**：`func`, `total_parameters`, `parameters_analyzed`, `entries`, `uncovered_categories`。  
- **`CrossingStats`**：`crossings`, `crossings_up`, `crossings_down`, `frames_above`, `frames_below`, `frames_total`, `min_margin`, `median_margin`。

### 处理流程（与 `parameters.json` 及敏感性）  

1. **`scan_parameters`**：拼接 `adasFunc.c` / `adasFunc.h` / `paraDefine.h`（相对 `source_root` 的路径见 295:302），SHA1 → 若 `cache_dir/parameters.json` 存在且 hash 一致则**直接加载**（318:325）；否则正则扫描 `bool`/`float` 声明，分类 `_resolve_category`、功能 `_resolve_func`，写回 JSON（383:391）。  

2. **`analyze_sensitivity`**：`scan_parameters` → `by_function(func_name)` + **`FCT_SHARED`**（568:569）；可选 `focus_categories` 过滤（571:573）。  
3. 按参数 **category** 缓存 `_observed_values_for(store, cat)`：例如 SPEED 用 `car_spd * 3.6` 得 **km/h**（414:441），与代码中 SPEED 阈值单位对齐；TTC/TTM 共用 `trc_*_ttc`（483:485）；等。  
4. 对每个有 `param.value` 且观测非空的参数：`_compute_crossings(values, threshold)`（507:532）：上穿/下穿计数、`frames_above`/`below`、`|v-threshold|` 排序得 min/median margin。  
5. **无可观测类别**（`FLAG`/`HOLD` 等映射为 `None`）：`note` 说明（585:593）。  
6. **`what_if`**：按 `proposals` 名找 `SensitivityEntry`，用 **store 若提供则重采观测**，否则调用 `_observed_values_for(None, cat)` — **store 为 None 时若仍走采集会异常**，属实现风险（663:668）。

### AI 调用点  
**无**。

### 隐式规则 / 阈值 / 魔数  
- 扫描文件相对路径三条（295:299）。  
- `max_rows_per_cat` 默认 8（692）。  
- Markdown 注解：`min_margin < 1.0` 标「接近阈值」（757:758）。  
- 注释：`TTM` bag 无单独通道，复用 `trc_ttc`（114）。  
- `_extract_inline_comment` 最长 200 字符（409）。

### 外部依赖  
- **源码树** `source_root`；**缓存** `cache_dir/parameters.json`。  
- **FrameStore**：`_collect_car_speeds_kmh` / `_collect_trc_field_kmh` 固定四个 ego topic（417:452）。

### Review 关注点  
- `what_if(..., store=None)` 与 `_observed_values_for(None, ...)` 的兼容性。  
- 类别 `RATIO`/`HOLD` 等无观测通道时的报告解读。  
- 与 `test_window_detector` 的速度单位是否一致（本模块 SPEED 明确 **km/h**）。

---

## 模块：`data_probe.py`  
路径：`D:\RamboStar\idea\radarAnalyze\ai\data_probe.py`

### 定位  
**无业务语义**的探针：对 **FrameStore 底层 SQLite** 拉取原始行，用 **asteval + numpy** 对表达式求值，再 **group_by + 统计**。业务含义由上层 `VariableQueryPlanner` 决定。

### 公开接口  
- `def to_dict(self) -> dict`（`ProbeResult`，213:229）  
- `def __init__(self, store, windows: Optional[list] = None) -> None`（235:245）  
- `def query(self, field: str, table: str = "radar_objects", group_by: Optional[str] = None, filter: Optional[str] = None, stats: Optional[list[str]] = None, max_rows: int = 500_000) -> dict` — 276:443  

### 关键数据结构  
**`query` 返回 dict**（`ProbeResult.to_dict`）：`field`, `table`, `row_count`, 可选 `group_by`, `filter`, `groups`（每组 min/max/mean/p10/p50/p90/std/count 等子集）, `global`（无 group 时）, 可选 `error`。

### 处理流程  

1. 校验 `table in TABLE_COLUMNS`；默认 `stats`：`count,min,max,mean,p50,p90`（298:299）。  
2. 从 `field`/`filter`/`group_by` 用 `_collect_names` 推断需 SELECT 的列；**语义字段** `side`→需 `dist_y`；`in_window`→需表的时间列（323:324）。  
3. SQL：`SELECT col_list FROM table LIMIT max_rows`（332:335）— **无 WHERE**，时间过滤靠后或全靠 filter 表达式。  
4. 列转 numpy；计算 `side`、`in_window`（352:360）。  
5. `filter`：`_rewrite_bool_ops` 把 `and/or/not` 转为 `&|~`，`eval` 得 mask（363:382）。  
6. `field` 表达式求值，须为可转 `float` 的数组（393:414）。  
7. `group_by`：按组 `_compute_stats`；否则 `global_stats`。

### 支持的查询类型  
- **表名**（仅三种）：`radar_objects`, `radar_debug`, `warning_events`（100:125；`bag_frames`/`can_frames` 在文档串提及但 **未** 列入 `TABLE_COLUMNS`）。  
- **field / filter**：算术与比较表达式；内置 numpy：`abs`, `sqrt`, `where`, `clip`, `minimum`, `maximum`, `isfinite`, `isnan`, `log`, `exp`（175:178）。  
- **group_by**：列名或语义字段 `side`。  
- **stats**：`count`, `min`, `max`, `mean`, `std`, `p10`, `p50`, `p90` 的子集（96）。  
- **windows**：`TestWindow` 或 `(start,end)`，自动判断 ns vs 秒（249:272）。

### AI 调用点  
**无**。

### 隐式规则 / 阈值 / 魔数  
- `max_rows` 默认 500_000（283）。  
- `asteval`：`minimal=True`, `use_numpy=True`, `max_statement_length=500`（167:171）。  
- `warning_events` 时间列用 `start_ns`（128:131）。  
- 百分位：p10/p50/p90（462:464）。

### 外部依赖  
- `FrameStore.conn`（sqlite3）；**numpy**、**asteval** 必填。  
- **无** `source_docs`/`memory`。

### Review 关注点  
- 全表 `LIMIT` 无时间范围，大数据库可能偏置样本。  
- 文档写的 `bag_frames`/`can_frames` 与 `TABLE_COLUMNS` 不一致。  
- 非数值 `field` 直接报错（406:414）。

---

## 模块：`problem_classifier.py`  
路径：`D:\RamboStar\idea\radarAnalyze\ai\problem_classifier.py`

### 定位  
将用户请求分到 **`diagnose` / `tune` / `verify` / `query`**，并猜测 **目标 ADAS 功能** 与 **参数桶/信号**，供编排器选分支。先**确定性正则**，不行再 **LLM**。

### 公开接口  
- `def to_dict(self) -> dict`（`ClassificationResult`，116:124）  
- `def __init__(self, router: ModelRouter | None = None) -> None`（154:155）  
- `def classify(self, problem: str, expected: str = "", memory_hint: str = "") -> ClassificationResult` — 159:187  

### 关键数据结构  
**`ClassificationResult`**：`task_type`, `confidence`, `target_function`（大写三字功能名或 `UNKNOWN`）, `focus_parameters`, `focus_signals`, `reasoning`。  
**`to_dict`**：confidence 保留两位小数。

### 处理流程  

1. 拼接 `problem` + `expected`；空则默认 `diagnose`, `UNKNOWN`（167:172）。  
2. **`_rule_based`**（191:257）优先级概要：  
   - 显式数值改动正则 `_EXPLICIT_VALUE_RE` + tune/verify 意图 → **`verify`**（201:210）  
   - `verify_hit` → **`verify`**（214:220）  
   - 强 tune 词 → **`tune`**（224:230）  
   - 弱 tune 且无 diagnose → **`tune`**（232:238）  
   - query 且无 diag/tune → **`query`**（240:247）  
   - diagnose 关键词 → **`diagnose`**（249:256）  
3. 无规则命中：`router is None` → 低置信 `diagnose` + `_guess_function` / `_guess_param_buckets`（178:185）；否则 **`_llm_classify`**。  
4. **`_guess_function`**：在 `ALL_FUNCTIONS`（BSD,LCA,DOW,RCW,RCTA,RCTB,FCTA,FCTB）中出现次数最多者（323:330）。  
5. **`_guess_param_buckets`**：按 `PARAM_KEYWORDS` 顺序匹配 ROI/SPEED/TTC/…（333:341）。  
6. **`_guess_signals`**：`_SIGNAL_LIKE_RE` 提取 `car_spd`、`trc_*` 等（352:359）。  
7. **LLM**：`SYSTEM_PROMPT`（130:142）+ 用户问题/预期/`memory_hint[:1500]`（265:272）；`router.simple(prompt, system=...)`（277）；`parse_json_from_llm`；校验 `task_type in TASK_TYPES`，`target_function in ALL_FUNCTIONS`（286:299）。

### AI 调用点  
- **Router**：`self.router.simple(prompt, system=self.SYSTEM_PROMPT)`（277）。  
- **Thinking**：代码未传 thinking 参数，是否 thinking 取决于 `ModelRouter.simple` 默认（本文件不可见）。  
- **解析**：`parse_json_from_llm(content, fallback={})`（286），字段规范化（301:310）。

### 隐式规则 / 阈值 / 魔数  
- 置信度示例：verify 0.92/0.85，tune 0.88/0.8，query 0.75，diagnose 0.85（204:255）。  
- 无 router 默认 diagnose confidence 0.3（181）；LLM 失败 0.2（281）。  
- `reasoning` 截断 500 字符（310）；`memory_hint` 截断 1500（272）。

### 外部依赖  
- `ModelRouter`、`parse_json_from_llm`、`ALL_FUNCTIONS`（`utils`）。  
- **无** FrameStore / `source_docs` / memory 文件读取（`memory_hint` 由调用方传入）。

### Review 关注点  
- 规则优先级：强 verify/tune 与 diag 同时出现时的语义（文档 222:224 说明强 tune 覆盖）。  
- `target_function` 仅靠关键词计数可能误判。  
- LLM 返回非法 `task_type` 时强制 `diagnose`（288:289）。

---

以上为六个文件对照源码的整理，可直接用于需求–实现 review。


================================================================================

# 第四章 信号映射与条件提取（signal_mapper / condition_extractor / causal_aligner / variable_query_planner）

以下为基于源码与样本 JSON 整理的实现说明（Ask 模式，仅阅读分析）。

---

## 模块：`signal_mapper.py`

### 定位

- **确定性 / 混合**：**纯确定性**（正则解析 C 源码），**不使用 AI**。
- **作用**：从 `RteComMapping.c` 解析 `RteComMapping_ReadSignal` / `RteComMapping_WriteSignal` 与赋值，建立 **CAN 信号名 ↔ 内部变量（短名 + 全路径）** 映射；可选从 `globalVariDef*.c` 追踪 **全局 `g_*` → RTE 结构前缀** 别名，写入 `variable_chains.json`；并生成人类可读的 `signal_chain.md`。

### 公开接口

（以下为模块级或类外可调用符号；`文件:行号` 为 `def` 行。）

| 签名 | 位置 |
|------|------|
| `def extract_signal_mapping(source_root: Path, output_dir: Path, rte_file: str = ...) -> dict` | `D:\RamboStar\idea\radarAnalyze\ai\signal_mapper.py:131` |
| `def extract_output_signal_mapping(source_root: Path, output_dir: Path, rte_file: str = ...) -> dict` | 同文件 `:221` |
| `def get_output_signals_for_function(func_name: str) -> list[str]` | 同文件 `:262` |
| `def resolve_internal_to_can(var_name: str, mapping: dict, chains: dict \| None = None) -> list[str]` | 同文件 `:267` |
| `def resolve_can_to_internal(can_signal: str, mapping: dict) -> list[str]` | 同文件 `:333` |
| `def build_signal_chain_summary(mapping: dict, output_dir: Path) -> str` | 同文件 `:367` |
| `def trace_variable_chains(source_root: Path, output_dir: Path, rte_file: str = ..., extra_files: list[str] \| None = None) -> dict` | 同文件 `:576` |
| `def load_variable_chains(output_dir: Path) -> dict` | 同文件 `:694` |

### 输入

- **主源文件**（默认相对 `source_root`）：`coem\GWM_B26\components\AswIf\ASW_IN\RteComMapping.c`（`extract_signal_mapping` / `extract_output_signal_mapping` / `trace_variable_chains` 中 `rte_file` 参数可改）。
- **变量链扫描**：硬编码 `_CHAIN_FILES` + `rglob` 匹配 `globalVariDef.c`、`globalVariDef_*.c`；可经 `extra_files` 追加。
- **来源**：均由调用方传入的 `source_root`（工程配置里的 `paths.source_code` 等）与 `output_dir`（通常为 `source_docs`）。

### 输出

**1. `signal_mapping.json`（`extract_signal_mapping`）**

| Key | 类型 | 含义 |
|-----|------|------|
| `source_hash` | `str` | 源文件 SHA256 **前 16 位** |
| `source_file` | `str` | 相对路径 |
| `mapping_count` | `int` | `mappings` 条数 |
| `mappings` | `list[dict]` | 每条含 `can_signal`, `internal_var`, `internal_full_path`, `transform`, `scaling`, `data_type`, `direction`（`read`） |
| `internal_to_can` | `dict[str, list[str]]` | 短内部名 → CAN 名列表 |
| `can_to_internal` | `dict[str, list[str]]` | CAN 名 → 短内部名列表 |
| `fullpath_to_can` | `dict[str, list[str]]` | **全路径**（如 `AdasStM.SteerWheelSpd`）→ CAN 名列表 |

示例结构见 `source_docs\signal_mapping.json` 前若干行（`mappings` 内多目标同一 CAN 等）。

**2. `output_mapping.json`（`extract_output_signal_mapping`）**

| Key | 类型 |
|-----|------|
| `source_hash`, `mapping_count`, `mappings`（`can_signal`, `expression`, `direction: write`）, `signal_to_expr`（CAN → 表达式列表） |

见 `source_docs\output_mapping.json` 前 100 行。

**3. `variable_chains.json`（`trace_variable_chains`）**

| Key | 类型 |
|-----|------|
| `struct_aliases`, `alias_details`, `ambiguous`, `raw_copies`, `rte_write_prefixes`, `scanned_files` |

见 `source_docs\variable_chains.json` 全文。

**4. `signal_chain.md`（`build_signal_chain_summary`）**：按关键词分类的 Markdown 表。

### 解析规则（正则 / AI）

**无 AI。** 关键正则（原文含义）：

1. **`_READ_SIGNAL_RE`**（`:19-21`）  
   `^\s*\(void\)\s*RteComMapping_ReadSignal\((\w+)\)\s*\(\s*&\s*(\w+)\s*\)`  
   → 捕获 **CAN 信号名**、**临时变量**（如 `ftmp`）。

2. **`_ASSIGN_RE`**（`:23-25`）  
   `^\s*([\w.]+(?:\[[\w\d]+\])?)\s*=\s*(.+?)\s*;`  
   → Read 块后最多 5 行内匹配赋值：**全路径左值**、**右值表达式**。

3. **`_WRITE_SIGNAL_RE`**（`:27-29`）  
   `\(void\)\s*RteComMapping_WriteSignal\((\w+)\)\((.+)\)\s*;`  
   → 写 CAN 的表达式。

4. **`_SCALING_RE`**（`:351`）  
   `\*\s*([\d.]+f?|System_\w+)`  
   → 从变换式里抽缩放因子（用于 `scaling` 字段）。

5. **`_PREFIX_RE` / `_SUFFIX_RE`**（`:446-447`）  
   - `^[bfug]_?|^(get_rda|set_rda|is_)`  
   - `(Flg|Flag|Sts|Status|Valid|Vld|Req|Val)$`（忽略大小写）  
   → `_extract_core_keyword` 用于模糊匹配时的“词干”。

6. **变量链**：`_STRUCT_COPY_RE` `^\s*(g_\w+)\s*=\s*\*(\w+)\s*;`；`_FUNC_SIG_RE` `void\s+(\w+)\s*\(([^)]+)\)`；`_PARAM_RE` `(\w+)\s*\*\s*(\w+)`；`_DIRECT_ASSIGN_RE` `^\s*(g_\w+)\s*=\s*([a-zA-Z_]\w*)\s*;`。

7. **写映射行清理**：`_parse_rte_write_mapping` 内 `re.sub(r'//.*$', '', stripped)` 去行尾注释。

**Read 路径启发式**（非正则）：`transform` 为 `bool` 若 `!= 0`/`== 0` 在表达式中；`passthrough` 若右值等于临时变量；否则保留表达式字符串；`data_type`：`bool` / `float`（`temp_var=="ftmp"`）/ 否则 `uint8`。

### 查询/解析优先级

**`resolve_internal_to_can`**（`:275-329`，文档字符串与实现一致）：

1. `internal_to_can` **精确**匹配 `var_name`  
2. `fullpath_to_can` **精确**匹配 `var_name`  
3. 点路径取 **最后一段** 再查 `internal_to_can`；或对 `fullpath_to_can` 的 key 做 `endswith("." + last)` / `fp == var_name`  
4. **`struct_aliases`（variable_chains）**：前缀候选 `parts[0]` 或 `parts[0].parts[1]`（当 `len(parts)>=3`），映射到 RTE 前缀后拼 `field`，再查 `fullpath_to_can`；失败则对 `fp2c` 找 `endswith("." + parts[-1])`  
5. **大小写不敏感**比对 `internal_to_can` 的 key 与 `last`  
6. **核心子串**：`_extract_core_keyword` 后长度 **≥5** 时在 `internal_to_can` 中双向 `in` 匹配  

**`resolve_can_to_internal`**：精确 → key 大小写不敏感。

**`_match_aliases`（变量链）**：对每条 `raw_copy`，相对 `rte_write_prefixes` 打分 **100**（param 在 prefix 路径中）/ **90**（`g_` 去掉后与路径段一致）/ **70**（param 仅大小写不同）；多前缀时 **仅当最高分严格胜出** 才采纳，否则记入 `ambiguous`。

### 边界条件 / 缓存失效

- **`signal_mapping.json`**：`source_hash`（SHA256 全文，取 hex **前 16 位**）与缓存一致则 **整文件跳过解析**；若缓存损坏则重算。命中缓存时若 **`signal_chain.md` 不存在** 会补建 `build_signal_chain_summary`。  
- **`output_mapping.json`**：同样 **`source_hash` 16 位** 一致则直接返回缓存。  
- **`RteComMapping.c` 不存在**：返回空 `mappings` 与空索引（read 路径还缺 `source_hash` 在 return 里——实现上 `:149-150` 无 `source_hash`，review 时注意）。  
- **`trace_variable_chains`**：**每次调用都重写** `variable_chains.json`，**无** hash/mtime 跳过逻辑（与 signal 缓存不同）。  
- **手动删除 JSON**：下次 `extract_*` 会重建；`signal_mapping` 还依赖源文件 hash。

### `fullpath_to_can` / `internal_to_can` / `can_to_internal` 双向索引（实现要点）

- **`_build_indices`**（`:100-128`）：遍历每条 `mapping`，对 `internal_var`、`can_signal`、`internal_full_path`（非空）分别 **去重 append** 到三个 dict。  
- **读方向**：业务多用 `resolve_internal_to_can`（短名或全路径或别名展开 → CAN 列表）；`resolve_can_to_internal` 为反向。  
- **一对多**：同一 CAN 可对应多个内部赋值目标，故值均为 **`list[str]`**。

### Review 关注点

- Read 解析只向后看 **最多 5 行**（`i+1`..`i+5`），复杂块可能漏赋值。  
- 注释行：以 `//`/`/*` 开头的行整行跳过；`/*` **不**做块注释跨行处理。  
- `trace_variable_chains` 无增量缓存，大仓库频繁调用可能浪费 I/O。  
- `extract_signal_mapping` 在源文件缺失时的返回结构与其他成功路径字段不一致。

---

## 模块：`condition_extractor.py`

### 定位

- **混合**：**AI 提取**结构化条件树 + **确定性**后处理（CAN 回填、缓存、mtime 失效）。

### 公开接口

| 签名 | 位置 |
|------|------|
| `class ConditionExtractor` · `def __init__(self, router: ModelRouter, project_root: Path, config: dict)` | `D:\RamboStar\idea\radarAnalyze\ai\condition_extractor.py:141` |
| `def extract(self, func_name: str, force: bool = False) -> dict` | 同文件 `:149` |
| `def format_conditions(conditions: dict) -> str` | 同文件 `:288` |

（类内 `_backfill_can_signals`、`_extract_with_ai` 等为内部方法。）

### 输入

- **源码路径**：`config["paths"]["source_code"]`；默认域来自 `config.get("source_domains", _DEFAULT_DOMAIN_SOURCES)`：  
  - `system_state`：`ASWIN_SystemState.c/h`  
  - `algorithm`：`adasFunc.c/h`、`paraDefine.h`  
  - `signal_chain`：`RteComMapping.c`  
- **每文件**：`extract_relevant_sections(text, build_keyword_variants(func_name), context_lines=15, max_chunks=30)`（`utils`）。

### 输出

缓存：`source_docs/{FUNC}_conditions.json`。顶层结构由 prompt 约束，样本见 `FCTB_conditions.json`：

- `function`, `system_state`（`state_values`, `transitions[]`）, `target_filter`, `detect_enable`, `ego_speed_ranges`, `target_speed_ranges`, `external_suppression[]`, `other_conditions[]`  
- `external_suppression` 项含：`source_system`, `condition`, `variable`, `can_signal`, `suppression_trigger`, `normal_value`, `effect`, `source` 等。

回填后可能多 `_can_resolved: bool`。

### 解析规则（正则 / AI prompt）

- **无业务正则解析条件树**；依赖 LLM。  
- **Prompt 识别特征**（`_EXTRACT_PROMPT`，`:34-135`）：  
  - 角色：「嵌入式 ADAS 代码分析专家」  
  - 要求严格 JSON，含 `system_state` / `target_filter` / `detect_enable` / `ego_speed_ranges` / `external_suppression` 等块  
  - **external_suppression** 变量规则：单个 C 变量名、禁止宏/函数名；OR 拆条；从 `RteComMapping.c` 找 CAN  
  - **极性规则专段**：`suppression_trigger` 必须对应「导致退出/抑制/回退」为真时的条件；列举 `!bXxxActiveFlg`、`==0`、`>80` 等模式与 **验证方法**（代入 if 是否执行抑制分支）

**调用链**：`extract` → `_extract_with_ai` → `self.router.complex(prompt, max_tokens=16384)` → 从首个 `{` 到最后 `}` 切 JSON（**非** `parse_json_from_llm`，尽管文件 import 了 `parse_json_from_llm` 当前未用于主路径）。

**常量**：`MAX_SOURCE_CHARS = 80_000`，`MAX_RETRIES = 2`。

### 极性规则（`suppression_trigger` / `normal_value`）

- 写在 **prompt** 中（`:120-135`）：`suppression_trigger` = 抑制**发生**时条件为真的写法；`normal_value` = 不抑制时的典型相反描述。  
- 强调 **“Active” 在变量名里不代表 TRUE 即抑制**（例如 `if(!bXxxActiveFlg)` → 抑制在 FALSE）。  
- **消费侧**：Orchestrator `_check_suppression_signals` 用 `suppression_trigger` 或回退 `threshold` 做数据占比判断（见下）。

### 阈值评估器支持的表达式（与本模块的关系）

**`condition_extractor` 自身不实现数值评估**。BLF/CAN 上评估 **`suppression_trigger`** 的逻辑在 **`orchestrator.py` 的 `_evaluate_threshold`**（`:955-1000`），与条件 JSON 配套使用，review 时应 **跨文件** 对齐：

- **布尔/离散字面**（归一化后）：`TRUE`, `FALSE`, `!=0`, `==0`, `==TRUE`, `==FALSE`, `==1`, `!=TRUE` 等（实现里 `thr_normalized` 集合）  
- **比较**：`^(>=?|<=?|==|!=)\s*([-\d.]+)` → `> >= < <= == !=` 对**数值**帧  
- **未解析**：回退为「非零帧占比」

**`_invert_threshold`**（`:1003-1013`）：用于极性交叉检查，仅覆盖少量离散映射（如 `TRUE`↔`== FALSE`）。

### 查询/解析优先级

- 缓存优先：`cache_path` 存在且非 `force` 且 **`_source_changed` 为假** 则直接读缓存。  
- `_source_changed`：任一域内源码文件 `st_mtime > cache_mtime` 则视为变更。

### 边界条件 / 缓存失效

- **mtime**：缓存文件时间 vs 各域源文件 mtime（**非**内容 hash）。  
- **`force=True`**：跳过缓存。  
- AI 失败：返回带 `error` / `raw_response` 的字典；成功才 `_backfill_can_signals` 与 `_save_cache`。

### Review 关注点

- 缓存一致性与 **AI 漂移**：同样代码不同次提取可能结构略有不同。  
- **CAN 回填**：仅当 `can_signal` 空或 `unknown`/`?`；`resolve_internal_to_can(..., chains)` 取 **`resolved[0]`** 单信号。  
- **阈值字符串**：条件 JSON 里可出现 `">= 0.5 && <= 21.0 km/h"` 等 **复合中文/逻辑**，与 `_evaluate_threshold` 的 **单行数值比较** 能力不对齐——评估器主要服务 **external_suppression 的 suppression_trigger** 一类简单串。

---

## 模块：`causal_aligner.py`

### 定位

- **确定性**：**无 LLM**。将 **代码侧** `CodePattern`（来自 `pattern_extractor`）与 **数据侧** `TemporalFeature`（来自 `temporal_analyzer`）对齐，判断 **模式触发条件在录制数据中是否同时成立**，并关联 **状态时间线** 上的邻近跳变。

### 公开接口

| 签名 | 位置 |
|------|------|
| `@dataclass class Interval` | `D:\RamboStar\idea\radarAnalyze\ai\causal_aligner.py:62` |
| `@dataclass class PatternHit` | 同文件 `:74` |
| `@dataclass class PatternEvidence` | 同文件 `:91` |
| `class CausalAligner` · `def __init__(self, signal_mapping: Optional[dict] = None, variable_chains: Optional[dict] = None)` | 同文件 `:134` |
| `def align(self, patterns: Iterable[CodePattern], features: dict[str, TemporalFeature], state_timeline: Optional[list[dict]] = None, func_name_filter: Optional[str] = None) -> list[PatternEvidence]` | 同文件 `:142` |
| `def format_evidence_block(evidence_list: list[PatternEvidence], max_hits_per_pattern: int = 5) -> str` | 同文件 `:512` |
| `def state_timeline_from_transitions(transitions: list[dict]) -> list[dict]` | 同文件 `:577` |

### 输入

- `CodePattern`：`trigger_condition`、`consequence_variables`、`pattern_type`、`adas_function`、位置信息等。  
- `features`：`TemporalFeature` 字典（含 `runs` 等）。  
- `signal_mapping` / `variable_chains`：供 `resolve_internal_to_can` 把 C 变量解析到 CAN/特征 key。  
- `state_timeline`：`[{"t": float, "field", "from", "to}, ...]`（如状态机迁移时刻）。

### 输出

- `list[PatternEvidence]`，`to_dict()` 含：`pattern`, `resolution`, `verdict`, `hit_count`, `hits`（每 hit：`t_start`/`t_end`/`duration_ms`/`signals_at_start`/`nearby_state_changes`）, `unresolved_signals`, `missing_signals`, `summary`。  
- `verdict`：`triggered` / `not_triggered` / `insufficient_data` / `unknown`。

### 解析规则（正则）

**`_parse_condition_terms`** 将 `trigger_condition` 按 `&&` 拆分，逐子句匹配：

- **`_NOT_RE`**：`'!\s*(?!=)\s*([A-Za-z_][\w.]*)'` → `(var, 0)`  
- **`_EQ_RE`**：`'([A-Za-z_][\w.]*)\s*==\s*([A-Za-z_0-9.]+)'` → 字面经 `_normalise_literal`（`TRUE/FALSE`→1/0，整数/浮点，否则字符串）  
- **`_NEQ_RE`**：类似 `!=` → `(var, ("!=", value))`  
- 否则若子句以标识符开头 → `(var, "truthy")`

**无 AI prompt。**

### “因果对齐”类型说明

- **时间对齐（核心）**：把模式触发条件转成各变量在 **特定取值上的连续时间 run**，对多变量做 **区间交集**（sweep-line `_intersect_two`），得到「条件同时成立」的时间段；即 **代码语义的布尔条件 ↔ 多通道信号 run 的时域交集**。  
- **事件/状态邻近关联**：对每个命中区间的起点，收集 `state_timeline` 上 **±`NEARBY_WINDOW_SEC`（0.5s）** 内的状态迁移，作为 **旁证**（非严格因果推断）。  
- **不是**基于格兰杰因果或贝叶斯网络；模块注释明确为 **circumstantial evidence**。

### 查询/解析优先级

**`_resolve_feature_key`**：

1. `var in features`  
2. 最后一段 `last in features`  
3. `key.endswith("." + last)` 或 `endswith("." + var)`；或最后一段 **大小写不敏感**  
4. `resolve_internal_to_can` → 候选 CAN；在 `features` 中找精确或 `_0x` 截断后与 leaf 匹配  
5. 仍无数据但解析到 CAN → `__missing__`；完全不能解析 → `None`

**触发值匹配**：`!=` 元组 → `r.value != target`；`truthy` → 非 `0/0.0/False/None`；否则 `r.value == trigger`。

### 边界条件 / 缓存失效

- 本模块 **无缓存**。  
- `MIN_TRIGGER_DURATION_SEC = 0.0`：理论上允许零长区间（若上游 run 产生）。  
- `_value_at` 对边界 **优先下一段 run**，避免交集起点落在错误值上。

### Review 关注点

- 只支持 **AND** 合取与有限子句模式；**OR/括号嵌套** 未完整建模。  
- `func_name_filter` 过滤 `adas_function`。  
- 若 `unresolved` 或 `missing` 任一非空，直接 **不计算交集**，`verdict` 为 insufficient/unknown。

---

## 模块：`variable_query_planner.py`

### 定位

- **AI + 确定性校验/回退**：LLM 根据 **问题 + L6 代码知识 + 表字段清单** 规划 **DataProbe 查询**；失败时用 **`_fallback_plan`**。

### 公开接口

| 签名 | 位置 |
|------|------|
| `class QueryPlan` · `def __init__(self, spec: dict)` | `D:\RamboStar\idea\radarAnalyze\ai\variable_query_planner.py:120` |
| `def is_valid(self) -> bool` / `def to_dict(self) -> dict` / `def to_query_args(self) -> dict` | 同文件 `:131`–`:166` |
| `class VariableQueryPlanner` · `def __init__(self, router, memory_system, project_root: Path)` | 同文件 `:180` |
| `def plan(self, problem: str, expected: str, func_name: str, fail_type: str, focus_params: list[str], store, *, max_queries: int = 6, use_thinking: bool = False) -> list[QueryPlan]` | 同文件 `:187` |
| `def render_probe_results_for_prompt(plans: list[QueryPlan], results: list[dict], max_chars: int = 6000) -> str` | 同文件 `:358` |

### 输入

- `problem`, `expected`, `func_name`, `fail_type`, `focus_params`（来自分类阶段）。  
- `store`：SQLite，用于 `COUNT(*)` 与列清单渲染。  
- L6：`memory.render_code_knowledge_for_context(func_name, max_chars=4000)`。

### 输出

- **`list[QueryPlan]`**，每项 `to_query_args()` 供 **`DataProbe.query`**：`field`, `table`, `stats`, 可选 `group_by`, `filter`（**不含** `reasoning`）。  
- JSON 约定：顶层 **`{"queries": [ {...}, ... ]}`**。

### 解析规则（AI prompt）

**`_SYSTEM_PROMPT`**（`:52-67`）识别特征：  
- 角色：「雷达数据诊断的查询规划员」  
- 必须输出严格 JSON，`key = "queries"`  
- 布尔建议用 **`&` `|` `~`**  
- 最多 **6** 条查询  

**`_USER_TEMPLATE`**（`:69-111`）：含「问题/预期/功能/fail_type/焦点参数/**已学代码知识（L6）**/可查表与字段/语义字段 `side`·`in_window`/已有基础 evidence 勿重复/输出 JSON 示例（含 `dist_y + 0.25 * 2.0` 类算术字段）」。

**路由**：`self.router.chat(..., complexity="complex", temperature=0.2, max_tokens=1800, thinking=use_thinking)`。

**解析**：`parse_json_from_llm(raw, fallback={})`，取 `queries` 列表，**截断** `max_queries`，每项 `QueryPlan(spec)` 且 `is_valid()`。

**`QueryPlan` 约束**：  
- `ALLOWED_TABLES = ("radar_objects", "radar_debug", "warning_events")`  
- `ALLOWED_STATS = {"count","min","max","mean","std","p10","p50","p90"}`  

### Phase 3.57「按需证据采集」（编排侧）

**位置**：`orchestrator.py` `:221-268`（注释明确 Phase 3.57）。

**流程**：

1. 读配置 `config["ai"]["variable_probe"]`：`enabled`（默认真）, `max_queries`, `use_thinking`, `max_chars`。  
2. `VariableQueryPlanner.plan(..., store, ...)` 用 **问题 + L6 `render_code_knowledge_for_context`** + **各表列名与行数** 让模型决定查哪些 **字段或算术表达式**、过滤与分组。  
3. `DataProbe(store, windows=windows or [])`，对每条 `QueryPlan` 调用 **`probe.query(**qp.to_query_args())`**。  
4. **`render_probe_results_for_prompt`** 生成 Markdown，进入后续 **Expert Panel** 上下文（与 `ContextBudget` 等后续阶段衔接，具体注入点可在 orchestrator 中继续跟 `probe_section`）。

**设计意图**（模块 docstring）：避免只依赖手写 extractor；让 L6 中的变量/阈值驱动 **自定义派生量**（如 ROI 边界）的统计。

### 查询/解析优先级

1. LLM 返回的 `queries`（至多 `max_queries`）  
2. 过滤：仅 **合法 table + 非空 field + 非空 stats**  
3. 若无效或空：**`_fallback_plan`** —— 始终尝试 `dist_y` + `group_by: side` + `filter: in_window`；`focus_params` 含 `TTC` / `ROI`/`ANGLE` 时追加对应模板；`reasoning` 附加 `planner fallback: <reason>`

### 边界条件 / 缓存失效

- **无磁盘缓存**；每次诊断运行重新 plan（除非上层跳过）。  
- Router 异常或 JSON 坏：**fallback**。

### Review 关注点

- L6 为空时 prompt 为「(暂无代码知识)」，计划质量依赖 fallback。  
- 列清单 **硬编码** `_COLS_*`，注释要求与 `FrameStore.TABLE_COLUMNS` 同步。  
- `max_tokens=1800` 与复杂查询数量的平衡。

---

## JSON 样本结构速览（路径均为绝对路径）

- **`D:\RamboStar\idea\radarAnalyze\source_docs\signal_mapping.json`**：`source_hash`, `mappings[]`（`can_signal`/`internal_full_path`/…）, 顶层含三索引（样本前 100 行已体现 `mappings` 与重复 CAN）。  
- **`D:\RamboStar\idea\radarAnalyze\source_docs\variable_chains.json`**：`struct_aliases`, `alias_details`, `raw_copies`, `rte_write_prefixes`, `scanned_files`。  
- **`D:\RamboStar\idea\radarAnalyze\source_docs\FCTB_conditions.json`**：`system_state.transitions`, `target_filter`, `detect_enable`, `ego_speed_ranges`, 及后续 `external_suppression` 等（前 150 行覆盖状态机与速度段）。  
- **`D:\RamboStar\idea\radarAnalyze\source_docs\output_mapping.json`**：`mappings[]` 的 `write` 方向与 `signal_to_expr`。

---

以上可直接用于需求–实现对照 review；若需把 **`_evaluate_threshold`** 记入条件提取「实现说明」文档，建议在文档中 **显式标注实现位于 `orchestrator.py`**，避免误以为在 `condition_extractor.py` 内。


================================================================================

# 第五章 专家面板与数据查询（expert_panel / data_query_engine / problem_classifier 补充）

以下为基于对 `expert_panel.py`、`data_query_engine.py`、`problem_classifier.py` 全文及 `cli.py` / `orchestrator.py` 相关调用链阅读后的实现说明（行号均来自当前工作区文件）。

---

## 模块：`expert_panel.py`

### 定位

- 多专家研讨：`ExpertPanel.run_panel` 固定 **3 轮**（`ROUND_COUNT = 3`，约 207 行），但 **V3 按 `fail_type` 子集选专家**（约 191–197、245 行），**不总是 5 人**；`FP`/`FN`/`DELAY`/`STATE` 各 3 人，`OTHER` 才 5 人全上。
- 与 `orchestrator` 配合：`data_summary` 实为带 TPE/抑制/输出/条件表/时间线等的拼装上下文（见 `orchestrator.py` 约 449–491 行）。

### 公开接口

| 签名 | 位置 |
|------|------|
| `def __init__(self, router: ModelRouter, config: dict, project_root: Path)` | `D:\RamboStar\idea\radarAnalyze\ai\expert_panel.py:209` |
| `@staticmethod def select_experts(fail_type: str = "OTHER") -> dict[str, dict]` | 同文件 `219:223` |
| `def run_panel(self, problem: str, expected: str, func_name: str, data_summary: str, memory_context: str = "", on_status=None, fail_type: str = "OTHER", task_type: str = "diagnose") -> dict` | 同文件 `225:235` |

类内其余方法均为 `_` 前缀私有方法（如 `_parallel_expert_analyze` 296 行等）。

### 5 位专家的角色定义

专家定义集中在模块级字典 `EXPERTS`（`22:151`），键为 `expert_id`，用于 Round2 JSON 的 `questions` 键名及附录文件名中的小节标题。

| expert_id | 角色名（`name`） | 职责 / domain（要点） | system prompt 要点（摘录） | 读的输入 |
|-----------|------------------|------------------------|----------------------------|----------|
| `signal_chain` | 信号链路专家 | CAN→RteComMapping→内部变量→条件 | 查条件表中的 CAN；追溯链路；禁止套用其他功能映射；输出须有数据支撑 | `case_context` + 截断后的 `source_files` 源码（`_load_expert_sources`） |
| `algorithm` | 算法逻辑专家 | `adasFunc.c` 条件与阈值 | 逐条比对条件；**不满足时沿代码追到 CAN** | 同上 |
| `system_state` | 系统状态专家 | 双状态机与使能 | 区分观测层 enable 与代码层关闭原因；追到信号 | 同上 |
| `perception` | 感知与目标专家 | 目标属性与过滤 | m/s vs km/h；`radar_objects` 各功能 `*_flag` 为观测输出 | 同上 |
| `architecture` | 架构专家 | 左右雷达与输出合并 | 简洁，仅相关架构因素 | 同上 |

主持人（非“第 6 位专家”）使用 `MODERATOR_SYSTEM`（`155:188`）：**因果链 L4→L1**、TPE `verdict=triggered/not_triggered` 规则、禁止无数据假设等。

### 3 轮迭代流程

- **Round 1（独立分析）**  
  - **输入**：`_build_case_context`（`560:598`）拼 `task_type` 说明、`problem`/`expected`/`func_name`、`data_summary`（截断 20000）、可选 `memory_context`（5000）。  
  - **每专家**：`_expert_analyze`（`366:416`）user prompt 含「问题与数据」「源码」；要求先读 **TPE**、填条件表、硬约束（TPE 行号、`trigger_variables`、`not_triggered` 等）。  
  - **输出**：各 `expert_id → markdown 字符串`。  
  - **并行**：`ThreadPoolExecutor`，最多 `MAX_PARALLEL = 5`（`217`、`311`）。  
  - **Prompt 风格**：结构化小节（**TPE 一致性 / 条件检查表 / 结论 / 需确认**）。

- **Round 2（交叉质疑 + 回应）**  
  - **主持人**：`_moderator_challenge`（`444:485`）输入截断的 `case_context[:8000]` + 全部 R1 意见；**输出 JSON**：`contradictions`、`gaps`、`questions`（按 5 个固定 key）、`preliminary_consensus`、`key_dispute`；空追问会被过滤（`484`）。  
  - **专家回应**：仅对 `questions` 中非空项 `_parallel_expert_respond`（`327:359`）；`_expert_respond`（`418:440`）在原文后追加 `### 补充分析(R2)\n{resp}`（`276`）。  
  - **若主持人未产出任何追问**：不调用回应，R2 仅保留 challenge 字典。  
  - **Prompt 风格**：追问 + 其他专家摘要（12000）+ 本人分析（6000）+ 源码，**≤500 字**。

- **Round 3（综合收敛）**  
  - `_moderator_synthesize`（`487:556`）：输入问题摘要、全文意见（截断 30000）、矛盾/遗漏 JSON。  
  - **输出**：单一 markdown **最终诊断**（`final_verdict`）。  
  - **Prompt 风格**：强制章节（**数据溯源规则 / 根因 / 时序耦合 TPE 表 / 条件检查汇总 / 证据链 / 数据链路 / 测试窗口 / 场景差异 / 修复建议 / 置信度**），并再次强调 TPE 行号锁定与权威阈值。

`run_panel` 返回值（`287:292`）：`expert_opinions`、`moderator_challenges`、`final_verdict`、`rounds`。

### 数据溯源规则

- **嵌入专家 R1**：`_expert_analyze` 硬约束要求沿用 TPE 的 `file:line`、`trigger_variables`，禁止把 `not_triggered` 当根因（`394:402`）。  
- **嵌入主持人 R3**：`**数据溯源规则**`：结论须标明出处（`"TPE 因果对齐"` / `"抑制信号实测"` / `"条件检查表"` / `"帧分析数据"` / `"BAG数据"` / `"权威阈值参考"`）；禁止未提供信号名与编造值；抑制实测若写「不满足」则不得列为根因；阈值须与权威参考一致（`504:507`）。  
- **观测 vs 根因**：各专家 `system` 与 R1 user 中多次强调「关键事实/时间线/TPE」为据；`MODERATOR_SYSTEM` 明确 L3 为结果、须下到 L2/L1（`155:188`）。  
- **上游拼装**：具体「抑制信号实测」「权威阈值」等段落由 `orchestrator` 写入 `data_summary`（如 `391:432`），非本文件生成。

### 产出格式

- **`expert_opinions.md`** 由 **`orchestrator._save_expert_appendix`**（`1439:1454`）写入，非 `expert_panel` 内写文件。  
- **结构**：  
  1. 标题 `# 专家面板详细记录`  
  2. 按 **`panel_result["expert_opinions"]` 字典迭代顺序**，每键一节：`## {expert_id}` + 该专家完整 markdown（含 R1 及可能的 `### 补充分析(R2)`）  
  3. 若有 `moderator_challenges`：`## 主持人审查` + `### 矛盾点` / `### 遗漏` / `### 关键争议`  
- **综合报告**：主报告中的诊断正文来自 `panel_result["final_verdict"]`（`orchestrator.py` 约 492、505–511 行），与 `expert_opinions.md` 分离；附录不含 `final_verdict` 全文。

### AI 调用

- **Thinking**：`self._thinking` 来自 `router.thinking_mode`（`215`）。  
  - R1 专家、R2 专家回应、R2 主持人 challenge：`thinking = (self._thinking == "full")` → 仅 **`full` 时** `router.complex(..., thinking=True)`（`414–415`、`438–439`、`474–475`）。  
  - R3 综合：`thinking = self._thinking in ("synth", "full")`（`554–555`）。  
- **complex vs simple**：本文件**仅使用** `router.complex`（远程大模型路径，`model_router.py` 152–168），**无** `simple` 调用。

### Review 关注点

- **`fail_type` 与专家数**：文档若写死「5 专家」需与 `select_experts` 及 `_FAIL_TYPE_EXPERTS` 对齐。  
- **Round2 JSON**：`questions` 固定 5 key，但**实际被选中的专家可能少于 5**；主持人仍可能被 prompt 引导写满 key，需看解析后过滤逻辑（`484`）。  
- **TPE 与上游**：`expert_panel` 假设 `data_summary` 已含 TPE/抑制等；若上游未注入，专家 prompt 中的硬约束仍生效但证据可能空。  
- **线程与缓存**：源码按路径缓存于 `_source_cache`（`214`、`600–616`）；并行 R1/R2 同进程安全依赖 CPython GIL 下纯 dict 读；需关注单专家失败时占位字符串（`323`、`356`）。

---

## 模块：`data_query_engine.py`

### 定位

- **自然语言查数**：BLF+DBC / BAG → `FrameStore`，再 **AI 规划信号** → 校验/纠错 → 抽时间线 → **AI 作答**；模块 docstring 流程（`10:16`）与 `cli.py` 的 `query` 模式一致。

### 公开接口

| 签名 | 位置 |
|------|------|
| `def __init__(self, router: ModelRouter, config: dict, project_root: Path)` | `D:\RamboStar\idea\radarAnalyze\ai\data_query_engine.py:105` |
| `def run_query(self, case_dir: Path, question: str, on_status=None) -> str` | 同文件 `122:127` |

**`run_query` 行为概要**（`122:164`）：  
1. 定义内部 `status(step, detail)`，将 `(step, detail)` 传给 `on_status`（若提供）。  
2. `parse`：`store, dbc = self._parse_data`（`load_case_data`）。  
3. `inventory`：`_build_signal_lookup`、`_build_bag_inventory`、`_build_knowledge_context`。  
4. `plan`：`_plan_query` → `_validate_plan`。  
5. `extract`：`data_text = self._extract_data`。  
6. `answer`：`answer = self._answer_question`。  
7. `store.close()`，返回 **markdown 字符串** `answer`。

### 查询流程（对应 `cli.py` 的 `steps_display`）

`cli.py` `237:243` 与 `engine.run_query` 内 `status` 调用一致：

| 步骤 key | CLI 展示文案 | `data_query_engine` 中动作 |
|----------|----------------|---------------------------|
| `parse` | Parsing data | `_parse_data` → `parsers.case_loader.load_case_data`（`168:172`），status `"Loading data..."` |
| `inventory` | Scanning signals | 构建 `signal_lookup`/`signal_table`、`bag_inventory`、知识上下文；status 含信号数量（`136:141`） |
| `plan` | Understanding question | `_plan_query`（AI JSON）；`_validate_plan` 模糊/子串纠正信号名；status 含 `query_type`、summary、信号数（`143:152`） |
| `extract` | Extracting data | `_extract_data`：CAN 时间线、BAG 字段、`radar_objects` 告警目标、`include_warning_events` 时 `query_warning_events`（`154:157`） |
| `answer` | Analyzing | `_answer_question`（`159:161`） |

### 调用的其他模块

- **本文件未使用** `SignalMapper`、`ConditionExtractor`、`DataProbe`（grep 无匹配）。  
- **实际依赖**：  
  - `parsers.case_loader.load_case_data`（`169`）  
  - `FrameStore` 接口：`get_signal_inventory`、`get_bag_topics`、`query_can_by_name`/`query_can_by_id`、`query_bag_by_topic`、`query_objects_with_warning`、`query_warning_events`、`get_can_ids`、`close` 等（`392:523`）  
  - `ai.model_router.ModelRouter`、`ai.utils.parse_json_from_llm`、`ai.utils.ALL_FUNCTIONS`（`265`）  
  - 可选：`memory.memory_system.MemorySystem` 懒加载，用于 `render_code_knowledge_for_context`（`112:120`、`296:304`）  
  - 静态数据：`source_docs/signal_mapping.json`、`radar_knowledge.json`、各 `{FN}_conditions.json`、`{FN}.md`（`220:307`）

### 返回格式

- **返回值类型**：`str`，为模型生成的 **Markdown**（`_answer_question` `616:617`；失败时固定中文提示）。  
- **内容规范**（由 `_ANSWER_PROMPT` `83:99` 约束）：直接回答、时间段佐证、关联查询列触发时段、表格/列表、不足时说明缺失、总结 ≤500 字；另可拼接 `## 参考知识`（`614:615`，截断 4000）。  
- **非结构化中间产物**：`data_text` 为提取的 CAN/BAG/雷达目标/告警事件的文本块，用户不可见，仅作为 answer 步骤输入。

### AI 调用

- **`_plan_query`**、`__answer_question`**：均 `self.router.complex(prompt, system=_QUERY_SYSTEM)`，**未传 `thinking`**，故为默认 `thinking=False`（`320`、`616`）。  
- **无 `router.simple`**：查询管线两步均为 **remote complex**。

### Review 关注点

- **规划 JSON 可信度**：`_validate_plan` 在信号不在 inventory 时仍可能保留 `not_found` 项，抽取阶段会打 ⚠（`377:385`、`407:408`）。  
- **知识上下文**：问题中大写功能名子串匹配 `ALL_FUNCTIONS` 才附加条件/文档/L6（`265:267`）；未提功能名则知识块偏薄。  
- **`data_text` 截断**：`>12000` 字符截断（`606:607`），长录可能影响答案完整性。  
- **与全量诊断管线边界**：query 模式不跑 TPE/专家面板；仅回答数据问题。

---

## 模块：`problem_classifier.py`

### 定位

- **任务路径分流**：将用户描述归为 `diagnose` / `tune` / `verify` / `query`（`7:18`、`37`），供 `orchestrator` 在 Phase 1.5 使用（`orchestrator.py` `119:137`）。  
- **设计**：**先规则、后 LLM**（`20:21`、`164:187`）；无规则命中且无 router 时默认 `diagnose`（`178:185`）。

### 公开接口

| 签名 | 位置 |
|------|------|
| `@dataclass class ClassificationResult`（字段见 `108:114`） | `D:\RamboStar\idea\radarAnalyze\ai\problem_classifier.py:107:114` |
| `def to_dict(self) -> dict` | 同文件 `116:124` |
| `def __init__(self, router: ModelRouter \| None = None)` | 同文件 `154:155` |
| `def classify(self, problem: str, expected: str = "", memory_hint: str = "") -> ClassificationResult` | 同文件 `159:164` |

模块导出（`375:380`）：`ClassificationResult`、`PARAM_KEYWORDS`、`ProblemClassifier`、`TASK_TYPES`。  
内部方法：`_rule_based`（`191`）、`_llm_classify`（`262`）。  
模块级辅助函数（可被外部 import，但属实现细节）：`_any_match`（`316`）、`_guess_function`（`323`）、`_guess_param_buckets`（`333`）、`_guess_signals`（`352`）、`_normalise_list`（`362`）。

### 分类逻辑

- **关键词/正则（优先）**（`_rule_based` `191:258`）：  
  - **显式数值改动** + tune/verify 倾向 → `verify`（`201:210`，`_EXPLICIT_VALUE_RE` `65:72`）  
  - **verify 句式** → `verify`（`214:220`）  
  - **强 tune 词** → `tune`（`224:230`）  
  - **弱 tune** 且无 diagnose 命中 → `tune`（`232:237`）  
  - **query 词** 且无 diagnose/tune → `query`（`240:247`，`_QUERY_HINTS` `75:78`）  
  - **diagnose 词** → `diagnose`（`249:256`，`_DIAGNOSE_HINTS` `81:87`，含未触发/误触发/延迟/状态异常等）  
  - 全未命中 → `None`，交 LLM  
- **LLM 兜底**（`_llm_classify` `262:311`）：`SYSTEM_PROMPT`（`130:142`）+ user 含问题/预期/`memory_hint`；`router.simple`（**本地 simple**）；解析 JSON，校验 `task_type ∈ TASK_TYPES`，`target_function` 须在 `ALL_FUNCTIONS` 否则 `_guess_function`。  
- **功能识别**：  
  - 规则路径：`_guess_function` 统计 `ALL_FUNCTIONS` 在全文出现次数（`323:330`）  
  - LLM 路径：模型输出 `target_function`，非法则回退 `_guess_function`（`296:299`）  
- **输出**：`ClassificationResult`：**无**单独的「FP/FN/DELAY/STATE」字段；「漏报/误报/延迟」等通过命中 `_DIAGNOSE_HINTS` 将 **`task_type` 定为 `diagnose`**，精细失效类型由 **`orchestrator._understand_problem` 的 `func_info["fail_type"]`** 等上游决定，不在本分类器输出。

### Review 关注点

- **优先级交互**：强 tune 可压过同时出现的 diagnose 词（`222:224`）；弱 tune 与 diagnose 并存时 diagnose 优先（`232` 条件 `not diag_hit`）。  
- **query vs diagnose**：带「列出/查看」且同时有「没触发」类词时，可能先被 diagnose 命中（`249` 在 query 分支之后独立判断——实际顺序是 query 要求 `not diag_hit`，diag 后处理会命中；若同时有 query_hit 与 diag_hit，query 分支不满足，`diag_hit` 会落到 diagnose）。  
- **空输入**：直接 `diagnose` + `UNKNOWN`（`167:172`）。  
- **LLM 失败**：异常时低置信 `diagnose`（`279:284`）。  
- **与专家面板**：`fail_type` 不由本模块提供；专家子集由 `ExpertPanel.select_experts(fail_type)` 与 orchestrator 传入的 `func_info` 决定。

---

以上内容可直接用于后续「需求 ↔ 实现」对照 review。若需把 `orchestrator` 中 `data_summary` 拼装与 `expert_opinions.md` 落盘也纳入同一份 checklist，可再单独开一节对照 `orchestrator.py` 344–515、1439–1454 行。


================================================================================

# 第六章 代码学习与时序模式引擎（code_learner / tpe / pattern_extractor / visualizer）

说明：`pattern_extractor.py` 将**源码行为模式**写入 `source_docs/code_patterns.json`（或 `cache_dir` 下的同名文件）；`memory/patterns.json` 由 `memory/memory_system.py` 的 L3 模式记忆维护，与 `PatternExtractor` 无直接写入关系。下面按代码事实撰写文档。

---

## 模块：`code_learner.py`

路径：`D:\RamboStar\idea\radarAnalyze\ai\code_learner.py`

### 定位

- 模块注释与类文档（```1:26:D:\RamboStar\idea\radarAnalyze\ai\code_learner.py```）定义其为项目中**唯一**负责「读源码、抽知识」的引擎。
- **增量 JSON 学习**（`learn`）供 Auto-Dream Phase 0 使用：按 **(function × focus)** 二维网格轮转，结果写入 `memory/code_knowledge/<FUNC>.json`。
- **Markdown 概览**（`ensure_overview_docs`）供 orchestrator 启动时补齐 `source_docs/<FUNC>.md`（按 per-function 片段 hash 决定是否重生成）。

### 公开接口

**类 `CodeLearner`**

- `def __init__(self, router: ModelRouter, config: dict, project_root: Path)` — `303:330:D:\RamboStar\idea\radarAnalyze\ai\code_learner.py`
- `def learn(self, status_cb: Optional[Callable[[str, str], None]] = None, force_pairs: Optional[int] = None) -> dict` — `334:431:D:\RamboStar\idea\radarAnalyze\ai\code_learner.py`
- `def ensure_overview_docs(self, funcs: Optional[list[str]] = None, force: bool = False, status_cb: Optional[Callable[[str, str], None]] = None) -> dict` — `433:511:D:\RamboStar\idea\radarAnalyze\ai\code_learner.py`

（带 `_` 前缀的方法为内部实现，此处不列为对外 API。）

### 学习单元

- **组合规模**：`learn` 中 `all_pairs = [(fn, fc) for fc in self.rotation_focuses for fn in self.priority_functions]`（```368:373:D:\RamboStar\idea\radarAnalyze\ai\code_learner.py```）。默认 `rotation_focuses` 为 4 个 focus、`priority_functions` 默认 8 个功能名 → **4×8=32** 个 **(func, focus)** 槽位；实际是否学完取决于预算与源码变化。
- **focus 与提取目标**（模块头注释 + `FOCUSES` / `FOCUS_FILES`，```15:19:D:\RamboStar\idea\radarAnalyze\ai\code_learner.py``` 与 ```41:72:D:\RamboStar\idea\radarAnalyze\ai\code_learner.py```）：
  - **alarm_logic**：报警触发/取消/退出、迟滞、延时、抑制等；Prompt 要求 JSON 含 `trigger_conditions` / `cancel_conditions` / `exit_conditions` / `hysteresis` / `timers` / `suppression`（```131:165:D:\RamboStar\idea\radarAnalyze\ai\code_learner.py```）。
  - **calculation_chain**：关键变量计算、数据链、所用阈值；JSON 含 `key_variables` / `derivation_chain` / `thresholds_used`（```167:207:D:\RamboStar\idea\radarAnalyze\ai\code_learner.py```）。
  - **output_chain**：内部变量 → ASWOUT → RteComMapping → CAN；JSON 含 `outputs` / `merge_strategy` / `external_gating`（```210:241:D:\RamboStar\idea\radarAnalyze\ai\code_learner.py```）。
  - **state_machine**：状态编号语义、转换、双状态机交互；JSON 含 `states` / `transitions` / `entry_functions` / `dual_state_interaction`（```244:280:D:\RamboStar\idea\radarAnalyze\ai\code_learner.py```）。

### 输入

- **源码根目录**：`self.source_root = Path(config["paths"]["source_code"])`（```322:322:D:\RamboStar\idea\radarAnalyze\ai\code_learner.py```）。
- **`learn` 每条 focus 读取的文件**：`FOCUS_FILES[focus]` 中的相对路径列表（Windows 下与源码树一致；```48:72:D:\RamboStar\idea\radarAnalyze\ai\code_learner.py```），**不**读取 `config.paths.key_source_files`（后者仅用于概览）。
- **`ensure_overview_docs`**：读取 `config.paths.key_source_files` 所列全部文件（```535:550:D:\RamboStar\idea\radarAnalyze\ai\code_learner.py```），再按 `FUNC_KEYWORDS` 抽片段（```77:88:D:\RamboStar\idea\radarAnalyze\ai\code_learner.py```）。
- 代码中**未**出现 `source_domains` 配置项。

### 输出

**`memory/code_knowledge/<FUNC>.json`（如 `FCTB.json`）**

- 顶层 **`_meta`**（`_merge_knowledge` 写入）：`function`、`last_updated`、`learned_focuses`（已学过的 focus 列表）、`source_hashes`（每个 focus 对应聚合源码 hash）（```710:718:D:\RamboStar\idea\radarAnalyze\ai\code_learner.py```）。
- 顶层 **以 focus 名为键** 的节（如 `alarm_logic`、`calculation_chain`），内容为模型返回 JSON 经合并后的结构；列表项可带 `_learned_at`（```797:797:D:\RamboStar\idea\radarAnalyze\ai\code_learner.py```）。
- 参考样例前部：`D:\RamboStar\idea\radarAnalyze\memory\code_knowledge\FCTB.json`（`_meta` + `alarm_logic.trigger_conditions[]` 等）。

**`source_docs/code_patterns.json`**

- **不由 `code_learner` 写入**；由 `pattern_extractor.PatternExtractor` 的缓存逻辑写入（见下文模块说明）。

**`memory/code_knowledge/learning_state.json`**

- 默认结构（`_read_state`）：`cursor`、`warmup_done`、`pair_hashes`、`learned_pairs`、`total_learned_pairs`（```761:767:D:\RamboStar\idea\radarAnalyze\ai\code_learner.py```）。
- `learn` 结束后更新：`cursor`、`warmup_done`（冷启动且学到数量达标时置 True）、`last_learn_at`、`total_learned_pairs`；每次成功学习会更新 `pair_hashes["func/focus"]` 并把 `func/focus` 记入 `learned_pairs`（```413:420:D:\RamboStar\idea\radarAnalyze\ai\code_learner.py```、```629:633:D:\RamboStar\idea\radarAnalyze\ai\code_learner.py```）。

**`source_docs/.overview_hashes.json`**

- 各功能 MD 对应 snippets 的 sha256 前 16 位，用于跳过未变更的概览（```513:531:D:\RamboStar\idea\radarAnalyze\ai\code_learner.py```）。

### AI prompt

- **按 focus 差异**：使用 `_FOCUS_PROMPT_TEMPLATES[focus]`（用户任务描述 + 期望 JSON 形状不同）与 `_FOCUS_SYSTEMS[focus]`（角色设定不同）（```131:289:D:\RamboStar\idea\radarAnalyze\ai\code_learner.py```、`664:671:D:\RamboStar\idea\radarAnalyze\ai\code_learner.py`）。
- **Overview（MD）**：独立 `_OVERVIEW_SYSTEM_PROMPT` + `_OVERVIEW_PROMPT`，固定 Markdown 章节结构（```92:126:D:\RamboStar\idea\radarAnalyze\ai\code_learner.py```），`router.complex(..., thinking=False)`（```560:566:D:\RamboStar\idea\radarAnalyze\ai\code_learner.py```）。
- **warmup_pairs vs pairs_per_dream**：`warmup_done` 为 False 时用 `warmup_pairs`，否则用 `pairs_per_dream`；可被 `force_pairs` 覆盖（```360:364:D:\RamboStar\idea\radarAnalyze\ai\code_learner.py```）。配置来自 `config["auto_dream"]["code_learning"]`，默认 `warmup_pairs=8`、`pairs_per_dream=2`（```308:311:D:\RamboStar\idea\radarAnalyze\ai\code_learner.py```）。
- **max_snippet_chars**：默认 40000，用于截断送入模型的片段（```319:319:D:\RamboStar\idea\radarAnalyze\ai\code_learner.py```、`616:617:D:\RamboStar\idea\radarAnalyze\ai\code_learner.py`）；`_extract_snippets` 另有 per-file 预算（```650:650:D:\RamboStar\idea\radarAnalyze\ai\code_learner.py```）。
- **use_thinking**：传入 `router.complex(..., thinking=self.use_thinking)`，默认 False（```320:320:D:\RamboStar\idea\radarAnalyze\ai\code_learner.py`、`669:673:D:\RamboStar\idea\radarAnalyze\ai\code_learner.py`）。

### 缓存与去重

- **源码 hash**：对当前 focus 所涉各文件分别 sha256，再拼接排序后做 sha256，取前 16 位为 `combined_hash`；若与 `state["pair_hashes"][func/focus]` 相同则 **跳过**（```584:608:D:\RamboStar\idea\radarAnalyze\ai\code_learner.py```）。
- **合并去重**：`_merge_knowledge` 对 list 按 `id` 合并；无 `id` 时 `_auto_id` 生成（```724:743:D:\RamboStar\idea\radarAnalyze\ai\code_learner.py```、`778:808:D:\RamboStar\idea\radarAnalyze\ai\code_learner.py```）。
- **预算与跳过**：`source_unchanged` 等跳过不增加 `learned` 计数，循环有 `max_attempts = pair_budget * 3`（```380:400:D:\RamboStar\idea\radarAnalyze\ai\code_learner.py```）。

### Review 关注点

- `warmup_done` 条件为 `len(learned) >= min(pair_budget, len(all_pairs))`（```415:417:D:\RamboStar\idea\radarAnalyze\ai\code_learner.py```），若大量因 hash 跳过可能导致「学到条数为 0 仍结束」与预期不符。
- `learn` 与 `ensure_overview_docs` 使用**不同**文件集合，需求需分别对齐。
- 模型输出依赖 `parse_json_from_llm`；失败则 `empty_ai_response` 跳过。
- `FOCUS_FILES` 路径为硬编码 GWM 树，换项目需配置化审查。

---

## 模块：`tpe.py`

路径：`D:\RamboStar\idea\radarAnalyze\ai\tpe.py`

### 定位（Temporal Pattern Engine）

- 代码明确为 **Temporal Pattern Engine** 门面：**时序模式（代码侧模式 + CAN 时间线 + 因果对齐）**，**不是** 贝叶斯优化里的 Tree-structured Parzen Estimator（```3:26:D:\RamboStar\idea\radarAnalyze\ai\tpe.py```）。
- 组装 `PatternExtractor`（代码模式）、`TemporalAnalyzer`（数据侧特征）、`CausalAligner`（对齐与证据）（```92:113:D:\RamboStar\idea\radarAnalyze\ai\tpe.py```）。

### 公开接口

**`@dataclass class TPEResult`**

- `patterns: list[CodePattern]`
- `features: dict[str, TemporalFeature]`
- `evidence: list[PatternEvidence]`
- `unresolved_variables: set[str] = field(default_factory=set)`
- `missing_can_signals: set[str] = field(default_factory=set)`
- `notes: list[str] = field(default_factory=list)`
- `@property def triggered_count(self) -> int` — `61:63:D:\RamboStar\idea\radarAnalyze\ai\tpe.py`
- `@property def has_triggers(self) -> bool` — `65:67:D:\RamboStar\idea\radarAnalyze\ai\tpe.py`
- `def to_expert_block(self) -> str` — `69:89:D:\RamboStar\idea\radarAnalyze\ai\tpe.py`

**`class TemporalPatternEngine`**

- `def __init__(self, source_root: Path, cache_dir: Optional[Path] = None, signal_mapping: Optional[dict] = None, variable_chains: Optional[dict] = None)` — `95:113:D:\RamboStar\idea\radarAnalyze\ai\tpe.py`
- `def run(self, store, func_name: Optional[str] = None, extra_patterns: Optional[list[CodePattern]] = None, state_transitions: Optional[list[dict]] = None, time_window: Optional[tuple[float, float]] = None) -> TPEResult` — `117:183:D:\RamboStar\idea\radarAnalyze\ai\tpe.py`
- `@staticmethod def format_evidence(evidence: list[PatternEvidence]) -> str` — `364:366:D:\RamboStar\idea\radarAnalyze\ai\tpe.py`
- `@staticmethod def format_features(features: dict[str, TemporalFeature]) -> str` — `368:370:D:\RamboStar\idea\radarAnalyze\ai\tpe.py`
- `@staticmethod def format_patterns(patterns: list[CodePattern]) -> str` — `372:374:D:\RamboStar\idea\radarAnalyze\ai\tpe.py`

### 算法要点（流水线）

1. `pattern_extractor.extract_all(use_cache=True)` 加载/扫描代码模式；可合并 `extra_patterns`（```147:149:D:\RamboStar\idea\radarAnalyze\ai\tpe.py```）。
2. 按 `func_name` 过滤 `adas_function`（大小写不敏感）（```187:196:D:\RamboStar\idea\radarAnalyze\ai\tpe.py```）。
3. 从模式收集 `trigger_variables`，经 `signal_mapper.resolve_internal_to_can` 解析为 CAN 名；未解析的进入 `unresolved_variables`（```200:245:D:\RamboStar\idea\radarAnalyze\ai\tpe.py```）。
4. 用 `store.get_signal_inventory()` 建 signal→message 映射，对每个 CAN 信号 `load_can_signal` → 可选 `time_window` 裁剪（`_clip_timeline` 保留窗口前最后样本作基线）→ `temporal_analyzer.analyze`（```249:309:D:\RamboStar\idea\radarAnalyze\ai\tpe.py```、`311:345:D:\RamboStar\idea\radarAnalyze\ai\tpe.py```）。
5. `state_timeline_from_transitions(state_transitions)` 与 `aligner.align(...)` 生成 `evidence`（```159:163:D:\RamboStar\idea\radarAnalyze\ai\tpe.py```）。

### 输入/输出

- **输入**：类 `FrameStore` 风格对象（`query_can_by_name` / `get_signal_inventory` 等在 analyzer 中使用）、可选 `func_name`、`state_transitions`、`time_window`、`signal_mapping` / `variable_chains`、`source_root` / `cache_dir`。
- **输出**：`TPEResult`（模式列表、按 CAN 名的时序特征、证据列表、未解析变量、缺失 CAN、统计 notes）。

### Review 关注点

- `func_name=None` 时不过滤模式，注释提示成本更高（```132:136:D:\RamboStar\idea\radarAnalyze\ai\tpe.py```）。
- `resolve_internal_to_can` 导入失败时返回空解析、全部变量进 `unresolved`（```226:229:D:\RamboStar\idea\radarAnalyze\ai\tpe.py```）。
- 门面**不**调用 LLM（```25:26:D:\RamboStar\idea\radarAnalyze\ai\tpe.py```）。

---

## 模块：`pattern_extractor.py`

路径：`D:\RamboStar\idea\radarAnalyze\ai\pattern_extractor.py`

### 定位（与 `memory/patterns.json` 的关系）

- 本模块从 **C 源码** 挖掘**时序行为模式**（HoldRelease、Accumulate 等），输出确定性 **`CodePattern` 列表**；启用缓存时写入 **`cache_dir/code_patterns.json`**（文档与代码默认指向 **`source_docs/code_patterns.json`** 这一用法）（```30:32:D:\RamboStar\idea\radarAnalyze\ai\pattern_extractor.py```、`448:477:D:\RamboStar\idea\radarAnalyze\ai\pattern_extractor.py```）。
- **`memory/patterns.json`** 在工程中是 **L3 诊断模式记忆**（症状、根因、关键词等），由 `memory/memory_system.py` 的 `add_pattern` 等维护（```16:18:D:\RamboStar\idea\radarAnalyze\memory\memory_system.py```、`113:133:D:\RamboStar\idea\radarAnalyze\memory\memory_system.py```），**不是**本文件写入。

### 公开接口

**常量**

- `PATTERN_TYPES: dict` — `54:61:D:\RamboStar\idea\radarAnalyze\ai\pattern_extractor.py`

**`@dataclass class CodePattern`**

- 字段：`pattern_type`, `file`, `line_start`, `line_end`, `function`, `trigger_condition`, `trigger_variables`, `consequence_variables`, `adas_function`, `snippet`, `notes`（```64:78:D:\RamboStar\idea\radarAnalyze\ai\pattern_extractor.py```）
- `def to_dict(self) -> dict` — `80:81:D:\RamboStar\idea\radarAnalyze\ai\pattern_extractor.py`

**`class PatternExtractor`**

- `def __init__(self, source_root: Path, cache_dir: Optional[Path] = None, target_files: Optional[Iterable[str]] = None)` — `144:152:D:\RamboStar\idea\radarAnalyze\ai\pattern_extractor.py`
- `def extract_all(self, use_cache: bool = True) -> list[CodePattern]` — `154:174:D:\RamboStar\idea\radarAnalyze\ai\pattern_extractor.py`

**模块函数**

- `def load_patterns(cache_dir: Path) -> list[CodePattern]` — `484:493:D:\RamboStar\idea\radarAnalyze\ai\pattern_extractor.py`
- `def summarise_patterns(patterns: list[CodePattern]) -> str` — `496:516:D:\RamboStar\idea\radarAnalyze\ai\pattern_extractor.py`

### 提取规则（已实现检测器）

- **目标文件**默认：`TARGET_FILES` 四处（```97:102:D:\RamboStar\idea\radarAnalyze\ai\pattern_extractor.py```）。
- **HoldRelease**：匹配 `if (` 多行条件；`{ }` 体不超过 `MAX_BODY_SCAN=20`；体内至少 `MIN_BODY_SIZE=2` 条赋 0/false；`_looks_like_hold_clear` 要求「类 flag + 类 timer」或≥2 条且含 flag（```185:244:D:\RamboStar\idea\radarAnalyze\ai\pattern_extractor.py```、`354:360:D:\RamboStar\idea\radarAnalyze\ai\pattern_extractor.py```）。
- **Accumulate**：`var += ...` 与附近 `var = 0` 成对（半径 30 行）（```248:279:D:\RamboStar\idea\radarAnalyze\ai\pattern_extractor.py```）。
- **adas_function**：关键词打分 `_guess_adas_function` / `_adas_func_for_identifier`（```104:113:D:\RamboStar\idea\radarAnalyze\ai\pattern_extractor.py```、`395:414:D:\RamboStar\idea\radarAnalyze\ai\pattern_extractor.py```）。

**缓存文件 schema**（与 `source_docs/code_patterns.json` 前部一致）：`source_hash`、`pattern_type_catalogue`、`patterns`（`CodePattern` 字典列表）（```470:474:D:\RamboStar\idea\radarAnalyze\ai\pattern_extractor.py```）。

### Review 关注点

- 仅 **HoldRelease + Accumulate** 实现；其余类型在 `PATTERN_TYPES` 中占位（```24:28:D:\RamboStar\idea\radarAnalyze\ai\pattern_extractor.py```）。
- 保守策略：宁可漏检（```91:94:D:\RamboStar\idea\radarAnalyze\ai\pattern_extractor.py```）。
- `cache_dir=None` 时不写缓存（```172:173:D:\RamboStar\idea\radarAnalyze\ai\pattern_extractor.py```）。

---

## 模块：`visualizer.py`

路径：`D:\RamboStar\idea\radarAnalyze\ai\visualizer.py`

### 定位

- 将 FrameStore、测试窗口、TPE 结果、参数敏感性、专家结论文本等汇总为**单文件离线** `report.html`；Plotly 图表 + Markdown 渲染专家段落（```3:22:D:\RamboStar\idea\radarAnalyze\ai\visualizer.py```）。
- **`render_report_from_md` 不在本模块**：工具脚本 `D:\RamboStar\idea\radarAnalyze\tools\render_report_from_md.py` 从 `report.md` 剥 front matter 后调用 **`build_report`**（```34:34:D:\RamboStar\idea\radarAnalyze\tools\render_report_from_md.py```）。

### 公开接口

**`@dataclass class ChartSection`**

- 字段：`anchor`, `title`, `caption`, `body_html`, `tag`, `icon`
- `@property def empty(self) -> bool` — `116:118:D:\RamboStar\idea\radarAnalyze\ai\visualizer.py`

**`@dataclass class VisualizerResult`**

- 字段：`html_path`, `charts_built`, `warnings`
- `def to_dict(self) -> dict` — `128:133:D:\RamboStar\idea\radarAnalyze\ai\visualizer.py`

**`def build_report(...)`** — `136:219:D:\RamboStar\idea\radarAnalyze\ai\visualizer.py`  

签名（关键字-only）：

```python
def build_report(
    *,
    case_dir: Path,
    func_name: str,
    task_type: str,
    problem: str,
    expected: str,
    diagnosis: str,
    store,
    windows: list,
    tpe_result=None,
    param_report=None,
    whatif_entries: Optional[list] = None,
    bag_meta: Optional[dict] = None,
    blf_meta: Optional[dict] = None,
) -> VisualizerResult
```

### 生成的 HTML 结构

- **页壳模板**：模块级字符串 **`_PAGE_TEMPLATE`**（```750:871:D:\RamboStar\idea\radarAnalyze\ai\visualizer.py```），通过 `_PAGE_TEMPLATE.format(...)` 填充（```1482:1501:D:\RamboStar\idea\radarAnalyze\ai\visualizer.py```）。
- **模板骨架（f-string/`str.format` 占位）**：
  - `<head>`：`charset`、`viewport`、**内联** `{plotly_js}`、`<style>{css}</style>`（`{css}` 来自 `_CSS`，```874:1286:D:\RamboStar\idea\radarAnalyze\ai\visualizer.py```）。
  - `<body>`：`header.page-header`（标题、任务/功能 badge、生成时间、图表数）→ `main.page-main`：`aside.toc`（目录）+ `section.page-body` 内多个 `article.card`：`#summary`、`#windows`、`{charts_html}`、`#diagnosis`（`markdown-body`）、可选 `warning_block` 与 `{meta_card}` → `footer.page-footer`。
- **Plotly 嵌入**：每张图 `fig.to_html(full_html=False, include_plotlyjs=False)`，仅输出 div/script 片段，**统一依赖页面头部一次注入的 plotly.js**（```275:275:D:\RamboStar\idea\radarAnalyze\ai\visualizer.py```）；`_load_plotly_js()` 优先 `plotly.offline.get_plotlyjs()` 内联（```1541:1556:D:\RamboStar\idea\radarAnalyze\ai\visualizer.py```）。
- **Markdown → HTML**：`diagnosis`、`problem`、`expected` 经 `_md_to_html`（优先 `python-markdown` 扩展 `fenced_code/tables/...`，否则正则回退）（```1465:1467:D:\RamboStar\idea\radarAnalyze\ai\visualizer.py```、`707:744:D:\RamboStar\idea\radarAnalyze\ai\visualizer.py```）。**并非**整份 `report.md` 逐节映射；**专家全文**来自调用方传入的 `diagnosis` 字符串（通常即报告主体 Markdown）。
- **`cases/BSDLCA001/report.html`**：体积极大是因内联完整 plotly.js；结构上仍符合上述壳；无法用行式 `read` 抽样时，以 `_PAGE_TEMPLATE` 与 `_write_html_shell` 为准。

### 图表类型

| 区块/anchor | 类型 | 说明 |
|-------------|------|------|
| `ego-speed` | 时间序列 `Scatter` | 自车速度，多 topic；窗口为竖条 `add_vrect`（```225:287:D:\RamboStar\idea\radarAnalyze\ai\visualizer.py```） |
| `output-signals` | 阶跃线 `lines+markers`，`shape=hv` | CAN 输出信号（```290:362:D:\RamboStar\idea\radarAnalyze\ai\visualizer.py```） |
| `state-timeline` | 同上 | 功能状态字段阶跃（```365:431:D:\RamboStar\idea\radarAnalyze\ai\visualizer.py```） |
| `tpe-triggers` | 横向粗线 `Scatter`（类 Gantt） | TPE `triggered` 证据的时间段（```434:505:D:\RamboStar\idea\radarAnalyze\ai\visualizer.py```） |
| `param-sensitivity` | 横向 `Bar` | `task_type in ("tune","verify")` 时；min‖Δ‖（```508:587:D:\RamboStar\idea\radarAnalyze\ai\visualizer.py```） |
| `whatif` | 分组 `Bar` | 穿越次数 before/after（```590:647:D:\RamboStar\idea\radarAnalyze\ai\visualizer.py```） |

测试窗口区：**HTML 条带** `_window_strip_html` + 列表，非 Plotly（```1289:1344:D:\RamboStar\idea\radarAnalyze\ai\visualizer.py```）。

### Review 关注点

- 无 plotly 时 `_write_fallback_html`（```1505:1537:D:\RamboStar\idea\radarAnalyze\ai\visualizer.py```）。
- 图表数据全部来自传入 `store`/对象，**不**自读 `report.md`（除非外层先读再传入 `diagnosis`）。
- 内联 JS 使单文件体积巨大，属设计权衡（```11:13:D:\RamboStar\idea\radarAnalyze\ai\visualizer.py```）。

---

### 参考文件结构摘要

- **`source_docs/code_patterns.json`**：`source_hash`、`pattern_type_catalogue`、`patterns[]`（与 `PatternExtractor._save_cache` 一致）。
- **`memory/code_knowledge/FCTB.json`**：`_meta` + 各 `focus` 键下结构化数组/对象；条目含 `id`、`code_ref`、`confidence`、`_learned_at` 等。
- **`memory/patterns.json`**：JSON 数组，元素含 `function`、`symptom`、`root_cause`、`keywords`、`fix_hint`、`_learned_at`、`_id`（诊断经验库，非源码扫描产物）。


================================================================================

# 第七章 记忆系统（memory_system + auto_dream）

以下为基于源码全文（及你指定参考片段）整理的实现说明。**注意**：你模板里的部分命名（如 `load`/`save`/`get_function_memory`/`merge_patterns`/`save_session`）与仓库**实际方法名**不一致；下文一律以代码为准，并在 L1/L2/L4 等处标明**实际 API 名称**。

---

## 模块：`memory/__init__.py`

### 定位

- 包入口：从子模块导出 `MemorySystem` 与 `AutoDream`，无额外逻辑。

```1:2:D:\RamboStar\idea\radarAnalyze\memory\__init__.py
from .memory_system import MemorySystem
from .auto_dream import AutoDream
```

---

## 模块：`memory/memory_system.py`

### 定位

- 多层记忆的统一读写与诊断上下文拼装：**L1** `project.md`、**L2** `memory/functions/<FUNC>.json`、**L3** `patterns.json`、**L4** `memory/sessions/<session_id>.json`、**L5** `cases/<case_id>/memory.json`、**L6** `memory/code_knowledge/<FUNC>.json` + `learning_state.json`。
- 文档性分层说明见文件头 ```7:31:D:\RamboStar\idea\radarAnalyze\memory\memory_system.py```。

### 类：`MemorySystem`

#### `__init__(self, project_root: Path)` 成员字段

| 成员 | 含义 | 行号 |
|------|------|------|
| `self.root` | 项目根目录 | 44 |
| `self.memory_dir` | `project_root / "memory"`，并 `mkdir(exist_ok=True)` | 45-46 |
| `self._ctx_cache` | 诊断上下文字符串缓存，键为 `(func_upper, problem[:240], case_dir_str)` | 55 |
| `self._ctx_cache_hits` / `self._ctx_cache_misses` | 缓存命中/未命中计数 | 56-57 |

**隐式路径约定**（由方法拼接，非 `__init__` 单独字段）：

- L1：`memory_dir / "project.md"`
- L2：`memory_dir / "functions" / f"{func_name.upper()}.json"`
- L3：`memory_dir / "patterns.json"`
- L4：`memory_dir / "sessions" / f"{session_id}.json"`
- L5：`case_dir / "memory.json"`（`case_dir` 由调用方传入）
- L6：`memory_dir / "code_knowledge" / f"{func_name.upper()}.json"`、`.../learning_state.json`

`__init__` 中还会创建子目录：`functions`、`sessions`、`code_knowledge`（```47:49:D:\RamboStar\idea\radarAnalyze\memory\memory_system.py```）。**不**自动创建 `patterns.json` 或 `project.md`。

---

### L1 API（`project.md`）

实际方法名与模板中的 `load/save/update/...` 对应关系如下。

| 方法签名 | 行为 | 行号 |
|----------|------|------|
| `read_project_memory(self) -> str` | 存在则读全文 UTF-8，否则 `""` | 61-66 |
| `write_project_memory(self, content: str) -> None` | 整体覆盖写入 | 68-70 |
| `append_project_memory(self, entry: str) -> None` | 在文末追加 `## [YYYY-MM-DD HH:MM]\n{entry}`；若文件不存在则写入以 `# Project Memory` 开头的首段 | 72-78 |

**无**单独的 `update` / `get_preferences` / `append_system_arch` 方法；此类更新由上层或 `AutoDream` 通过 `write_project_memory` 整块替换完成。

**`project.md` 结构（参考前 30 行）**：顶层 Markdown 标题与按时间戳分节（如 `## [2026-04-18 ...]`），内含架构、功能列表、状态机约定等叙述性内容（```1:30:D:\RamboStar\idea\radarAnalyze\memory\project.md```）。

---

### L2 API（`memory/functions/<FUNC>.json`）

| 方法签名 | 行为 | 行号 |
|----------|------|------|
| `read_function_knowledge(self, func_name: str) -> dict` | 读 JSON；不存在返回 `{}` | 82-87 |
| `write_function_knowledge(self, func_name: str, knowledge: dict) -> None` | 写入前设置 `knowledge["_updated"] = now.isoformat()` | 89-93 |
| `get_all_function_names(self) -> list[str]` | `functions/*.json` 的文件名 stem 列表 | 95-99 |
| `has_function_knowledge(self, func_name: str) -> bool` | 对应文件是否存在 | 101-102 |

**无** `merge` / `append_experience` 命名方法；合并由调用方 `read` → 改 dict → `write`，或由 `AutoDream._apply_dream_result` 对 `function_updates` 做 `existing.update(updates)`（见 `auto_dream.py`）。

**L2 JSON schema（来自 `memory/functions/FCTA.json` 样例，字段名）**：

- 业务字段示例：`function`, `diagnosis_count`, `known_issues`（数组，元素可含 `id`, `problem`, `sessions`, `date`, `analysis`, `confidence`, `status`）, `description`, `state_machine`, `logic_ref`, `status` 等。
- 系统字段：`_updated`（由 `write_function_knowledge` 写入）。

```1:40:D:\RamboStar\idea\radarAnalyze\memory\functions\FCTA.json
{
  "function": "FCTA",
  "diagnosis_count": 10,
  "known_issues": [
    {
      "id": "FCTA001",
      "problem": "...",
      "sessions": [...],
      "date": "...",
      "analysis": "...",
      "confidence": 0.95,
      "status": "..."
    }
  ],
  "_updated": "...",
  "description": "...",
  "state_machine": "...",
  "logic_ref": "...",
  "status": "..."
}
```

---

### L3 API（`patterns.json`）

| 方法签名 | 行为 | 行号 |
|----------|------|------|
| `read_patterns(self) -> list[dict]` | 读 JSON 数组；不存在返回 `[]` | 106-111 |
| `add_pattern(self, pattern: dict) -> None` | 对去掉 `_` 前缀键后的内容算 MD5 取前 8 位为 `_id`；若已有相同 `_id` 则跳过；否则写 `_learned_at`、`_id` 并追加写入文件 | 113-132 |
| `find_similar_patterns(self, func_name: str, symptom_keywords: list[str]) -> list[dict]` | `function` 大小写匹配且 `keywords` 与症状词有交集；匹配项带 `_match_score`，按分数降序 | 135-147 |

**无** `merge_patterns` 方法；批量删改由 `AutoDream` 读全量、过滤 `_id`、写回，或 `add_pattern` 增量添加。

**模式 schema（业务字段 + 系统字段，参考 `patterns.json` 前几条）**：

- 业务：`function`, `symptom`, `root_cause`, `keywords`（字符串数组）, `fix_hint`。
- 系统：`_learned_at`, `_id`（`add_pattern` 生成）。

**`conflicts_found`** 不在 L3 存储，而出现在 `AutoDream` 的 AI 输出与 `dream_log` 的统计中。

---

### L4 API（`memory/sessions/*.json`）

| 方法签名 | 行为 | 行号 |
|----------|------|------|
| `create_session(self, case_id: str, problem: str, expected: str) -> str` | 生成 `session_id = f"{case_id}_{%Y%m%d_%H%M%S}"`，写入初始 session dict，返回 `session_id` | 151-165 |
| `log_step(self, session_id: str, step_name: str, detail: Any) -> None` | 向 `steps` 追加 `step`/`timestamp`/`detail`（非 str/dict/list 则 `str(detail)`） | 167-176 |
| `log_finding(self, session_id: str, finding: dict) -> None` | `findings` 追加，带 `_timestamp` | 178-184 |
| `complete_session(self, session_id: str, result_summary: str) -> None` | `status="completed"`，写 `completed_at`、`result_summary` | 186-193 |

**内部（非 public）**：

- `_read_session(self, session_id: str) -> Optional[dict]` — 195-199  
- `_write_session(self, session_id: str, data: dict) -> None` — 201-203  

**文件命名规则**：`{session_id}.json`，其中 `session_id` 由 `create_session` 定义为 **`{case_id}_{YYYYMMDD_HHMMSS}`**（无 `sessions/` 前缀；与用户写的 `CASE_...` 形式一致，**case_id 本身可含字母**，如 `FCATB001_20260417_155149`）。

**Session snapshot schema（参考 `FCATB001_20260417_155149.json` 前段）**：

- 顶层：`session_id`, `case_id`, `problem`, `expected`, `created_at`, `status`, `steps`, `findings`。
- `steps[]`：`step`, `timestamp`, `detail`（常为嵌套 dict）。
- 完成后另有：`completed_at`, `result_summary`（由 `complete_session` 写入）。

```1:12:D:\RamboStar\idea\radarAnalyze\memory\sessions\FCATB001_20260417_155149.json
{
  "session_id": "FCATB001_20260417_155149",
  "case_id": "FCATB001",
  "problem": "...",
  "expected": "...",
  "created_at": "2026-04-17T15:51:49.863471",
  "status": "completed",
  "steps": [
```

---

### L5 API（`cases/<CASE>/memory.json`）

| 方法签名 | 行为 | 行号 |
|----------|------|------|
| `read_case_memory(self, case_dir: Path) -> dict` | 读 `case_dir/memory.json`；不存在 `{}` | 207-212 |
| `write_case_memory(self, case_dir: Path, memory: dict) -> None` | 写前设置 `memory["_updated"]` | 214-219 |

**L5 schema（样例 `cases/FCATB001/memory.json`）**：`session_id`, `function`, `problem`, `diagnosis_summary`, `_updated` 等；**无**强制 schema 校验，由写入方约定。

```1:7:D:\RamboStar\idea\radarAnalyze\cases\FCATB001\memory.json
{
  "session_id": "FCATB001_20260417_180840",
  "function": "FCTB",
  "problem": "...",
  "diagnosis_summary": "...",
  "_updated": "2026-04-17T18:23:01.421433"
}
```

---

### L6 API（`memory/code_knowledge/`，代码中明确实现）

| 方法签名 | 行为 | 行号 |
|----------|------|------|
| `read_code_knowledge(self, func_name: str) -> dict` | 读 `code_knowledge/<FUNC>.json`；JSON/OS 错误则 `{}` | 223-231 |
| `list_code_knowledge_funcs(self) -> list[str]` | 仅 **stem 全大写** 的 `.json`（用于排除 `learning_state.json` 等小写 stem） | 233-238 |
| `read_code_learning_state(self) -> dict` | 读 `learning_state.json` | 240-248 |
| `render_code_knowledge_for_context(self, func_name: str, max_chars: int = 6000) -> str` | 依 `_meta.learned_focuses` 与固定 focus 列表渲染 Markdown；超长截断 | 250-312 |

**L6 `FUNC.json` schema（`code_knowledge/FCTA.json` 样例）**：

- `_meta`：`function`, `last_updated`, `learned_focuses`, `source_hashes`（focus → hash 字符串）等。
- 各 focus 下结构化块：`alarm_logic`, `calculation_chain`, `output_chain`, `state_machine` 等；列表项常含 `id`, `description`, `c_expression`, `variables`, `thresholds`, `code_ref`（`file`, `line`, `function`）, `confidence`, `_learned_at` 等。

**`learning_state.json` 字段（实例）**：`cursor`, `warmup_done`, `pair_hashes`, `learned_pairs`, `total_learned_pairs`, `last_learn_at`（```1:30:D:\RamboStar\idea\radarAnalyze\memory\code_knowledge\learning_state.json```）。

---

### 上下文拼装与缓存（跨层）

| 方法签名 | 行为 | 行号 |
|----------|------|------|
| `build_context_for_diagnosis(self, func_name: str, problem: str, case_dir: Optional[Path] = None) -> str` | 组合 L1（截断 2000）+ L2（JSON 截断 3000）+ L6（`render_code_knowledge_for_context`）+ L3（`find_similar_patterns`，最多 3 条摘要）+ L5（若 `case_dir` 给定，截断 1500）；结果写入 `_ctx_cache` | 316-375 |
| `invalidate_context_cache(self) -> None` | 清空缓存 | 377-384 |
| `context_cache_stats(self) -> dict` | 返回 `hits`, `misses`, `size` | 386-392 |

---

### 隔离原则（文档与路径约定）

- **L1**：跨会话、跨案例的通用项目知识（`project.md`）。
- **L2**：按 ADAS 功能维度的结构化知识（`functions/<FUNC>.json`）。
- **L3**：可复用的症状–根因模式库（全局 `patterns.json`）。
- **L4**：单次诊断会话轨迹（`sessions/`）。
- **L5**：绑定具体案例目录的结论与摘要（`cases/<id>/memory.json`）。
- **L6**：从源码学习到的深度代码知识（`code_knowledge/`），与 L2 互补：L2 偏诊断沉淀，L6 偏代码结构/链路与 learner 状态。

---

### 并发 / 锁 / 原子性

- **`MemorySystem` 不使用** dream-lock、**不使用** 临时文件 + `rename`；一律 `Path.write_text` / `read_text` 直接写盘（例如 ```70:70:D:\RamboStar\idea\radarAnalyze\memory\memory_system.py```、```131:133:D:\RamboStar\idea\radarAnalyze\memory\memory_system.py```）。
- 多进程同时写同一文件时存在**竞态**风险；并发控制仅在 `AutoDream` 层通过 `.dream-lock` 协调做梦周期（见下节）。

---

## 模块：`memory/auto_dream.py`

### 定位

- **记忆整合（做梦）引擎**：在门控条件允许时，串联 **Phase 0 代码学习** 与 **Phase 1–4 的「定向–收集–AI 整合–解析输出」**；再通过 `_apply_dream_result` 写回 L1/L2/L3。
- 设计说明与门控摘要见文件头 ```1:16:D:\RamboStar\idea\radarAnalyze\memory\auto_dream.py```。

**与提示语四阶段的关系**：`CONSOLIDATION_PROMPT` 要求模型在输出 JSON 前在思维上完成 Orient → Gather → Consolidate → Prune（```33:81:D:\RamboStar\idea\radarAnalyze\memory\auto_dream.py```）；**工程上** Phase 0 另算为代码学习，Phase 1 含 `variable_chains` 刷新与全量 context 收集。

---

### 类：`AutoDream`

#### `__init__(self, memory_system, router, project_root: Path, config: Optional[dict] = None)`

- `self.memory`：传入的 `MemorySystem` 实例（类型注解在源码中为 `memory_system`）。  
- `self.router`：具备 `complex(prompt, system=...)` 的 AI 路由。  
- `self.project_root` / `self.config`。  
- `self.memory_dir = project_root / "memory"`。  
- `self.lock_path = memory_dir / ".dream-lock"`（`LOCK_FILE`）。  
- `self.log_path = memory_dir / "dream_log.json"`（`DREAM_LOG_FILE`）。  

行号：```91:98:D:\RamboStar\idea\radarAnalyze\memory\auto_dream.py```。

---

### 入口：`try_dream`

#### 签名

`try_dream(self, on_status=None, force: bool = False) -> Optional[dict]` — ```102:106:D:\RamboStar\idea\radarAnalyze\memory\auto_dream.py```

#### 完整行为（顺序）

1. 内部 `status(msg)`：若 `on_status` 非空则 `on_status("dream", msg)`（```121:123:D:\RamboStar\idea\radarAnalyze\memory\auto_dream.py```）。
2. **`force=False`**：若 `_is_gate_open()` 为假，**返回 `None`**（```125:126:D:\RamboStar\idea\radarAnalyze\memory\auto_dream.py```）。
3. 若 `_is_locked()` 为真，status 提示并发做梦，**返回 `None`**（```128:130:D:\RamboStar\idea\radarAnalyze\memory\auto_dream.py```）。
4. `status("Memory consolidation starting...")`，`_acquire_lock()`（```132:133:D:\RamboStar\idea\radarAnalyze\memory\auto_dream.py```）。
5. `try`：`result = _run_dream_cycle(status)` → `_apply_dream_result(result, status)` → `_record_dream(result)` → `_release_lock()` → 返回 `result`（```135:141:D:\RamboStar\idea\radarAnalyze\memory\auto_dream.py```）。
6. `except`：`_release_lock()`，status 失败信息，**返回 `{"error": str(e)}`**（```142:145:D:\RamboStar\idea\radarAnalyze\memory\auto_dream.py```）。

#### 返回值字段（成功路径）

- 主路径来自 AI 输出 JSON 解析后的 dict，典型键（见 `CONSOLIDATION_PROMPT`）：`project_memory_update`, `function_updates`, `patterns_to_remove`, `patterns_to_add`, `conflicts_found`, `summary`（```71:81:D:\RamboStar\idea\radarAnalyze\memory\auto_dream.py```）。
- **必定附加**：`result["_code_learning"] = code_delta`（Phase 0 的 `learn_result`）（```311:313:D:\RamboStar\idea\radarAnalyze\memory\auto_dream.py```）。
- **`overview`**：嵌在 `_code_learning["overview"]` 内（由 `_run_code_learning` 写入）（```262:269:D:\RamboStar\idea\radarAnalyze\memory\auto_dream.py```）。
- **解析失败**：`summary` 为固定英文说明，`raw_output` 为截断原文（```305:309:D:\RamboStar\idea\radarAnalyze\memory\auto_dream.py```）。

#### 触发条件

- **`force=True`**：跳过门控（仍受 **dream-lock** 约束）（```125:126:D:\RamboStar\idea\radarAnalyze\memory\auto_dream.py```）。
- **`force=False`**（`_is_gate_open`）：  
  - `_hours_since_last_dream() >= DREAM_INTERVAL_HOURS`（默认 **4**）；若日志为空则视为 `inf` 小时，满足间隔（```149:159:D:\RamboStar\idea\radarAnalyze\memory\auto_dream.py```、```161:169:D:\RamboStar\idea\radarAnalyze\memory\auto_dream.py```）。  
  - `_count_new_sessions() >= MIN_NEW_SESSIONS`（默认 **2**）：统计 `sessions/*.json` 中 `created_at` **严格晚于** 上次 dream 日志最后一条 `timestamp` 的会话数；若无 dream 日志则所有会话都算新（```171:188:D:\RamboStar\idea\radarAnalyze\memory\auto_dream.py```）。

常量：```26:29:D:\RamboStar\idea\radarAnalyze\memory\auto_dream.py```。

#### dream-lock 并发保护

- `_is_locked`：锁文件存在且 **mtime 在 1 小时内** 视为锁定；**超时则 `_release_lock()` 并视为未锁**（```192:203:D:\RamboStar\idea\radarAnalyze\memory\auto_dream.py```）。
- `_acquire_lock`：写入当前进程 PID（```205:206:D:\RamboStar\idea\radarAnalyze\memory\auto_dream.py```）。
- `_release_lock`：`unlink(missing_ok=True)`（```208:212:D:\RamboStar\idea\radarAnalyze\memory\auto_dream.py```）。

**无**文件级原子 rename；锁文件与各类 JSON 仍为直接写入。

---

### 四阶段 + Phase 0（与代码对齐）

实现上 `_run_dream_cycle` 注释为 **5 段：0 Study + 1–4**（```275:284:D:\RamboStar\idea\radarAnalyze\memory\auto_dream.py```）；状态文案为 “Phase 0/4”…“Phase 4/4”（```285:300:D:\RamboStar\idea\radarAnalyze\memory\auto_dream.py```）。

#### Phase 0 — Study（代码学习，`_run_code_learning`）

- **做什么**：导入 `CodeLearner`，`learn(status_cb=...)` 写 **L6 JSON**；再 `ensure_overview_docs(status_cb=...)` 按源码 hash **刷新 `source_docs/` 下 MD 概览**（```227:271:D:\RamboStar\idea\radarAnalyze\memory\auto_dream.py```）。
- **输入**：`self.router`, `self.config`, `self.project_root`；`config` 需包含 `paths.source_code`（`_refresh_variable_chains` 亦用此路径）（```217:223:D:\RamboStar\idea\radarAnalyze\memory\auto_dream.py```）。
- **Prompt**：本阶段**不**使用 `CONSOLIDATION_PROMPT`；由 `CodeLearner` 内部定义（本文件未展开）。

#### Phase 1 — Orient（定向）

- **做什么**：  
  - `status("Phase 1/4: Orient — surveying memories...")`  
  - `_refresh_variable_chains()`：若配置中有 `source_code`，调用 `ai.signal_mapper.trace_variable_chains(Path(source_code), project_root/source_docs)` 刷新 **`variable_chains.json`**（```214:225:D:\RamboStar\idea\radarAnalyze\memory\auto_dream.py```、```288:290:D:\RamboStar\idea\radarAnalyze\memory\auto_dream.py```）。  
  - `context = _gather_all_memory_context()`：拼接 L1、各 L2、`patterns` 摘要、`source_docs/*.md` 每文件前 500 字符、`signal_mapping.json` 抽样、`variable_chains.json` 摘要、最近 5 个 L5 case memory、L6 代码知识与 `learning_state` 摘要（```315:439:D:\RamboStar\idea\radarAnalyze\memory\auto_dream.py```）。
- **Prompt**：此时尚未调用整合模型；整合 prompt 在 Phase 3。

#### Phase 2 — Gather（收集）

- **做什么**：`recent = _gather_recent_sessions()`：按 mtime 逆序读全部 `sessions/*.json`，取**最近 10 条**，输出问题/状态/结果/部分 `findings`（```441:465:D:\RamboStar\idea\radarAnalyze\memory\auto_dream.py```、```292:293:D:\RamboStar\idea\radarAnalyze\memory\auto_dream.py```）。

#### Phase 3 — Consolidate（整合）

- **做什么**：`_build_prompt(context, recent, code_delta)` 拼接用户消息；`self.router.complex(prompt, system=CONSOLIDATION_PROMPT)`（```295:298:D:\RamboStar\idea\radarAnalyze\memory\auto_dream.py```）。
- **冲突与更新规则**：由 **system prompt** 规定（时间/数据/频率优先，`[CONFLICT]` 标记等）（```52:61:D:\RamboStar\idea\radarAnalyze\memory\auto_dream.py```）。
- **L1 `project.md`**：此阶段仅生成 **`project_memory_update` 字符串**；真正写入在 `_apply_dream_result`（```507:512:D:\RamboStar\idea\radarAnalyze\memory\auto_dream.py```）。

#### Phase 4 — Prune（解析 + 为应用做准备）

- **做什么**：从模型返回 `content` 中截取首尾 `{` `}` 做 `json.loads`；失败则降级 dict（```300:309:D:\RamboStar\idea\radarAnalyze\memory\auto_dream.py```）；附加 `_code_learning`（```311:313:D:\RamboStar\idea\radarAnalyze\memory\auto_dream.py```）。

**机械 Prune / 应用**：在 `try_dream` 中紧随的 `_apply_dream_result`（```507:537:D:\RamboStar\idea\radarAnalyze\memory\auto_dream.py```）：

- 有 `project_memory_update` → `memory.write_project_memory`  
- `function_updates` → 逐功能 `read` + `dict.update` + `write`  
- `patterns_to_remove`：按 `_id` 过滤后写回 `patterns.json`  
- `patterns_to_add`：逐条 `memory.add_pattern`  
- `conflicts_found`：仅 **status 计数**，**不**单独落盘  

**注意**：**不会**在代码里删除旧 session 文件；「修剪」主要针对模式与 AI 叙述性输出。

---

### 代码学习集成

- **调用**：`_run_code_learning` 内 `CodeLearner(self.router, self.config, self.project_root)`，再 `learner.learn(...)` 与 `learner.ensure_overview_docs(...)`（```239:271:D:\RamboStar\idea\radarAnalyze\memory\auto_dream.py```）。
- **warmup / 常规**：**不在 `auto_dream.py` 内实现**；注释说明由 `CodeLearner` 根据 `learning_state` 的 `warmup_done` 在 **`warmup_pairs`（冷启动）与 `pairs_per_dream`（热启动）** 间选择（```116:119:D:\RamboStar\idea\radarAnalyze\memory\auto_dream.py```、```234:237:D:\RamboStar\idea\radarAnalyze\memory\auto_dream.py```）。
- **状态回调**：`status_cb=lambda _s, d: status(d)` 将子阶段进度并入 dream 的 `on_status`（```255:260:D:\RamboStar\idea\radarAnalyze\memory\auto_dream.py```）。

---

### `variable_chains` / `signal_chain` / `overview` 刷新时机

| 项 | 阶段/函数 | 说明 |
|----|-----------|------|
| `variable_chains.json` | Phase 1 `_refresh_variable_chains` | `trace_variable_chains` 写入 `source_docs`（```214:225:D:\RamboStar\idea\radarAnalyze\memory\auto_dream.py```） |
| `overview`（MD） | Phase 0 `ensure_overview_docs` | 挂在 `learn_result["overview"]`（```258:266:D:\RamboStar\idea\radarAnalyze\memory\auto_dream.py```） |
| `signal_chain` | **无专用刷新函数** | 若存在 `source_docs/signal_chain.md`，仅在 `_gather_all_memory_context` 中作为 `*.md` **读前 500 字**进入 context（```334:341:D:\RamboStar\idea\radarAnalyze\memory\auto_dream.py```） |

---

### `dream_log.json` 写入（`_record_dream`）

每条记录字段（```549:567:D:\RamboStar\idea\radarAnalyze\memory\auto_dream.py```）：

- 必有：`timestamp`, `summary`, `conflicts`（`conflicts_found` 长度）, `patterns_added`, `patterns_removed`
- 若 `_code_learning` 存在且非 `skipped`：`code_pairs_learned`, `code_pairs_skipped`, `code_warmup_done`（取自 `code_delta` 的 `learned_count` / `skipped_count` / `warmup_done`）

日志最长 **100** 条，超出截断尾部（```565:567:D:\RamboStar\idea\radarAnalyze\memory\auto_dream.py```）。

**历史样例**（前若干条仅含早期字段，无 code 统计）：```1:36:D:\RamboStar\idea\radarAnalyze\memory\dream_log.json```。

---

### `AutoDream` 其余方法（便于 review，含「小」方法）

**Public**：仅 `__init__`、`try_dream`（上文已列）。

**内部方法签名一览**：

| 方法 | 行号 |
|------|------|
| `_is_gate_open(self) -> bool` | 149-159 |
| `_hours_since_last_dream(self) -> float` | 161-169 |
| `_count_new_sessions(self) -> int` | 171-188 |
| `_is_locked(self) -> bool` | 192-203 |
| `_acquire_lock(self)` | 205-206 |
| `_release_lock(self)` | 208-212 |
| `_refresh_variable_chains(self)` | 214-225 |
| `_run_code_learning(self, status) -> dict` | 227-271 |
| `_run_dream_cycle(self, status) -> dict` | 275-313 |
| `_gather_all_memory_context(self) -> str` | 315-439 |
| `_gather_recent_sessions(self) -> str` | 441-465 |
| `_build_prompt(self, context: str, recent: str, code_delta: Optional[dict] = None) -> str` | 467-503 |
| `_apply_dream_result(self, result: dict, status)` | 507-537 |
| `_read_dream_log(self) -> list[dict]` | 541-547 |
| `_record_dream(self, result: dict)` | 549-567 |

---

### Review 关注点（建议）

- **门控与日志一致性**：新会话计数依赖 `dream_log` 最后一条 `timestamp` 与 session 的 `created_at` ISO 比较；时钟回拨或手动改文件可能导致意外触发/不触发。
- **`MemorySystem` 无锁**：做梦持锁期间不阻止 orchestrator 直接写 L2/L3/L5。
- **AI 输出解析**：仅靠首尾 `{` `}` 切片，模型若输出多个 JSON 或夹杂文字易失败并落入 `raw_output`。
- **`add_pattern` 与 `patterns_to_remove`**：移除按 `_id`，新增再走内容 hash；需确认 AI 输出的 `_id` 与现存一致。
- **Phase 编号**：注释为 5 阶段（0–4），与用户口头「四阶段」并存，易混淆。
- **`_code_learning` 字段契约**：`dream_log` 依赖 `learned_count` / `skipped_count` / `warmup_done`；需与 `CodeLearner.learn` 返回值保持同步。

---

## 目录约定与自动创建 / 扫描

| 目录/文件 | 层级 | 自动创建 | 扫描方式 |
|-----------|------|----------|----------|
| `memory/functions/` | L2 | `MemorySystem.__init__` `mkdir`（```47:47:D:\RamboStar\idea\radarAnalyze\memory\memory_system.py```） | `glob("*.json")` 得功能名（```97:99:D:\RamboStar\idea\radarAnalyze\memory\memory_system.py```） |
| `memory/sessions/` | L4 | 同上 `mkdir`（```48:48:D:\RamboStar\idea\radarAnalyze\memory\memory_system.py```） | `AutoDream` / `_gather_recent_sessions` / `_count_new_sessions` 使用 `glob("*.json")`（```178:187:D:\RamboStar\idea\radarAnalyze\memory\auto_dream.py``` 等） |
| `memory/code_knowledge/` | L6 | 同上 `mkdir`（```49:49:D:\RamboStar\idea\radarAnalyze\memory\memory_system.py```） | `glob("*.json")`；`list_code_knowledge_funcs` 过滤 stem 全大写（```233:238:D:\RamboStar\idea\radarAnalyze\memory\memory_system.py```）；`_gather_all_memory_context` 排除 `learning_state` 且只要大写 stem（```397:400:D:\RamboStar\idea\radarAnalyze\memory\auto_dream.py```） |
| `memory/patterns.json` | L3 | **不**在 `__init__` 创建；首次 `add_pattern` 或读时由 `read_patterns` 返回 `[]` | `read_patterns` / 直接读写 |
| `memory/project.md` | L1 | **不**自动创建；`read` 返回 `""`，`append` 会写新文件 | `read_project_memory` 等 |
| `cases/<CASE>/memory.json` | L5 | 由业务写入 `write_case_memory` | `AutoDream` 对 `cases/*/memory.json` 按 mtime 取 5 个（```382:394:D:\RamboStar\idea\radarAnalyze\memory\auto_dream.py```） |

---

以上内容可直接用于后续「需求 ↔ 实现」对照 review；若你希望模板术语与代码名一一映射表（例如「load_project_memory = read_project_memory」）单独成表，可以在 Agent 模式下再补一份对照文档。


================================================================================

# 第八章 基础设施与工具（model_router / context_budget / utils / scripts / tools / tests / source_docs）

以下为基于仓库内已读文件的实现说明（**未读取** `msg_defs` 下具体定义，仅列路径）。说明：`model_router` 中**没有** `complete_simple` / `complete_complex`，公开辅助方法名为 `simple` / `complex`。

---

## Part A：AI 辅助模块

### `ai/model_router.py`

**`ModelRouter` 公开接口（签名与行号）**

- `def __init__(self, config: dict) -> None` — 第 22–40 行  
- `def chat(self, messages: list[dict], complexity: str = "auto", temperature: float = 0.7, max_tokens: int = 4096, tools: Optional[list] = None, response_format: Optional[dict] = None, thinking: bool = False) -> dict` — 第 42–141 行  
- `def simple(self, prompt: str, system: str = "") -> str` — 第 143–150 行  
- `def complex(self, prompt: str, system: str = "", tools: Optional[list] = None, max_tokens: int = 16384, thinking: bool = False) -> dict` — 第 152–168 行  

未对外暴露但与本类行为相关：

- `def _estimate_complexity(self, messages: list[dict], tools: Optional[list]) -> str` — 第 200–215 行  
- `@staticmethod def _print_usage(response, model: str, complexity: str, elapsed: float)` — 第 170–198 行  

**local vs remote 选路规则**

- 显式 `complexity="simple"` → 使用 `local_client` + `local_model`（第 67–68 行）。  
- 显式 `complexity="complex"` → 使用 `remote_client` + `remote_model`（第 69–70 行）。  
- `complexity="auto"` 时由 `_estimate_complexity` 决定（第 64–65、200–215 行）：  
  - 若传入 `tools` 非空 → `"complex"`（第 202–203 行）；  
  - 否则若所有 message 的 `content` 总长度 > 3000 → `"complex"`（第 204–206 行）；  
  - 否则若最后一条 user 内容命中中英关键词列表（分析/诊断/根因/state machine 等）→ `"complex"`（第 207–214 行）；  
  - 否则 → `"simple"`（第 215 行）。  
- **注意**：只要 `complexity != "simple"`（含 auto 判为 complex），就会走 remote 分支并组装 `extra_body`（第 83–91 行）；`thinking` 布尔仅在该分支参与 API 行为。

**默认模型、base_url、api_key 从 config 读取位置**

- 统一从 `config.get("ai", {})` 读取（第 23 行）。  
- **Local**：`ai_cfg.get("local") or ai_cfg.get("gemma", {})`（第 25 行）；`base_url` 默认 `http://localhost:11434/v1`（第 29 行），`api_key` 默认 `"ollama"`（第 30 行），`model` 默认 `"qwen3:14b"`（第 32 行）。  
- **Remote**：`ai_cfg.get("remote") or ai_cfg.get("qwen", {})`（第 26 行）；`base_url` 来自 `remote_cfg.get("base_url")`（无默认，第 35 行），`api_key` 默认 `"none"`（第 36 行），`model` 默认 `"Qwen3.5-27B-FP16"`（第 38 行）。  
- `self.thinking_mode = ai_cfg.get("thinking", "off")`（第 40 行）：**在本文件内未再使用**；`off` / `synth` / `full` 的实际效果在 `ExpertPanel` 里通过 `router.thinking_mode` 转成每次 `complex(..., thinking=...)` 的布尔值（见下方「thinking」与 `expert_panel.py` 交叉说明）。

**`thinking` 参数如何映射到实际 API**

- 在 `chat` 中，仅当 `complexity != "simple"` 时设置（第 83–91 行）：  
  - `extra_body = {"chat_template_kwargs": {"enable_thinking": thinking}, "top_k": 20}`（第 84 行）；  
  - 若 `thinking` 为真：`presence_penalty=1.5`，`temperature=1.0`，`top_p=0.95`（第 85–88 行）；  
  - 若 `thinking` 为假：`top_p=0.8`（第 89–90 行）。  
- **`config.yaml` 的 `ai.thinking`（off/synth/full）与本文件**：`ModelRouter` 只存储字符串，**不**把 off/synth/full 映射为 API 参数；映射发生在调用方（例如 `ai/expert_panel.py` 第 414、438、474、554 行）：Round1/R2/主持人挑战在 `thinking_mode == "full"` 时 `thinking=True`；Round3 综合在 `thinking_mode in ("synth", "full")` 时 `thinking=True`。这与 `SYSTEM_GUIDE.md` 第 203–206 行描述一致。

**异常处理（超时 / 回退）**

- **无**显式超时参数或 `timeout` 配置（本文件未出现）。  
- `client.chat.completions.create` 外层 `try/except`（第 93–141 行）：  
  - 若当前为 `complexity == "simple"` 且失败，则尝试用 `remote_client`、将 `model` 改为 `self.remote_model`，重建 `extra_body` 且 `enable_thinking=False`，再请求一次（第 119–138 行）；二次失败返回 `{"content": "", "error": "Both models failed: ..."}`（第 139–140 行）。  
  - 若当前已是 remote（或非 simple 路径失败），返回 `{"content": "", "error": str(e)}`（第 141 行）。  

**Review 关注点**

- `thinking_mode` 在 `ModelRouter` 内写入但未使用，易让读者误以为路由层已处理 off/synth/full。  
- Remote `base_url` 缺省为 `None` 时依赖 OpenAI 客户端行为，配置缺失可能在运行时暴露。  
- Local 失败回退 remote 时返回字典字段少于成功路径（例如未必含 `usage`），调用方需兼容。  
- Auto 复杂度仅基于字符长度与关键词，**无**任务类型枚举与 orchestrator 对齐的显式契约。

---

### `ai/context_budget.py`

**做什么**

- 模块文档（第 1–43 行）：在**全局字符预算**下组装多段 prompt 片段；超预算时按**优先级**先压缩低优先级片段，每段保留不少于 `min_chars`；避免多段各自截断导致总 prompt 失控膨胀。

**公开 API（类与方法签名）**

- `@dataclass class ContextBudget` — 第 60–71 行；属性 `total_chars: int = 60_000`，`pieces: list[_Piece]`。  
- `def add(self, name: str, content: str, priority: int = 50, min_chars: int = 500) -> "ContextBudget"` — 第 72–87 行。  
- `def render(self) -> list[tuple[str, str]]` — 第 90–145 行。  
- `def format_report(self) -> str` — 第 147–172 行。  
- `def concat(self, joiner: str = "\n\n") -> str` — 第 174–177 行。  

内部数据类 `_Piece`（第 49–56 行）非公开导出，但 `render`/`format_report` 会填充 `rendered`、`truncated`。

**算法（`render`，第 90–145 行）**

- 若总原始长度 ≤ `total_chars`：逐段原样输出，无截断（第 105–111 行）。  
- 否则：按 `priority` 降序（同优先级按插入顺序）排序（第 115–117 行）；先为每段预留 `min(min_chars, len(content))` 作为 `reserved`，从预算中扣除得到 `remaining`「额外池」（第 119–125 行）；再按优先级分配每段允许长度；若需截断则取 `content[:allowed - 20] + "\n... [truncated]"`（第 138–140 行）。  
- 文档说明：若某段 `min_chars` 已超剩余预算，仍可能整体超出软上限（第 97–99 行注释）。

**常量**

- **无**独立的「token-to-char 比例」常量；预算单位为**字符**（`total_chars`）。  
- 默认 `total_chars = 60_000`（第 69 行）。  
- 截断时预留 20 字符给后缀标记（第 139 行）。

**Review 关注点**

- 与「token 预算」命名心理预期不一致：实现是**字符**级软上限。  
- `render()` 多次调用时，若已处于截断分支，重复调用会基于同一 `pieces` 重复分配逻辑；`format_report` 在 `rendered` 全空时会调用一次 `render()`（第 152–154 行）。  
- `add` 对空字符串直接跳过（第 80–81 行），调用方需知悉「未注册」与「注册了空」不等价。

---

### `ai/utils.py`

**函数签名 + 一句话职责**

- `def parse_json_from_llm(content: str, fallback: Optional[dict] = None) -> dict`（第 17–31 行）— 从可能含杂质的 LLM 输出中截取首末 `{}` 子串并 `json.loads`，失败则返回 `fallback` 或 `{}`。  
- `def extract_relevant_sections(text: str, keywords: list[str], context_lines: int = 15, max_chunks: int = 30) -> str`（第 36–73 行）— 按关键词在源码行中匹配，合并重叠窗口，输出带行号的片段拼接。  
- `def build_keyword_variants(func_name: str) -> list[str]`（第 76–80 行）— 生成某 ADAS 功能名的常见 C 标识符变体列表。  
- `def get_func_fields(func_name: str) -> dict`（第 219–227 行）— 返回 `FUNC_FIELD_MAP` 中该功能字段映射；未知名返回带 `_unknown: True` 的空模板（第 205–216、227–228 行）。  
- `def infer_side_prefix(func_name: str, config: dict | None = None) -> str`（第 231–250 行）— 优先用 `FUNC_FIELD_MAP` 的 `side_prefix`，否则尝试 `config["functions"].front/rear` 列表（第 244–249 行）。  

**模块级常量**

- `ALL_FUNCTIONS: list[str]`（第 85 行）— 8 个功能名列表。  
- `FUNC_FIELD_MAP: dict[str, dict]`（第 89–202 行）— 各功能 state/enable/warnings/error_status/ego_topics 等映射。  

**Review 关注点**

- `parse_json_from_llm` 仅用第一个 `{` 与最后一个 `}`，对嵌套或多 JSON 块脆弱。  
- `get_func_fields` 对未知功能显式 `_unknown`，利于上层诚实降级（与静默默认某一功能对比）。  

---

### `ai/__init__.py`

**对外暴露符号（第 1–4 行）**

- `from .model_router import ModelRouter`  
- `from .orchestrator import Orchestrator`  
- `from .code_learner import CodeLearner`  
- `from .frame_analyzer import FrameAnalyzer`  

---

## Part B：脚本与工具

### `scripts/smoke_test_learner.py`

- **目的**（文件头第 2–9 行）：在不调用真实 AI 的前提下验证 `CodeLearner` 相关配置、初始化、源码可发现性、关键词片段提取、学习状态、Memory L6、`ensure_overview_docs` 签名、包导出、`AutoDream.try_dream` 签名、`parse_data.py` 删除、`ContextBudget` 行为、`_understand_problem` 预过滤、`DataProbe`/`VariableQueryPlanner`、与 `Orchestrator` 的 Phase 3.57 / `ContextBudget` 接线等。  
- **运行方式**：`PROJECT_ROOT` 为脚本上级目录（第 16–17 行）；加载 `.env`（第 19–20 行）；作为脚本执行时 `python scripts/smoke_test_learner.py`（隐含，第 380–381 行）。  
- **生成什么**：主要为控制台打印；可选路径下不写案例报告；**不**默认写 `source_docs` 下 MD（第 97–99 行刻意不调用会覆盖文档的 `ensure_overview_docs`）。  
- **断言**：多处 `if ...: return 1` 作为硬检查（如第 106–108、116–118、127–128、134–136、178–180、199–205、232–234 等）；整体 `main() -> int` 成功返回 0（第 377 行）。

### `scripts/ollama_models_on_d_drive.ps1`

- **作用**（第 1–4 行）：在 `%USERPROFILE%\.ollama\models` 与 `D:\RamboStar\ollama\models` 之间建立**目录联接（Junction）**，使 Ollama 仍用默认路径而权重落在 D 盘；第 24–25 行提示勿再设 `OLLAMA_MODELS`。  
- **流程要点**：创建目标目录与 `blobs`/`manifests`（第 10–12 行）；若已存在链接则 `rmdir` 联接（第 14–17 行）；若存在普通文件夹则抛错（第 18–19 行）；`mklink /J`（第 22 行）。  

### `tools/render_report_from_md.py`

- **作用**（第 1–19 行）：从已有 `report.md` 剥离机器生成 front matter，将正文与最小 stub `FrameStore` 交给 `ai.visualizer.build_report`，生成 HTML 供可视化冒烟/预览。  
- **CLI**（第 117–123 行）：  
  - `case_dir`：`Path`，含 `report.md` 的案例目录；  
  - `task_type`：可选，`choices=["diagnose","tune","verify","query"]`，默认 `diagnose`；  
  - `--func`：默认 `FCTB`。  

### `tools/run_tpe_smoke.py`

- **作用**（第 1–22 行）：对真实案例目录加载 BAG/BLF，构建 `FrameStore`，Gather 状态跳变，加载 `signal_mapping`/`variable_chains`，运行 `TemporalPatternEngine`，打印与专家面板同形态的 TPE 文本块；**不**调用 LLM。  
- **CLI**（第 94–104 行）：`case_dir`；`--func`；`--time-window T_START T_END`；`-o/--output` 可选写文件。  
- **退出码**（第 19–22、199–200 行）：0 表示至少一次 pattern 触发；1 表示无触发；2 表示加载/目录错误。  

### `tools/__init__.py`

- 文件为空：无包级导出。

---

## Part C：测试

### `tests/test_temporal_pattern_engine.py`

- **覆盖场景**（测试列表见第 407–414 行）：  
  1. `test_temporal_analyzer_detects_brief_pulses`（第 137–153 行）— 合成 AEBBA/AEBIB 短脉冲时间线，`TemporalAnalyzer` 识别 `runs_by_value`、`pattern_tag`。  
  2. `test_pattern_extractor_on_real_adas_func`（第 156–199 行）— 若存在 `D:/cr60_light`，在真实 `adasFunc.c` 上抽取 `HoldRelease` 并断言 FCTB/AEBBA 相关行号范围；否则打印跳过。  
  3. `test_causal_aligner_triggers_on_brief_pulses`（第 220–255 行）— 合成 `CodePattern` + 短脉冲 + 状态跳变，`CausalAligner` 应 `verdict=triggered` 且多次 `hits`。  
  4. `test_causal_aligner_silent_when_signals_always_high`（第 258–278 行）— 对照组恒高，`not_triggered`。  
  5. `test_causal_aligner_handles_accumulate_reset`（第 365–403 行）— `Accumulate` 模式 + 车速样本，断言不崩溃及 `verdict` 为允许集合之一。  
  6. `test_tpe_facade_end_to_end_on_fcatb001`（第 316–362 行）— mock `FrameStore` + 可选真实 `source_root`，端到端 `TemporalPatternEngine.run`。  
- **数据**：合成 `SignalTimeline`（第 62–107、298–313 行）；`SYNTH_SIGNAL_MAPPING` 字典（第 202–217 行）；可选本地路径 `D:/cr60_light`（第 158–160、320–323 行）。  
- **运行**：文档字符串第 19–23 行建议 `python -m tests.test_temporal_pattern_engine`；`main()` 汇总失败数（第 406–428 行）。

---

## Part D：固化知识（`source_docs/`）

### 功能文档 `FUNC.md`（BSD/LCA/DOW/RCW/RCTA/RCTB/FCTA/FCTB）

- **格式公约**（以 `BSD.md` 第 1–30 行为例）：一级标题为「# &lt;功能&gt; 功能分析」；`## 1. 功能概述` 段落说明；`## 2. 状态机` 下列出状态枚举、转换条件与代码位置引用（如 `ASWIN_SystemState.c` 行号）。  
- **由什么生成 / 何时刷新**（`SYSTEM_GUIDE.md` 第 192–194 行）：`**AI 生成**`；**失效/刷新**：「手动删除后重新生成」。另：`CodeLearner`/`ensure_overview_docs` 与 `source_docs/.overview_hashes.json` 在工程内用于按**源码片段哈希**判定是否需刷新概述文档（见 smoke 脚本第 139–159 行与 `.overview_hashes.json`），与 SYSTEM_GUIDE 表格表述可对照 review 是否完全一致。

### `signal_chain.md`

- **分类**（第 1–4、29 行及文内结构）：`Vehicle Dynamics`、`Function Switches`、后文延续 **Safety Systems / Door & Body / Wheel Speed / Other**（`SYSTEM_GUIDE.md` 第 123–125 行归纳与文件内 `##` 标题一致）。  
- **格式**：每个分类下 Markdown 表格列 `CAN Signal | Internal Variable | Full Path | Type | Transform`（第 7–8 行）；文首注明由 `RteComMapping.c` 自动生成及映射条数（第 3–4 行）。

### `signal_mapping.json` / `variable_chains.json`

- **`signal_mapping.json` schema**（第 1–13 行）：顶层 `source_hash`、`source_file`、`mapping_count`；`mappings[]` 元素含 `can_signal`、`internal_var`、`internal_full_path`、`transform`、`scaling`、`data_type`、`direction`。  
- **`variable_chains.json` schema**（全文 77 行）：`struct_aliases`、`alias_details`、`ambiguous`、`raw_copies[]`（`global_var`、`param_name`、`param_type`、`function`、`copy_type`、`source_file`）、`rte_write_prefixes`、`scanned_files`。  
- **生成与失效**（`SYSTEM_GUIDE.md` 第 78–110、187–191 行）：二者均为**确定性、无 AI**；`signal_mapping` 在 `RteComMapping.c` SHA256 变更时失效；`variable_chains` 手动删除或 AutoDream 刷新；`signal_chain.md` 随 `signal_mapping.json`。

### `FUNC_conditions.json`（8 份）

- **共有字段结构**（综合 `FCTA_conditions.json`、`LCA_conditions.json`、`FCTB_conditions.json`）：  
  - 顶层 `function`；  
  - `system_state.state_values`（状态码→名称）；  
  - `system_state.transitions[]`：`from`、`to`、`conditions[]`，条件项常含 `condition`、`variable`、`threshold`、`source`（及可能的 `note`）；  
  - `ego_speed_ranges`（及 FCTA 中 `target_speed_ranges`）— 嵌套 `active`/`deactive`/`detect` 等，内含 `low`/`high`/`unit` 等；  
  - `external_suppression[]`：`source_system`、`condition`、`variable`、`can_signal`、`suppression_trigger`、`normal_value`、`effect`、`source`，及可能出现的 `_can_resolved`（见 `FCTA_conditions.json` 第 259–314 行）；  
  - `other_conditions[]`：`category`、`condition`、`variable`、`threshold` 等（第 316–333 行样式）。  
- **极性字段**：`suppression_trigger` / `normal_value` 见 `FCTA_conditions.json` 第 265–310 行；`SYSTEM_GUIDE.md` 第 131–141 行对 AI 提取与极性规则有文字说明。

### `code_patterns.json`

- **结构**（第 1–30 行）：`source_hash`、`pattern_type_catalogue`（模式类型→说明字符串）、`patterns[]`。  
- **每条 pattern**：`pattern_type`、`file`、`line_start`、`line_end`、`function`（C 函数名）、`trigger_condition`、`trigger_variables`、`consequence_variables`、`adas_function`、`snippet`、`notes`。  
- **说明**：仓库该文件中**无** `extracted_at`、`focus`、`raw` 等字段名（已 grep 确认）。

### `parameters.json`

- **结构**（第 1–25 行）：`source_hash`、`count`、`parameters[]`；每项含 `name`、`func`、`category`、`value`、`value_raw`、`unit_hint`、`file`、`line`、`comment`。

### `output_mapping.json`

- **结构**（第 1–8 行）：`source_hash`、`mapping_count`、`mappings[]`；每项含 `can_signal`、`expression`、`direction`（示例为 `"write"`）。

### `variables.json` / `variable_chains.json` / `radar_knowledge.json`

- **`variables.json`**：JSON **数组**；元素含 `name`、`type`、`function`、`source_file`、`description`、`possible_values`（见第 1–24 行）。用途在 `SYSTEM_GUIDE.md` 第 194 行记为「关键变量目录」，AI 生成、手动删除后重新生成。  
- **`variable_chains.json`**：见上，用于 **g_DTCCode 等别名与 Rte 前缀**，支撑内部变量到 CAN 的追溯（`SYSTEM_GUIDE.md` 第 94–110 行）。  
- **`radar_knowledge.json`**：顶层 `description`；`can_id_to_radar`、`topic_to_radar`、`warning_status_raw_byte_map`（含 `bytes` 映射）、`a2l_to_egoCarInfo`（`mappings` 对象）、`wfAutosarData_structure`、`adas_functions`（rear/front 列表与 `system_state_enum`）等（第 1–99 行已覆盖主要块）。

### `.overview_hashes.json`

- **内容**（全文 11 行）：键为 8 个功能名（BSD、LCA、…、FCTB）对应 **16 字符十六进制**哈希字符串；`_updated_at` ISO 时间戳。用于与当前源码抽取片段哈希比对以决定是否重生成对应 `FUNC.md` 类概述（与 `smoke_test_learner.py` 第 139–159 行描述一致）。

### `LCA_conditions.json` / `FCTA_conditions.json` / `FCTB_conditions.json`（样本字段）

- **`LCA_conditions.json`**（第 1–85 行样本）：`function`、`system_state`、`transitions` 内 `conditions` 使用 `condition`/`variable`/`threshold`/`source`；另文件后部含 `ego_speed_ranges`、`external_suppression`（grep 第 179、208 行）。  
- **`FCTA_conditions.json`**：除 `system_state` 外，展示完整的 `ego_speed_ranges`、`target_speed_ranges`、`external_suppression`（含 `suppression_trigger`/`normal_value`）、`other_conditions`（第 230–333 行）。  
- **`FCTB_conditions.json`**（第 1–119 行样本）：同风格的 `function`、`system_state.transitions`；阈值与源码引用为 FCTB 语境（英/中混排以文件为准）。

### `SYSTEM_GUIDE.md`

- **定位**（第 1–18 行）：系统全功能说明，含三种模式、管线步骤、信号与条件、专家面板、记忆与缓存等。  
- **维护者**：文档**未**写明固定负责人；从内容看为与仓库同步的说明性文档，**缓存/失效表**（第 185–194 行）应与实现一并维护。另：第 210–214 行目录结构中仍列出 `parse_data.py`、`code_analyzer.py` 等，与当前树是否一致可作为 **review 项**（以实际仓库为准）。

---

## Part E：环境文件

### `.env.example`

- **变量**（第 4–10 行）：`LOCAL_BASE_URL`、`LOCAL_API_KEY`、`REMOTE_BASE_URL`、`REMOTE_API_KEY`。  
- **说明**：注释写明复制为 `.env` 后填写（第 1–2 行）。**未**列出其它键；实际运行是否还依赖更多变量以 `cli`/配置加载为准（本文件未写）。

### `.gitignore`

- **当前忽略项**（全文第 1–31 行）：`.env`；`cr60_light_arbe/`、`cr60_light_convert_radar_dataset/`；`__pycache__/`、`*.py[cod]`、`*.egg-info/`、`dist/`、`build/`、`*.egg`；`cases/**/*.bag`、`cases/**/*.blf`；`.vscode/`、`.idea/`、`.cursor/`；`.DS_Store`、`Thumbs.db`；`memory/store/`。  
- **说明**：**未**包含 `*.log`、`cases/*/report.html` 等；若需忽略报告产物需另加规则。

---

## `msg_defs`（仅列清，未读内容）

- `D:\RamboStar\idea\radarAnalyze\msg_defs\canfd_sgu_pub.py`  
- `D:\RamboStar\idea\radarAnalyze\msg_defs\egoCarInfo.msg`  

---

以上行号均指向本次读取的仓库版本；若你本地有未保存修改，以实际文件为准。


---

# 附录：文档维护规则

## A. 何时更新本文档

以下任一变更发生时，**必须**同步更新对应章节：

1. **新增/删除/重命名** `.py` 模块或公开类/函数
2. **修改公开 API 签名**（参数增减、类型变更、默认值变更）
3. **修改 AI prompt 内容**（system prompt / user prompt 模板 / JSON schema 约束）
4. **修改缓存/失效策略**（hash 算法、mtime 逻辑、缓存路径）
5. **修改 magic number / 阈值**（如 `ContextBudget.total_chars`、`_PADDING_SEC`、`MAX_SOURCE_CHARS` 等）
6. **修改数据结构 schema**（FrameStore 表结构、JSON 文件 schema、`evidence` dict 字段）
7. **修改管线步骤顺序或新增步骤**（`run_diagnosis` 中的 step 编号与流程）
8. **修改专家面板配置**（专家角色、轮次数、fail_type 映射）
9. **修改记忆层级 API 或 AutoDream 门控条件**

## B. 更新方法

1. 定位变更所属章节（参考目录对照表）
2. 更新对应小节的：签名、数据结构、处理流程、AI 调用点、阈值/魔数、Review 关注点
3. 若变更涉及跨模块交互（如 orchestrator ↔ expert_panel 的 `data_summary` 拼装），**两侧章节都需更新**
4. 更新本文件顶部的「生成日期」为当前日期

## C. Review Checklist（供 AI 对照使用）

对每个模块，依次检查：

- [ ] 公开接口签名是否与代码一致
- [ ] 数据结构字段是否与代码一致（含 JSON schema）
- [ ] AI prompt 内容是否与代码中的字符串常量一致
- [ ] 缓存失效条件是否与代码逻辑一致
- [ ] 阈值/魔数是否与代码中的值一致
- [ ] 处理流程步骤顺序是否与代码执行顺序一致
- [ ] 依赖关系是否正确（哪些模块调用哪些模块）
- [ ] Review 关注点中提及的潜在问题是否仍然存在

## D. 跨章节依赖速查

| 生产方 | 消费方 | 数据 |
|--------|--------|------|
| parsers/case_loader | orchestrator._parse_case_data | CaseLoadResult (store, bag_meta, blf_meta, sync) |
| signal_mapper | orchestrator._run_tpe, _check_suppression_signals | signal_mapping dict, variable_chains dict |
| condition_extractor | orchestrator (conditions step) | {FUNC}_conditions.json |
| frame_analyzer | orchestrator (analyze step) | evidence dict, frame_analysis str |
| test_window_detector | orchestrator, frame_analyzer, data_probe | list[TestWindow] |
| pattern_extractor | tpe.TemporalPatternEngine | list[CodePattern] |
| temporal_analyzer | tpe.TemporalPatternEngine, causal_aligner | dict[str, TemporalFeature] |
| causal_aligner | tpe.TemporalPatternEngine | list[PatternEvidence] |
| tpe | orchestrator._run_tpe | TPEResult |
| problem_classifier | orchestrator (classify step) | ClassificationResult |
| variable_query_planner | orchestrator (probe step) | list[QueryPlan] |
| data_probe | orchestrator (probe step) | ProbeResult dict |
| expert_panel | orchestrator (diagnose step) | panel_result dict (final_verdict, expert_opinions, ...) |
| parameter_analyzer | orchestrator (params step, tune/verify only) | SensitivityReport, WhatIfEntry |
| context_budget | orchestrator (panel_prompt step) | truncated combined prompt str |
| visualizer | orchestrator (visualize step) | VisualizerResult (html_path) |
| memory_system | orchestrator, auto_dream, data_query_engine | L1-L6 读写 |
| code_learner | auto_dream Phase 0, orchestrator._ensure_source_docs | L6 JSON, overview MD |
| model_router | 几乎所有 AI 模块 | chat/simple/complex 统一接口 |

---

*文档结束*
