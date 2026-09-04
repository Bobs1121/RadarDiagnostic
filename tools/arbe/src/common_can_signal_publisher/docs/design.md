# common_can_signal_publisher 设计说明

## 目标

该功能包提供一个通用公共 CAN-FD 信号发布节点，不绑定具体项目名称。节点从 Kvaser CAN-FD 通道读取报文，按 DBC 解码全部信号，并以固定 20ms 周期发布一份聚合快照。

## 生成式消息

DBC 中信号较多，当前 `CR_DBC_V3.1_20250715.dbc` 包含 72 个报文、1704 个信号。为避免手写和漏字段，`scripts/generate_public_can_msg.py` 会生成：

- `msg/PublicCanSignals.msg`：每个 DBC 信号一个强类型字段，字段类型由 DBC 信号属性推导。
- `scripts/generated_signal_map.py`：运行时使用的 `(frame_id, signal_name) -> msg_field/type/index` 映射。
- `signal_valid`：按 `generated_signal_map.SIGNALS` 顺序排列，`1` 表示该信号启动后至少成功解码过一次。
- `signal_age_ms`：按 `generated_signal_map.SIGNALS` 顺序排列，表示该信号距离上次更新的毫秒数，`-1.0` 表示未收到过。

字段命名规则：

```text
m_<hex_can_id>_<dbc_message_name>_<dbc_signal_name>
```

例如 `0x15E CR_FD1 BSD_LCA_warningReqRight` 会生成类似 `m_15e_cr_fd1_bsd_lca_warningreqright` 的字段名。

### generated_signal_map.py 的作用

`PublicCanSignals.msg` 只定义 ROS 消息字段，运行时无法从字段名反推出它来自哪个 CAN ID 和哪个 DBC 信号。因此生成脚本同时生成 `scripts/generated_signal_map.py`，保存每个信号的来源、目标字段、ROS 类型和数组索引，例如：

```python
(0x15E, 'CR_FD1', 'BSD_LCA_warningReqRight', 'm_15e_cr_fd1_bsd_lca_warningreqright', 'uint8', 123)
```

节点启动后会把它整理成：

```text
(frame_id, signal_name) -> msg_field
msg_field -> ros_type
msg_field -> signal_index
```

收到 CAN 帧后，`cantools` 按 DBC 解码出信号名和值，节点再通过这个映射把解码值写入 `PublicCanSignals` 对应字段，同时更新 `signal_valid[index]` 和 `signal_age_ms[index]` 的依据时间。这个文件是 DBC 与 ROS msg 字段之间的稳定桥接层，避免在运行时重新猜测字段名，也避免手写 1704 个字段映射。

具体例子：

```python
(96, 'HCU_FD1', 'HCU_AccelPedalPosn_Diag', 'm_060_hcu_fd1_hcu_accelpedalposn_diag', 'float64', 0)
```

对应 DBC 片段：

```dbc
BO_ 96 HCU_FD1: 64 GW
 SG_ HCU_AccelPedalPosn_Diag : 79|8@0+ (0.3937,0) [0|100.395] "%" RSDS_R,RSDS_L,CR_L,CR_R
BA_ "GenMsgCycleTime" BO_ 96 10;
```

含义如下：

- `96` 是 CAN ID 的十进制写法，对应十六进制 `0x060`。
- `HCU_FD1` 是 DBC 报文名，报文长度为 64 字节。
- `HCU_AccelPedalPosn_Diag` 是该报文中的信号名，起始位 79，长度 8bit，Motorola 大端，无符号。
- `(0.3937,0)` 表示物理值计算公式为 `raw * 0.3937 + 0`，单位是 `%`。
- `GenMsgCycleTime=10` 表示该报文设计周期为 10ms。
- `m_060_hcu_fd1_hcu_accelpedalposn_diag` 是生成到 `PublicCanSignals.msg` 中的 ROS 字段名。
- `float64` 是该字段生成出来的 ROS 类型，因为该 DBC 信号有比例系数 `0.3937`，解码后是小数物理量。
- `0` 是该信号在 `SIGNALS` 中的索引，`signal_valid[0]` 和 `signal_age_ms[0]` 对应该信号。

