# Cloud CAM 4 人协作开发方案

> 适用范围: 当前仓库阶段的内部协作开发
> 目标: 在不重写现有系统的前提下，支持 4 人并行推进，并降低接口冲突、联调阻塞和返工成本。

## 1. 项目现状判断

当前项目已经具备一条可运行主链路:

1. 上传 STEP 文件
2. 后端解析几何并落盘产物
3. 前端加载模型并展示特征
4. 推荐工艺参数
5. 生成 G-Code 与刀路
6. 恢复历史作业并下载产物

现阶段最关键的问题不是功能点不足，而是以下 4 个协作风险:

1. 前端流程状态集中在 App，容易多人改同一文件。
2. 3D 交互与普通业务 UI 耦合较高，调试门槛明显高于普通表单页。
3. 后端同步链路和异步链路并存，状态机与错误码尚未完全统一。
4. 几何解析和 CAM 计算属于重计算模块，接口不稳时会反复阻塞前后端联调。

因此，本项目不建议简单拆成“前端 2 人 + 后端 2 人”，而应按责任边界拆成 4 条开发线。

## 2. 4 人分工模型

### 2.1 角色划分

#### A. 前端流程与页面状态负责人

职责:

1. 负责上传、作业恢复、参数面板、结果面板、错误提示、下载流程。
2. 负责将主应用拆成更稳定的 UI 区块和状态区块。
3. 负责前端接口适配与页面状态一致性。

主责文件:

1. frontend/src/App.tsx
2. frontend/src/App.css
3. frontend/src/index.css

明确不负责:

1. 不主导 Three.js 场景内部逻辑。
2. 不直接修改 CAM 算法细节。

交付物:

1. 清晰的页面状态流转
2. 可恢复的作业视图
3. 稳定的参数编辑与错误展示

#### B. 前端 3D 交互与可视化负责人

职责:

1. 负责模型加载兼容性，包括 GLB、STL、OBJ。
2. 负责测量、选面、刀路叠加、渲染容错和性能优化。
3. 负责 3D 场景内的交互契约与展示效果。

主责文件:

1. frontend/src/components/ModelViewer.tsx
2. frontend/src/components/ToolpathViewer.tsx
3. frontend/src/components/ErrorBoundary.tsx

明确不负责:

1. 不主导上传流程、作业列表、业务按钮区逻辑。
2. 不直接改后端接口结构。

交付物:

1. 稳定的模型显示与刀路显示
2. 清晰的测量和装夹面交互
3. 大模型和长刀路场景下可接受的性能表现

#### C. 后端接口与任务编排负责人

职责:

1. 负责 API 契约、数据库模型、状态机、错误码和任务编排。
2. 负责同步接口与异步接口的一致性设计。
3. 负责 recent、detail、generate、artifacts 等接口的可恢复性。

主责文件:

1. backend/main.py
2. backend/database.py
3. backend/models.py
4. backend/routers/upload.py
5. backend/routers/cam.py
6. backend/routers/internal_jobs.py
7. backend/routers/jobs.py
8. backend/tasks.py

明确不负责:

1. 不负责 Three.js 交互实现。
2. 不主导几何算法和 OCL 策略本身。

交付物:

1. 统一状态机与错误码
2. 可稳定查询的作业详情接口
3. 可扩展到异步链路的任务提交与轮询能力

#### D. 几何解析、CAM 算法与工艺推荐负责人

职责:

1. 负责 STEP 解析、面信息提取、网格导出。
2. 负责 OpenCAMLib 接入、fallback 策略与刀路结果质量。
3. 负责 craftsman 推荐逻辑和特征契约。

主责文件:

1. backend/services/geometry_engine.py
2. backend/services/cam_engine.py
3. backend/routers/craftsman.py

明确不负责:

1. 不负责前端页面状态。
2. 不负责接口入口层的整体编排。

交付物:

1. 稳定的 topology 输出契约
2. 稳定的 CAM 结果与降级策略
3. 可解释的推荐参数来源

### 2.2 分工原则

1. 每个模块只允许 1 个 owner 对架构方向拍板。
2. 允许其他成员提 PR，但跨模块修改必须先同步 owner。
3. 公共契约改动必须先出文档，再改代码。
4. 所有人都可以提问题，但主责人负责最终收口。

## 3. 推荐代码边界

为减少冲突，建议按下面边界协作:

### 3.1 前端边界

建议把 App 中的职责拆成以下几个组件或模块:

