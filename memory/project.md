# Project Memory

## [2026-04-17 记忆整理 & 知识更新 v4]
角雷达问题分析系统，目标平台：TI AWR2E44P, 项目代码：cr60_light (GWM_B26 COEM)。

### 系统架构
- 感知层：adas/symmetry/perception/ (objAttribCal, track, postProcess, envModel)
- 功能层：coem/GWM_B26/components/AswPerception/func/adasFunc.c (8 功能状态机 + 阈值)
- 输出层：ASWOUT_OutCalc.c (报警输出协调、制动请求、左右雷达合并)
- 接口层：RteComMapping.c (CAN 信号读写), ASWIN_SystemState.c (系统状态管理)
- 调度层：AswIfSchedule.c -> asw_coem_Mainfunctin_20ms()

### 8 大功能
- 后角：BSD(盲区检测), LCA(变道辅助), DOW(开门预警), RCW(后方碰撞预警), RCTA(后方交叉交通警报), RCTB(后方交叉交通制动)
- 前角：FCTA(前方交叉交通警报), FCTB(前方交叉交通制动)
- **代码映射**: 代码中 RRCW 对应为 RCW

### 状态机通用定义
所有功能状态机遵循统一标准 (0-6):
0=None, 1=Init, 2=Standby, 3=Active, 4=Off, 5=Failure, 6=Passive

### 双状态机架构 [关键]
两套状态机**并行存在**，**共享同一组全局变量** (*SystemState):
1. **adasFunc.c 感知侧**: 在感知任务链 (postProcess→AdasFunc) 中执行
   - 输入：g_DTCCode(selfInspFlg/failureFlg/calibratingFlg), adasEnable
   - 写：全局 *SystemState + adasWarning->*SystemState
2. **ASWIN_SystemState.c 平台侧**: 在 20ms ASW 任务 (asw_coem_Mainfunctin_20ms) 中执行
   - 输入：GWM_Adas_SelfInspFinish(FIM 自检), GWM_*_AdasEnableCond(PERInputUpdate.adasEnable), 车身信号
   - 写：同一组全局 *SystemState
   - AdasEnable(): 用全局*SystemState 回灌 PERInputCapture.adasEnable
   - AdasStateActive(): Standby(2)→Active(3) 需要 PEROutput.adasWarning 非零
- **注意**: 两者可能被不同任务轮流改写，最终生效取决于调度顺序

### 左右雷达架构 [关键]
- 每根轴：右雷达 (RR/FR) 为公 CAN 出口，左雷达 (RL/FL) 经私 CAN 向右侧传送
  - 后轴：RL→(0x338/0x301)→RR
  - 前轴：FL→(0x339)→FR
- 右雷达整合：ASWOUT_OutCalc.c 中 max(本侧，对侧) 取大合并
- 无 #ifdef 区分左右，全靠 rbMPR_GetPoweronMR() 运行时分支 (ENM_POS_*)
- 故障码：PF_SLAVE_RADAR_MISSING (从雷达丢失)

### 信号链路 [关键]
公 CAN → RteComMapping_RxRunnable → PERInputUpdate/PERInputCapture:
- 功能开关：LCASwtReq→bBSDEnable/bLCAEnable, DOWSwtReq→bDOWEnable, RCTASwtReq→bRCTAEnable 等
- DTC 标志：AEBBAActv_0x137→bAEBBAActiveFlg, AEBIBActv_0x137→bAEBIBActiveFlg
- 变型控制：g_GWMSpecificVariant.bits (ZDU=RCTSDIDMerge, AAA=FCTSDIDMerge, BAA=DOW 门映射)
私 CAN → RteComMapping_RxRunnable_RLWarnSignal → g_RteComMapping_RLWarnSig:
- 仅 RR 接收 RL, 仅 FR 接收 FL
- 通过 RteComMapping_GetRL_*_GWM / GetFL_*_GWM 访问

### DBC 文件
- CR_DBC_V3.2_20260331.dbc (主 DBC)
- GAC_CR_FR&FL_Private_CAN_V1.3.dbc (前角私有 CAN)
- GWM_RearCorner_Pri_V3.0 (1).dbc (后角私有 CAN)

### BAG Topics
- /corner_radar/warning_status_raw (UInt8MultiArray) - 报警状态原始数据
- /wf/corner_radar/lgu_data_1~4 (wfAutosarData) - 4 路角雷达 AUTOSAR 数据
- /wf/objectlist_1~4 (wfObjectMsg) - 4 路目标列表
- /wf/ego_car_info/front_left|right/parsed (egoCarInfo) - 自车信息

### 分析方法
- 5 专家面板 × 3 轮研讨:
  1. 信号链路专家：CAN 信号映射、数据链路追踪
  2. 算法逻辑专家：adasFunc.c 报警判断、阈值逻辑
  3. 系统状态专家：双状态机交互、AdasEnable/AdasStateActive
  4. 感知目标专家：目标分类、跟踪、ROI 过滤
  5. 架构专家：左右雷达通信、合并逻辑

### 用户偏好
- 需要深入追溯数据链路：CAN 信号→内部变量→条件判断→结果
- 重视代码级别的精确分析，不接受泛泛而谈
- 希望定位到具体帧和变量值
- **核心偏好**: 必须包含“条件检查汇总”表格（阈值 vs 实际值 vs 满足状态）
- **新增偏好**: 对 FCTB 等制动功能，需重点分析“保压时间”与“风险消除（TTC=Inf）”的时序关系
- **新增偏好**: 针对“退出晚”或“退出早”类问题，需区分是“保压计时器逻辑”还是“外部抑制信号（如 AEBBAActv）”导致的时序差异

### 知识库状态
- [2026-04-12] 已完成 8 大功能源码状态机文档的结构化整合
- [2026-04-12] 新增双状态机架构知识、左右雷达从属关系、信号链路映射
- [2026-04-12] 升级为 5 专家面板研讨机制
- [2026-04-14] 新增 CAN信号↔内部变量 映射表 (signal_mapping.json, 91条)
- [2026-04-14] 新增外部抑制信号检测机制 (ConditionExtractor + CAN关联分析)
- [2026-04-15] **重大更新**: 整合 FCTB 高频故障模式，明确“左右信号值校验”、“保压时长阈值 (3.0s)”、“TTC=Inf 触发退出”及“外部抑制 (AEBBAActv)”四大根因。
- [2026-04-15] 清理重复模式，统一 FCTB 故障描述标准。
- [2026-04-17] **最新更新**: 修正 FCTB 退出逻辑认知，明确“退出晚”源于内部保压计时器（~2.8s）与外部 AEB 抑制信号的时序竞争；“退出早”源于 TTC=Inf 导致状态机提前回退。统一 FCTB 故障根因描述，移除重复模式。

注意：各功能的个案诊断结论存储在 memory/functions/<FUNC>.json 中，不在此处记录。