运行时如果收到 `frame.id == 96` 的 CAN 帧，`cantools` 会按 DBC 解码出 `HCU_AccelPedalPosn_Diag` 的物理值。节点再通过 `(96, 'HCU_AccelPedalPosn_Diag') -> m_060_hcu_fd1_hcu_accelpedalposn_diag` 映射，把该值写入 ROS msg 的对应字段。

### 字段类型策略

当前版本已改为按 DBC 信号属性生成 ROS 字段类型，不再把所有信号统一生成为 `float64`。

生成规则：

- DBC 浮点信号，或带比例/偏移的物理量：生成 `float64`。
- 1bit 且无枚举定义的信号：生成 `bool`。
- 无比例/偏移的无符号整数信号：按 bit 长度生成 `uint8/uint16/uint32/uint64`。
- 无比例/偏移的有符号整数信号：按 bit 长度生成 `int8/int16/int32/int64`。
- 枚举/状态/计数器类信号通常生成整数类型，避免把枚举值浮点化。

这样做的优点是接口更接近 DBC 语义，布尔、枚举、计数器不会显示成 `0.0/1.0` 这类浮点值，rosbag 体积也比全 `float64` 更小。

需要注意：强类型字段不能统一使用 `NaN` 表示“未收到”。因此消息中增加了：

- `signal_valid[index]`：该信号是否收到过。
- `signal_age_ms[index]`：该信号距离上次更新多久。

### signal_valid 和 signal_age_ms

`signal_valid` 和 `signal_age_ms` 是两个数组，数组顺序与 `scripts/generated_signal_map.py` 中的 `SIGNALS` 完全一致。每个信号在 `SIGNALS` 中都有一个固定 `index`，该信号的有效状态和更新时间就放在同一个下标位置。

例如：

```python
(96, 'HCU_FD1', 'HCU_AccelPedalPosn_Diag', 'm_060_hcu_fd1_hcu_accelpedalposn_diag', 'float64', 0)
```

这个信号的字段值在：

```text
msg.m_060_hcu_fd1_hcu_accelpedalposn_diag
```

它的状态信息在：

```text
msg.signal_valid[0]
msg.signal_age_ms[0]
```

含义：

- `signal_valid[0] == 0`：节点启动后还没有成功收到并解析过这个信号，此时字段值不能当作真实车辆数据使用。
- `signal_valid[0] == 1`：节点启动后至少成功解析过一次这个信号，字段值来自最近一次 CAN 报文。
- `signal_age_ms[0] == -1.0`：该信号从未收到过。
- `signal_age_ms[0] == 3.5`：距离该信号最近一次更新已经过去约 3.5ms。
- `signal_age_ms[0] == 120.0`：该信号最近 120ms 没有更新，消费端可以根据业务判断是否过旧。

时间线举例：

```text
t=0ms   节点启动，还没有收到 HCU_FD1
        value=NaN, signal_valid[0]=0, signal_age_ms[0]=-1.0

t=5ms   收到 CAN ID 0x060，解析出 HCU_AccelPedalPosn_Diag=12.2047
        value=12.2047, signal_valid[0]=1, signal_age_ms[0]=0.0 左右

t=20ms  ROS 定时发布
        value=12.2047, signal_valid[0]=1, signal_age_ms[0]=15.0 左右

t=25ms  又收到 CAN ID 0x060，解析出 HCU_AccelPedalPosn_Diag=13.7795
        value=13.7795, signal_valid[0]=1, signal_age_ms[0]=0.0 左右
```

这样设计的原因是：当前消息字段已经按 DBC 生成了强类型。`float64` 可以用 `NaN` 表示“未收到”，但 `uint8`、`uint16`、`bool` 这类 ROS 强类型不能用 `NaN`。如果一个 `uint8` 字段默认是 `0`，它可能表示“真实值就是 0”，也可能表示“还没收到过”。所以必须用 `signal_valid` 单独区分。