1. UploadPanel
2. JobSummaryCard
3. RecentJobsList
4. CraftsmanPanel
5. GcodeResultCard
6. useJobState 或类似状态管理模块
7. types/job.ts 与 types/cam.ts

拆分目标:

1. A 角色主要维护业务视图和状态模块。
2. B 角色主要维护 3D 组件，不频繁改业务组件。

### 3.2 后端边界

建议把后端改动分为三层:

1. Router 层: 参数校验、返回结构、状态落盘入口
2. Service 层: 几何和 CAM 计算
3. Persistence 层: Job、CAMRecord、数据库辅助迁移

拆分目标:

1. C 角色主要改 Router 和模型。
2. D 角色主要改 Service。
3. C 与 D 之间通过输入输出数据结构协作，不互相侵入内部实现。

## 4. 必须先统一的公共契约

在四人正式并行前，先花半天到 1 天统一以下契约。

### 4.1 Job 状态机

建议统一成以下状态:

1. queued
2. parsing
3. parsed
4. parsed_mock
5. generating
6. done
7. failed

建议统一 stage:

1. queued
2. parsing
3. meshing
4. cam
5. completed

验收标准:

1. 同一 job 在同步链路和异步链路下，状态命名一致。
2. 前端只做状态显示映射，不推断后端内部逻辑。

### 4.2 错误码

建议先固定 5 个基础错误码:

1. E1001 文件校验失败
2. E2001 几何解析失败或降级解析
3. E3001 CAM 生成失败
4. E5001 文件写入失败
5. E9001 未知异常

验收标准:

1. 每次失败必须至少有 status、stage、error_code、error_message。
2. 前端错误提示优先展示 error_code 和用户可理解信息。

### 4.3 topology.json 契约

建议固定字段:

1. features.volume
2. features.bbox_x
3. features.bbox_y
4. features.z_depth
5. faces[].face_id
6. faces[].normal
7. faces[].center
8. render_file
9. fallback_render_file

验收标准:

1. 即使走 mock fallback，也必须满足同一字段结构。
2. 前端不因为解析来源不同而写两套逻辑。

### 4.4 cam_result.json 契约

建议固定字段:

1. estimated_time_minutes
2. stats.layers
3. stats.total_cut_length_mm
4. stats.strategy
5. toolpath_segments

验收标准:

1. 同步和异步链路返回结构一致。
2. 前端刀路渲染只依赖一套 toolpath_segments 结构。

## 5. 两周迭代排期建议

## 5.1 第 1 周目标: 稳定主链路

### A 角色

1. 拆分 App.tsx 的业务区块。
2. 统一上传、生成、恢复、下载四种页面状态。
3. 整理前端公共类型定义。

### B 角色

1. 稳定模型加载器和 fallback 逻辑。
2. 修正测量和选面交互边界。
3. 让刀路显示支持显隐与异常容错。

### C 角色

1. 统一 Job 状态机、错误码和返回体。
2. 统一 recent、detail、generate 的结构。
3. 确认同步链路为当前默认主链路。

### D 角色

1. 固定 topology 与 cam_result 的输出结构。
2. 统一 OCL fallback 策略说明。
3. 选 2 到 3 个样件作为标准回归输入。

### 第 1 周验收标准

1. 至少 1 个标准 STEP 样件可完整跑通上传到下载。
2. 页面刷新后可恢复历史作业。
3. 解析降级和 CAM 降级可被明确识别。
4. 前后端联调不再依赖口头说明字段含义。

## 5.2 第 2 周目标: 提高可扩展性与可联调性

### A 角色

1. 补充作业列表筛选、错误态、空态和加载态。
2. 提高页面交互一致性。

### B 角色

1. 优化大模型加载性能。
2. 优化长刀路渲染性能。
3. 提升 3D 错误边界的可恢复性。

### C 角色

1. 打通异步 jobs 接口的可用路径。
2. 保证 v1 和 v2 契约差异可控。
3. 梳理数据库字段与轻量迁移逻辑。

### D 角色

1. 提高非理想 STEP 文件的容错率。
2. 优化 CAM 统计信息输出。
3. 整理推荐参数的输入特征与回写记录。

### 第 2 周验收标准

1. 同一作业可通过 detail 接口恢复完整状态。
2. 异步接口至少可提交并查询任务。
3. 主要样件在 fallback 模式下仍能生成可视结果。
4. 各角色都有独立可交付模块，不依赖集中修改一个文件完成工作。

