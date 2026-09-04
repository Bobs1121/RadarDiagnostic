# FCTB批量回灌操作说明（含具体示例）

## 1. 目标

在不影响原有 bag+真值csv KPI模式 的前提下，新增 bag-only 批量回灌模式：

- 不需要真值csv也可以批量回灌。
- 回灌过程中仍会生成每个bag的报警轨迹csv（_algo_warning_trace.csv）。
- 基于该报警轨迹csv抽取FCTB（左/右）触发信息。
- 将文件夹内所有bag的FCTB触发信息汇总到同一个csv：batch_fctb_trigger_report.csv。

## 2. 两种模式说明（互不影响）

### 模式A：KPI模式（原逻辑）

- 勾选复选框：KPI Batch Mode (bag+csv pair)
- 行为：要求bag与csv按同基名配对，调用原有KPI脚本输出KPI结果。
- 配对位置：默认先找独立 GT CSV 文件夹；若未设置或未命中，再回退到 bag 同目录。
- 输出目录：当前运行目录下的 kpi_reports_20260512_153000

### 模式B：Bag-only FCTB模式（新增逻辑）

- 取消勾选复选框：KPI Batch Mode (bag+csv pair)
- 行为：只基于bag批量回灌，不要求真值csv。
- 输出目录：当前运行目录下的 fctb_reports_20260512_153000
- 汇总输出：batch_fctb_trigger_report.csv（一个文件，包含该文件夹全部bag的FCTB触发记录）

补充说明：

- 若当前选中的主雷达在某个 bag 中没有帧，插件会自动回退到当前 bag 内第一个有帧的雷达（支持回放锚点 0~4），避免批处理停在该 bag。

## 3. 关键按钮与控件名称（界面上看到的文字）

- Select Folder
- Select GT CSV Folder
- Start KPI Batch
- KPI Batch Mode (bag+csv pair)
- Read
- Play
- Stop

## 4. Bag-only FCTB模式完整操作流程（逐步点击）

1. 打开RViz里的该插件面板。
2. 点击 Select Folder。
3. 选择你的bag文件夹（例如：D:/cases/case_set_01）。
4. 确认复选框 KPI Batch Mode (bag+csv pair) 为未勾选状态。
5. 点击 Start KPI Batch。
6. 在确认弹窗里点击 Yes。
7. 等待批量回灌自动跑完。
8. 完成后会弹出结束提示，提示里包含FCTB汇总csv路径。
9. 到输出目录打开 batch_fctb_trigger_report.csv 查看所有bag的FCTB触发点。

## 4.1 KPI模式补充流程（GT CSV 不与 bag 同目录时）

1. 打开RViz里的该插件面板。
2. 点击 Select Folder，选择 bag 文件夹。
3. 点击 Select GT CSV Folder，选择 GT CSV 所在文件夹。
4. 保持 KPI Batch Mode (bag+csv pair) 为勾选状态。
5. 点击 Start KPI Batch。
6. 插件会优先按 `bag基名_corner_radar_gt.csv` 在所选 GT CSV 文件夹内匹配。
7. 若独立 GT CSV 文件夹未命中，插件会回退到 bag 同目录继续匹配。

说明：

- 这样可以解决 GT CSV 因权限问题无法与 bag 放在同一路径的问题。
- 匹配规则仍然是“同基名优先”，不会改动已有 KPI 输出文件名。

## 5. 输出文件说明

### 5.1 每个bag报警轨迹文件（中间文件）

- 文件名示例：bag_0001_algo_warning_trace.csv
- 主要字段：event_sec, radar_id, w1...w15
- 其中：
  - w14 对应 LeftFctb
  - w15 对应 RightFctb

### 5.2 整批FCTB汇总文件（最终定位文件）

- 文件名固定：batch_fctb_trigger_report.csv
- 字段：
  - bag_name
  - bag_path
  - event_ros_sec
  - event_gui_time_utc8
  - radar_id
  - frame_id
  - time_source
  - left_fctb
  - right_fctb

字段说明：

- event_ros_sec：ROS时间戳（秒）。
- event_gui_time_utc8：将ROS时间按 +8 小时转换后的可读时间字符串，转换方式与逐帧GUI时间显示保持一致。
- frame_id：触发时对应的帧号（优先雷达LGU帧号；回退时使用主雷达帧信息）。
- time_source：时间来源。
  - lgu_radar_stamp：来自对应雷达LGU时间戳。
  - main_radar_fallback：该雷达时间不可用时，回退到主雷达时间戳。

## 6. 具体数值示例