`signal_age_ms` 用于判断数据新鲜度。对于低频报文或异常掉线报文，字段会继续保持最后一次值；消费端应该结合 `signal_age_ms` 判断这个值是否还能使用。

### 发布消息示例

实际 `PublicCanSignals` 有 1704 个 DBC 信号字段，下面只截取几个字段作为例子。假设节点运行在 Kvaser channel 3，当前已经收到过 `HCU_FD1` 和 `ECM_FD1` 中的部分信号，某一次 20ms 定时发布的消息可以理解为：

```yaml
header:
  stamp:
    secs: 1717000000
    nsecs: 120000000
  frame_id: "can3"
channel: 3
received_frame_count: 2580
decoded_frame_count: 2416

signal_valid: [1, 1, 1, 1, 1, ...]
signal_age_ms: [4.2, 4.2, 4.2, 4.2, 18.7, ...]

m_060_hcu_fd1_hcu_accelpedalposn_diag: 12.2047
m_060_hcu_fd1_hcu_brkpedalsts: 0
m_060_hcu_fd1_hcu_accelpedalposn_diagvalid: 1
m_060_hcu_fd1_hcu_brkpedalstsvalid: 1
m_079_ecm_fd1_engspd_0x079: 856.0
```

这个例子的含义：

- `header.frame_id="can3"` 和 `channel=3` 表示这条 ROS 消息来自 Kvaser 3 号通道。
- `received_frame_count=2580` 表示节点从 CAN 驱动读到过 2580 帧。
- `decoded_frame_count=2416` 表示其中 2416 帧成功按 DBC 解码并更新了至少一个信号。
- `m_060_hcu_fd1_hcu_accelpedalposn_diag=12.2047` 是 DBC 信号 `HCU_AccelPedalPosn_Diag` 的物理值，单位来自 DBC，这个信号单位是 `%`。
- `m_060_hcu_fd1_hcu_brkpedalsts=0` 是制动踏板状态类信号，因为 DBC 定义为整数/枚举类，所以消息里保持为整数类型。
- `signal_valid[0]=1` 表示 `m_060_hcu_fd1_hcu_accelpedalposn_diag` 启动后至少收到过一次。
- `signal_age_ms[0]=4.2` 表示这个油门踏板信号距离最近一次 CAN 更新约 4.2ms。

如果某个信号启动后一直没有收到过，消息可能是：

```yaml
signal_valid: [0, ...]
signal_age_ms: [-1.0, ...]
m_060_hcu_fd1_hcu_accelpedalposn_diag: .nan
```

这时即使字段里有默认值，也不能当作真实车辆数据使用，消费端应以 `signal_valid[index]` 为准。

### ROS 类型兼容性

`PublicCanSignals.msg` 中使用的都是 ROS msg 原生支持的类型，没有使用 Python 专属类型或非 ROS 类型。当前包含：

- `std_msgs/Header`
- `uint8`
- `uint32`
- `uint8[]`
- `float32[]`
- `float64`
- `bool`
- `uint8/uint16/uint32/uint64`
- `int8/int16/int32/int64`

因此“有不是 ROS 有的类型吗”这个问题已经解决。生成脚本会把 DBC 类型转换为 ROS msg 支持的基础类型，运行时再按这些类型写入消息字段。

当前 DBC 生成结果大致为：

```text
float64: 824
uint8:   873
uint16:  1
uint32:  5
uint64:  4
```

## 运行行为

- CAN 参数与现有 `common_can_warning_publisher` 一致：仲裁域 500K，数据域 2M。
- 节点持续非阻塞读取 CAN 队列。
- 每收到一帧可被 DBC 解码的报文，就更新对应信号的最新值缓存。
- 定时器按 `~publish_period_ms` 发布当前快照，默认 20ms。
- 尚未收到过的浮点信号值为 `NaN`，整数/布尔信号为 ROS 默认值；是否真实有效以 `signal_valid` 为准。

### 不同 CAN 周期下的处理逻辑