## 6. 联调机制

### 6.1 每日站会内容

每人只说 3 件事:

1. 昨天完成了什么
2. 今天准备做什么
3. 当前阻塞是什么，需要谁配合

每次站会控制在 10 到 15 分钟内，不做细节争论。

### 6.2 每周两次联调窗口

建议固定两个联调窗口:

1. 周二下午: 接口和字段对齐
2. 周五下午: 端到端回归与问题收口

联调会议必须只看 3 类内容:

1. 标准样件是否跑通
2. 返回结构是否一致
3. 阻塞是否需要调整 owner

### 6.3 标准联调清单

每次联调按以下清单执行:

1. 上传 STEP 文件是否成功
2. topology.json 是否生成
3. 模型是否可显示
4. craftsman 是否返回推荐参数
5. generate 是否返回 gcode_url
6. toolpath_segments 是否可被前端渲染
7. recent 和 detail 是否可恢复作业
8. 错误态是否能显示明确信息

## 7. Git 协作策略

### 7.1 分支策略

建议使用:

1. main: 仅保留可运行版本
2. develop: 日常集成分支
3. feature/*: 个人功能分支

要求:

1. 不允许多人长期共用同一功能分支。
2. 每个分支只解决一个明确问题。
3. 超过 3 天未合并的分支必须主动 rebase 或重新同步。

### 7.2 提交规范

建议提交信息至少包含:

1. 模块名
2. 动作
3. 目的

示例:

1. frontend: split job sidebar into panels
2. backend: unify job status and error codes
3. cam: normalize fallback toolpath contract

### 7.3 合并规则

PR 合并前至少满足:

1. 说明改动范围
2. 说明是否改了接口契约
3. 说明如何验证
4. 说明是否影响其他 owner 模块

涉及公共契约的 PR，至少需要 2 人确认:

1. 当前 owner
2. 受影响模块 owner

## 8. 验收与质量门槛

当前项目测试体系较弱，因此先采用“最小可执行门槛”。

### 8.1 前端门槛

每次合并前至少执行:

1. npm run lint
2. npm run build

### 8.2 后端门槛

每次合并前至少执行:

1. 上传一个标准 STEP 文件
2. 验证 topology.json 落盘
3. 验证 output.nc 或 cam_result.json 生成
4. 验证 recent 和 detail 接口返回完整字段

### 8.3 端到端门槛

每周至少做一次完整回归:

1. 上传
2. 解析
3. 预览
4. 推荐
5. 生成
6. 刀路显示
7. 下载
8. 历史恢复

## 9. 当前阶段最值得优先做的 6 件事

1. 把 frontend/src/App.tsx 拆分为业务组件和状态模块。
2. 把前端公共类型从组件文件里提出来。
3. 统一后端 Job 状态机和错误码。
4. 固定 topology.json 与 cam_result.json 契约。
5. 选定 2 到 3 个标准 STEP 样件作为联调基线。
6. 建立 develop 分支和 PR 合并规则。

## 10. 角色职责矩阵

| 模块 | A 前端流程 | B 前端3D | C 后端编排 | D 几何/CAM |
| :--- | :--- | :--- | :--- | :--- |
| 上传与页面状态 | R | C | C | I |
| 模型显示与交互 | I | R | I | C |
| 工艺参数展示 | R | I | C | C |
| Job 状态机 | I | I | R | C |
| 同步/异步接口 | I | I | R | C |
| 几何解析 | I | I | C | R |
| CAM 生成 | I | C | C | R |
| 历史作业恢复 | R | I | R | I |
| 错误码与可观测性 | C | I | R | C |

说明:

1. R = Responsible，直接负责交付
2. C = Consulted，必须参与评审
3. I = Informed，需要知情

## 11. 本方案的落地方式

建议按以下顺序执行:

1. 召开一次 30 分钟分工会，确认 4 个 owner。
2. 当场确认标准样件、状态机、错误码和联调节奏。
3. 当天建立 develop 分支和 PR 模板。
4. 第 1 周只做主链路稳定，不额外扩需求。
5. 第 2 周再逐步引入异步化和性能优化。

如果出现冲突，优先级如下:

1. 主链路可用性
2. 接口契约稳定性
3. 模块边界清晰度
4. 功能扩展速度

这份方案默认以“先稳住内部交付效率，再考虑 SaaS 工业化改造”为原则；等主链路稳定后，再继续推进 RFC 中的 PostgreSQL、对象存储、异步编排和多租户能力。