假设你选中的文件夹中有3个bag：

- rear_scene_a_001.bag
- rear_scene_a_002.bag
- rear_scene_a_003.bag

最终 batch_fctb_trigger_report.csv 可能如下（示例值）：

bag_name,bag_path,event_ros_sec,event_gui_time_utc8,radar_id,frame_id,time_source,left_fctb,right_fctb
rear_scene_a_001,D:/cases/case_set_01/rear_scene_a_001.bag,1715508072.433000,2024-May-12 15:07:52.433000,3,1287,lgu_radar_stamp,1,0
rear_scene_a_001,D:/cases/case_set_01/rear_scene_a_001.bag,1715508078.966000,2024-May-12 15:07:58.966000,4,1290,lgu_radar_stamp,0,1
rear_scene_a_002,D:/cases/case_set_01/rear_scene_a_002.bag,1715509005.120000,2024-May-12 15:23:25.120000,3,421,main_radar_fallback,1,1
rear_scene_a_003,D:/cases/case_set_01/rear_scene_a_003.bag,1715510044.007000,2024-May-12 15:40:44.007000,4,2023,lgu_radar_stamp,0,1

解释：

- 第1行表示：rear_scene_a_001 在 ROS时间 1715508072.433000 触发左FCTB；可读时间是 2024-May-12 15:07:52.433000，直接可对照GUI时间。
- 第2行表示：同一个bag在 15:07:58.966000（GUI可读时间）触发右FCTB。
- 第3行表示：该行 time_source=main_radar_fallback，表示该触发时间使用了主雷达时间回退值。

## 7. 排查建议（算法同学常用）

1. 先按 bag_name 聚类，看哪些bag反复触发。
2. 先按 event_gui_time_utc8 在GUI时间显示中直接定位。
3. 再用 frame_id 快速跳转帧或核对日志。
4. 结合 radar_id 判断是哪颗角雷达给出的FCTB触发。
5. 如果要看原始报警位细节，打开对应bag的 _algo_warning_trace.csv 对照 w1...w15。

## 8. 结论

- 是的，新增逻辑就是“先保存报警轨迹csv，再基于其抽取FCTB，最后汇总到单个csv”。
- 是的，所有bag关于FCTB的报警记录都在同一个 batch_fctb_trigger_report.csv。
- 是的，两种模式互不影响：
  - 勾选 KPI Batch Mode (bag+csv pair) 走原KPI流程。
  - 不勾选走新增Bag-only FCTB汇总流程。

## 9. 切包重置策略（连续场景推荐）

当前版本默认采用旧逻辑（连续场景友好）：

- 默认不因“切包动作”本身强制重置。
- 只在时间条件命中时进入首帧处理。

### 9.1 旧逻辑的首帧/重置条件

在 corner_radar_post_process_data_callback 中，满足以下任一条件会触发首帧逻辑：

1. RosbagTimeStamp == 0（首次帧或无历史时间基准）。
2. (TimeStamp - RosbagTimeStamp) < 0（时间回退）。
3. (TimeStamp - RosbagTimeStamp) > 1 秒（帧间隔过大）。

### 9.2 旧逻辑下会被重置的变量

1. 当 RosbagTimeStamp == 0：
  - algo_InitFlg = 1
  - algo_timeFrm = 0

2. 当时间回退 (TimeStamp - RosbagTimeStamp) < 0：
  - algo_InitFlg = 1
  - algo_timeFrm = 0
  - 触发 reSetCarData()，清零以下车辆状态：
    - actual_spd
    - yaw_rate
    - yaw_rate_sign
    - lat_accel
    - long_accel
    - steer_angle
    - steer_angle_sign
    - fl_whl_spd
    - fr_whl_spd
    - rl_whl_spd
    - rr_whl_spd

3. 当帧间隔 > 1 秒：
  - algo_InitFlg = 1
  - 不清零车辆状态。

4. 每帧结束后：
  - algo_InitFlg 会回写为 0，等待下一帧条件判定。

### 9.3 可选强制切包重置开关（默认关闭）

为兼容“批处理强隔离”需求，代码中保留了可选参数：

- /kpi/force_reset_on_bag_switch
  - false（默认）：采用上述旧逻辑，不强制切包重置。
  - true：切包时按 bag_switch_epoch 变化执行硬重置（适合强调包间隔离的一致性回归）。

建议：

- 若你的 bag 是同一连续场景按时间切分（例如每2分钟切包），建议保持默认 false。
- 若你的 batch 混入了来源不一、时间戳质量不稳定的数据，建议设为 true。