当前节点采用“收帧更新缓存，固定周期发布快照”的逻辑：

- CAN 接收线程持续读取总线。
- 某个报文到达时，只更新该报文内包含的信号字段。
- 20ms 定时器发布一次完整 `PublicCanSignals`，里面包含所有信号的最新缓存值。
- 低频信号不会被强行插值；在下一帧到达前，会保持上一次收到的值。
- 启动后从未收到过的信号 `signal_valid=0`、`signal_age_ms=-1.0`。

举例：

```text
信号 A 所在报文周期 10ms
信号 B 所在报文周期 100ms
节点发布周期 20ms
```

时间线示例：

```text
t=0ms    收到 A=1，收到 B=50，发布 A=1, B=50
t=10ms   收到 A=2
t=20ms   收到 A=3，发布 A=3, B=50
t=40ms   收到 A=5，发布 A=5, B=50
t=60ms   收到 A=7，发布 A=7, B=50
t=80ms   收到 A=9，发布 A=9, B=50
t=100ms  收到 A=11，收到 B=51，发布 A=11, B=51
```

这表示发布 topic 的周期是固定 20ms，但每个字段的实际新鲜度仍由原始 CAN 报文周期决定。对于录制、对齐、上位机监控、离线分析，这是商用工具里常见且合理的做法，因为它提供了统一频率的数据快照，同时保留了低频信号的最新状态。

换句话说：

- 周期小于 20ms 的 CAN 信号：两次 ROS 发布之间可能更新多次，ROS msg 中发布的是最近一次收到的值，中间变化不会逐次发布。
- 周期等于 20ms 的 CAN 信号：理想情况下每次 ROS 发布前更新一次，但实际时间顺序取决于 CAN 到达和 ROS 定时器调度。
- 周期大于 20ms 的 CAN 信号：不是每次 ROS 发布都会有新值；没有新 CAN 帧时，字段保持上一次值继续发布。

需要注意的是，如果某个周期 100ms 的报文中断，字段会继续保持最后一次值；消费端应结合 `signal_age_ms` 判断数据是否过旧。对于更严格的量产级在线控制链路，建议后续增加：

- 按 DBC 报文周期配置超时阈值，超时后置 `NaN` 或置无效。
- 按报文维度发布 `valid/stale`，减少消费端逐信号判断成本。

本节点当前定位是“录制和上位机通用发布”，不是闭环控制输入，因此固定周期快照加最新值缓存符合实际使用场景。

## 主要参数

- `~channel`：Kvaser 通道号。
- `~dbc_path`：DBC 文件路径，默认指向本包 `config/CR_DBC_V3.1_20250715.dbc`。
- `~topic`：发布话题，默认 `/public_can/signals`。
- `~publish_period_ms`：发布周期，默认 `20`。

## DBC 更新流程

DBC 文件更新后，如果只是改了信号的系数、偏移、枚举值、报文长度等解码属性，且信号名/报文名/信号数量没有变化，可以直接替换 `config` 中的 DBC 后启动节点。

如果 DBC 增删了信号，或修改了报文名/信号名，则必须先重新生成 msg 和映射，再重新编译工作空间：

```bash
rosrun common_can_signal_publisher generate_public_can_msg.py \
  --dbc /home/lzq/BCSC/Recordv2.0/recordv2.0/src/common_can_signal_publisher/config/CR_DBC_V3.1_20250715.dbc
catkin_make --cmake-args -DCMAKE_POLICY_VERSION_MINIMUM=3.5
```

也可以直接用 `python3` 运行生成脚本，不依赖 `rosrun`：

```bash
python3 src/common_can_signal_publisher/scripts/generate_public_can_msg.py \
  --dbc /path/to/your.dbc
```

默认输出位置为：

```text
src/common_can_signal_publisher/msg/PublicCanSignals.msg
src/common_can_signal_publisher/scripts/generated_signal_map.py
```

如果需要，也可以手动指定输出路径：

```bash
python3 src/common_can_signal_publisher/scripts/generate_public_can_msg.py \
  --dbc /path/to/your.dbc \
  --msg /path/to/PublicCanSignals.msg \
  --map /path/to/generated_signal_map.py
```

当前节点运行时依赖默认位置的 `PublicCanSignals.msg` 和 `generated_signal_map.py`。如果生成结果改变了 `PublicCanSignals.msg`，需要重新编译工作空间：

```bash
catkin_make --cmake-args -DCMAKE_POLICY_VERSION_MINIMUM=3.5
```

总 launch 中已按 ch3/ch2 分别启动两个节点，默认发布到：

- `/public_can/ch3/signals`
- `/public_can/ch2/signals`

## public_can_signal_publisher.py 代码说明

`scripts/public_can_signal_publisher.py` 是运行时节点代码，负责打开 Kvaser CAN-FD 通道、读取原始 CAN 帧、按 DBC 解码、维护最新值缓存，并按固定周期发布 `PublicCanSignals`。

### 文件导入

```python
import os
import threading

import cantools
import rospy
from canlib import canlib

from common_can_signal_publisher.msg import PublicCanSignals
from generated_signal_map import SIGNALS
```

各模块作用：

- `os`：拼接默认 DBC 路径。
- `threading`：使用 `Lock` 保护共享数据。CAN 读取循环和 ROS 定时发布回调会访问同一份信号缓存。
- `cantools`：加载 DBC，并把 CAN 原始 payload 解码成信号名和值。
- `rospy`：ROS Python 节点、参数、Publisher、Timer、日志、时间戳。
- `canlib`：Kvaser 官方 Python canlib，用于打开 CAN-FD 通道并读取帧。
- `PublicCanSignals`：本包自动生成的 ROS msg。
- `SIGNALS`：自动生成的 DBC 到 ROS 字段映射。

### PublicCanSignalPublisher.__init__

`__init__` 完成节点初始化、参数读取、DBC 加载、映射表构建、缓存初始化、CAN 通道打开和定时器启动。

```python
rospy.init_node('public_can_signal_publisher', anonymous=True)
```

初始化 ROS 节点。`anonymous=True` 允许同一个脚本启动多个实例，因此 ch2/ch3 可以同时运行。

```python
self.channel = int(rospy.get_param('~channel', 0))
self.dbc_path = rospy.get_param('~dbc_path', ...)
self.topic = rospy.get_param('~topic', '/public_can/signals')
self.publish_period_ms = float(rospy.get_param('~publish_period_ms', 20.0))
```

读取私有参数：

- `~channel`：Kvaser 通道号。
- `~dbc_path`：DBC 文件路径。
- `~topic`：发布 topic。
- `~publish_period_ms`：发布周期，默认 20ms。

```python
self.db = cantools.database.load_file(self.dbc_path, strict=False)
```

加载 DBC。`strict=False` 用于兼容一些不完全严格的 DBC 写法，避免因 DBC 中的格式细节导致节点无法启动。

```python
for frame_id, _message_name, signal_name, field_name, ros_type, index in SIGNALS:
    self.signal_fields[(frame_id, signal_name)] = field_name
    self.signal_types[field_name] = ros_type
    self.signal_indices[field_name] = index
```

把生成文件中的列表转换成运行时快速查询表：

- `self.signal_fields[(frame_id, signal_name)] = field_name`：收到某个 CAN ID 的某个信号后，知道应该写入 ROS msg 的哪个字段。
- `self.signal_types[field_name] = ros_type`：写入前知道应该转成 `float`、`int` 还是 `bool`。
- `self.signal_indices[field_name] = index`：知道对应 `signal_valid` 和 `signal_age_ms` 的数组下标。

```python
self.lock = threading.Lock()
self.values = {...}
self.signal_valid = [0] * len(SIGNALS)
self.signal_last_update = [None] * len(SIGNALS)
self.received_frame_count = 0
self.decoded_frame_count = 0
```

初始化运行时缓存：

- `self.values`：每个 ROS 字段的最新值。
- `self.signal_valid`：每个信号是否成功解析过。
- `self.signal_last_update`：每个信号最近更新时间。发布时根据它计算 `signal_age_ms`。
- `self.received_frame_count`：从 CAN 驱动读到的总帧数。
- `self.decoded_frame_count`：成功解析并至少更新了一个信号的帧数。

```python
self.publisher = rospy.Publisher(self.topic, PublicCanSignals, queue_size=10)
self.can_bus = self._open_can_channel()
self.publish_timer = rospy.Timer(..., self._publish_snapshot)
```

创建 ROS Publisher，打开 CAN-FD 通道，并启动固定周期发布定时器。

### _open_can_channel

```python
bus = canlib.openChannel(self.channel, canlib.canOPEN_CAN_FD)
bus.setBusParams(canlib.canFD_BITRATE_500K_80P)
bus.setBusParamsFd(canlib.canFD_BITRATE_2M_80P)
bus.busOn()
```

打开 Kvaser CAN-FD 通道并上线：

- `canOPEN_CAN_FD`：以 CAN-FD 模式打开。
- `canFD_BITRATE_500K_80P`：仲裁域 500K，采样点 80%。
- `canFD_BITRATE_2M_80P`：数据域 2M，采样点 80%。
- `busOn()`：让通道进入工作状态。

这部分参数与原来的 `common_can_warning_publisher` 保持一致。

### _default_value

```python
if ros_type == 'bool':
    return False
if ros_type in ('float32', 'float64'):
    return float('nan')
return 0
```

根据 ROS 字段类型设置启动默认值：

- `bool` 默认 `False`。
- 浮点默认 `NaN`。
- 整数默认 `0`。

注意：默认值不代表信号有效。是否收到过要看 `signal_valid`。

### _coerce_value

```python
raw_value = getattr(value, 'value', value)
```

有些解码值可能是枚举对象或带 `.value` 的对象，这里先取出原始数值。

```python
if ros_type == 'bool':
    return bool(raw_value)
if ros_type in ('float32', 'float64'):
    return float(raw_value)
return int(raw_value)
```

按生成出来的 ROS 字段类型进行转换：

- `bool` 写入 Python `bool`。
- `float32/float64` 写入 Python `float`。
- 整数类型写入 Python `int`。

这样可以避免把枚举、计数器、布尔量全部写成浮点。

### _publish_snapshot

`_publish_snapshot` 是 ROS Timer 回调，默认每 20ms 执行一次。

```python
now = rospy.Time.now()
with self.lock:
    msg = PublicCanSignals()
```

取当前 ROS 时间，并加锁复制缓存。加锁是为了避免发布过程中 CAN 读取线程正在修改同一份缓存。

```python
msg.header.stamp = now
msg.header.frame_id = f'can{self.channel}'
msg.channel = self.channel
msg.received_frame_count = self.received_frame_count
msg.decoded_frame_count = self.decoded_frame_count
```

填写消息头和统计信息：

- `header.stamp`：本次发布 ROS 时间。
- `header.frame_id`：例如 `can2` 或 `can3`。
- `channel`：Kvaser 通道号。
- `received_frame_count`：已读取帧数。
- `decoded_frame_count`：已成功解码帧数。

```python
msg.signal_valid = list(self.signal_valid)
msg.signal_age_ms = [
    -1.0 if stamp is None else (now - stamp).to_sec() * 1000.0
    for stamp in self.signal_last_update
]
```

填写信号有效数组和信号年龄数组：

- `signal_valid` 直接复制缓存。
- `signal_age_ms` 根据当前时间减去每个信号最近更新时间计算。
- 从未收到过的信号写 `-1.0`。

```python
for field_name, value in self.values.items():
    setattr(msg, field_name, value)
```

把所有 DBC 信号的最新缓存值写入 ROS msg 对应字段。由于字段数量很多，不能手写赋值，所以用 `setattr` 动态写入。

最后：

```python
self.publisher.publish(msg)
```

发布完整快照。

### _decode_frame

`_decode_frame` 负责把一帧 CAN 数据解析成信号，并更新缓存。

```python
decoded = self.db.decode_message(
    frame.id,
    bytes(frame.data),
    decode_choices=False,
    decode_containers=True,
)
```

按 DBC 解码：

- `frame.id`：CAN ID。
- `bytes(frame.data)`：CAN payload。
- `decode_choices=False`：枚举信号输出数值，不输出字符串，便于写入强类型 ROS 字段。
- `decode_containers=True`：兼容 container message。

如果该 CAN ID 不在 DBC 中，或 payload 与 DBC 不匹配，会进入异常并返回 `False`。

```python
flat = {}
self._flatten(decoded, flat)
```

把 cantools 返回的嵌套结构拍平成 `{signal_name: value}`。普通 DBC 一般直接返回 dict，但 container message 可能返回 list/tuple/dict 嵌套结构。

```python
field_name = self.signal_fields.get((frame.id, signal_name))
```

通过 `(CAN ID, DBC 信号名)` 找到 ROS msg 字段。如果当前信号不在生成映射中，则跳过。

```python
self.values[field_name] = self._coerce_value(value, ros_type)
self.signal_valid[signal_index] = 1
self.signal_last_update[signal_index] = now
```

成功转换后更新：

- 最新值缓存。
- 有效标志。
- 最近更新时间。

如果本帧至少更新了一个信号：

```python
self.decoded_frame_count += 1
```

### _flatten

`_flatten` 是一个递归工具函数，用来处理 `cantools` 解码结果。

它支持三类结构：

- `dict`：普通信号字典，或嵌套字典。
- `list`：container message 可能返回列表。
- `tuple`：container message 中可能出现 `(message, signals)` 形式。

最终输出统一的：

```python
{
    "SignalNameA": value_a,
    "SignalNameB": value_b,
}
```

这样 `_decode_frame` 后续逻辑不用关心 cantools 的具体返回结构。

### run

`run` 是主循环，负责持续读取 CAN 帧。

```python
while not rospy.is_shutdown():
    try:
        while True:
            frame = self.can_bus.read(timeout=0)
            ...
            self._decode_frame(frame)
```

内部 `while True` 会尽可能把 Kvaser 驱动队列里当前已有的帧读完。`timeout=0` 表示非阻塞读取。

```python
except canlib.canNoMsg:
    pass
```

当队列暂时没有帧时，Kvaser 抛出 `canNoMsg`，这是正常情况，直接跳过。

```python
except canlib.canError as exc:
    rospy.logwarn('CAN读取异常: %s', exc)
```

其他 CAN 驱动异常会记录 warning，但节点不会立刻退出。

```python
rospy.sleep(0.0005)
```

每轮空闲后短暂 sleep 0.5ms，避免没有 CAN 帧时 CPU 空转过高。

### close

`close` 用于节点退出时释放资源：

```python
self.publish_timer.shutdown()
self.can_bus.busOff()
self.can_bus.close()
```

关闭 ROS 定时器、CAN 总线下线、关闭 Kvaser 通道。

### main 入口

```python
if __name__ == '__main__':
    node = PublicCanSignalPublisher()
    node.run()
```

脚本直接运行时创建节点并进入主循环。

异常处理逻辑：

- `rospy.ROSInterruptException`：ROS 正常退出。
- 其他异常：打印错误日志。
- `finally`：调用 `close()` 释放 CAN 资源。

## 后续可优化项

当前实现已经满足“录制和上位机通用发布”的使用要求。释放使用前建议注意以下几点：

- 实车/台架使用时，用 `rostopic hz /public_can/ch3/signals` 和 `/public_can/ch2/signals` 确认发布频率接近 50Hz。
- 用 `rostopic echo` 检查 `signal_valid` 是否逐步变为 `1`，以及 `signal_age_ms` 是否随 CAN 周期正常变化。
- 如果后续要作为在线控制输入，建议增加按 DBC `GenMsgCycleTime` 自动判断超时的逻辑；当前版本保留最后值，依赖消费端使用 `signal_age_ms` 判断是否过旧。
