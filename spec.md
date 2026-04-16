# Cloud CAM 工业级云端加工管理平台系统规范 (Spec)

> **最后更新**: 2026-04-16 (v2 — 装夹面高亮/刀路坐标修正)

## 0. 关联文档

- SaaS 工业化改造 RFC: [rfc-saas-industrialization.md](rfc-saas-industrialization.md)
- 4 人协作开发方案: [team-collaboration-plan.md](team-collaboration-plan.md)

## 1. 项目愿景与定位
本项目定位于"**内部使用型 Web CAM 平台**"，面向车间和制造团队的内部工作流。允许操作人员通过浏览器直接完成模型上传、解析、刀路预览、G-Code 生成和下载的完整闭环，无需安装重型 CAM 软件。同时提供作业历史查询、参数推荐和回看能力，不追求大型 SaaS 复杂度，优先保证**上传 → 解析 → 预览 → 生成 → 下载** 单一主链路稳定可用。

---

## 2. 总体软硬件架构设计 (MVC 分离)
系统严格遵循前后端分离架构，划分为三个核心运行层：

### 2.1 交互表现层 (Frontend)
* **主框架**: `React 19` + `Vite 8` 构建的超速轻量化前端。
* **语言规范**: `TypeScript 6` + 严格检查 (`verbatimModuleSyntax`)。
* **样式引擎**: `TailwindCSS v4` (通过 `@tailwindcss/vite` 插件集成)，以暗色系 (`Slate-900`) 为主的现代工业质感 UI。
* **3D 驱动渲染**: 围绕 `Three.js 0.183` 生态群（`@react-three/fiber 9` 声明式引擎 与 `@react-three/drei 10` 特效库），完成了 OBJ/STL 网格模型载入和工业化影棚 (`<Stage>`) 渲染展示。
* **图标体系**: `lucide-react` 提供统一的线条图标。
* **HTTP 客户端**: `axios`，通过环境变量 `VITE_API_BASE_URL` 配置 API 地址。

#### 2.1.1 3D 交互功能
* **多模式工具栏**: 3D 预览区左上角悬浮工具栏，支持三种交互模式：
  * **旋转/平移** (Orbit): 鼠标拖拽旋转、右键平移、滚轮缩放。**所有模式下始终可用**。
  * **测量** (Measure): 在模型表面点击两点，自动计算并显示距离 (mm)，带端点标记和中点标签。
  * **选择装夹面** (Face Select): 点击模型表面选择 CNC 装夹底面。使用 **BFS 洪泛算法** 从点击三角形出发搜索所有共面三角形（法向偏差 <5°），生成贴合实际模型曲面的半透明橙色高亮网格，箭头指示加工 Z 轴方向（装夹面法向的反方向）。
* **刀路可视化叠加**: 生成 G-Code 后，3D 场景自动叠加显示刀路，刀路坐标经后端逆变换回模型原始坐标系，与模型精确对齐：
  * 红色线段 = G0 快速移动（非切削）
  * 青色线段 = G1 切削进给
  * 绿色球 = 起点，红色球 = 终点
  * 支持显示/隐藏切换
  * 底部图例条标注颜色含义
* **坐标辅助**: 右下角 Gizmo 坐标轴始终可见。
* **错误容错**: `ErrorBoundary` 组件包裹 3D 渲染区，防止 WebGL 崩溃影响整个应用。

#### 2.1.2 侧边栏 UI
* **上传区**: 拖拽/点击上传 `.step/.stp` 文件，前端限制 100 MB，带状态动画。
* **当前作业概览** (新增): 显示当前作业文件名、状态（已上传/解析中/生成中/已完成/失败）、进度条、错误提示；支持 Mock 降级状态标注。
* **最近作业列表** (新增): 显示最近 8 个作业历史，支持点击恢复任意历史作业，显示阶段、进度、错误信息，带刷新按钮。
* **模型特征卡片**: 显示体积、XY 尺寸、最大 Z 深度。
* **加工特征识别卡片**: 显示识别到的制造特征（孔、型腔、凸台）及其参数（直径/深度/范围），支持特征类型汇总统计。
* **工艺参数面板**: 显示专家推荐参数（背吃刀量、主轴转速、进给率），**用户可编辑覆写**。标注"专家推荐"或"默认值"来源。
* **刀具选配方案卡片**: 显示自动选配的粗加工刀具和各特征对应的精加工刀具，含选刀理由。
* **G-Code 结果卡片**: 显示预计加工时间、加工层数、切削总长度，提供 `.nc` 文件下载。
* **生成按钮**: 底部固定，带加载状态和禁用逻辑。

#### 2.1.3 前端关键文件
| 文件路径 | 职责 |
| :--- | :--- |
| `src/App.tsx` | 主应用：状态管理、上传/生成流程、侧边栏 UI、工具栏、**作业列表与恢复** (新增) |
| `src/components/ModelViewer.tsx` | 3D 模型渲染：OBJ/STL/GLB 加载、**共面洪泛面高亮**、测量、刀路叠加（模型坐标系直接渲染） |
| `src/components/ToolpathViewer.tsx` | 刀路 3D 可视化：G0/G1 分色线段、起止标记；已修正 bufferAttribute 类型 |
| `src/components/ErrorBoundary.tsx` | React 错误边界，捕获 3D 渲染崩溃 |
| `src/App.css` | 自定义滚动条样式 |
| `.env` | `VITE_API_BASE_URL=http://localhost:8000` |

### 2.2 业务计算与总线层 (Backend)
* **主框架**: Python `FastAPI`，负责高并发上传、校验下发与通信。CORS 中间件允许跨域（生产环境需限制 `allow_origins`）。
* **静态文件服务**: `/static` 路由映射 `uploads` 目录，供前端获取 OBJ 和 G-Code 文件。
* **数据库持久层**: `SQLite` + `SQLAlchemy` ORM，包含：
  * `jobs`：异步解析控制池与状态追踪 (`uploaded` → `parsed` / `parsed_mock` → `generating` → `done` / `failed`)。
  * `cam_records` (工艺大师历史表)：记录模型体积、加工深度、包围盒尺寸，以及对应的开粗参数，供专家引擎检索。
  * `tool_cards`：刀具数据。
* **虚拟环境**: `Ai_cnc`，依赖版本锁定于 `requirements.txt`。

#### 2.2.1 后端路由 API
| 路由 | 方法 | 职责 |
| :--- | :--- | :--- |
| `/api/v1/upload/` | POST | **[v1 同步主链]** 上传 STEP → CadQuery 进程内解析 → STL/OBJ + topology.json 落盘 → 返回渲染 URL + 拓扑与状态字段 |
| `/api/v1/craftsman/recommend/` | GET | 输入 volume + max_depth → 欧氏距离最近邻 → 返回推荐工艺参数 |
| `/api/v1/cam/tools/` | GET | 返回内置刀具库（D2–D8 平底铣刀，6 把） |
| `/api/v1/cam/generate/` | POST | **[v1 同步主链]** 读取已识别特征 → 自动选刀 → 用选出的粗加工刀径生成 stock-aware 刀路 → cam_result.json 落盘 → 返回 G-Code URL + 刀路分段 + 刀具方案 |
| `/api/v1/jobs/recent` | GET | **[内部查询]** 返回最近 12 个作业摘要（文件名、状态、阶段、时间戳） |
| `/api/v1/jobs/{job_id}` | GET | **[内部查询]** 返回单个作业完整信息（拓扑、CAM 结果、渲染 URL、错误信息、时间戳） |
| `/api/v2/jobs/` | POST | **[v2 同步]** 提交解析任务，返回 job_id 和解析结果 |
| `/api/v2/jobs/{job_id}` | GET | **[v2 同步]** 查询任务状态和产物 |
| `/api/v2/jobs/{job_id}/cam` | POST | **[v2 同步]** 提交 CAM 生成任务 |
| `/api/v2/jobs/{job_id}/artifacts` | GET | **[v2 同步]** 查询渲染/刀路产物与统计信息 |

#### 2.2.2 后端关键文件
| 文件路径 | 职责 |
| :--- | :--- |
| `main.py` | FastAPI 应用入口，CORS、静态文件、路由注册、运行时迁移 |
| `database.py` | SQLAlchemy 引擎、Session 管理、轻量自愈迁移 (`ensure_jobs_columns`) |
| `models.py` | ORM 模型定义 (Job 含 stage/progress/error_code, CAMRecord, ToolCard) |
| `routers/upload.py` | **v1 同步**: 文件校验、CadQuery 解析、Mock 降级、状态落盘、JSON 写入 |
| `routers/cam.py` | **v1 同步**: 读取特征 → 自动选刀 → CAM 生成 + G-Code + 刀具方案落盘 |
| `routers/craftsman.py` | 专家推荐：Min-Max 归一化 + 加权欧氏距离 |
| `routers/internal_jobs.py` | **内部查询**: recent 列表与 detail 接口，支持恢复历史作业 |
| `routers/jobs.py` | **v2 同步**: 任务提交与状态查询（已简化为同步处理） |
| `services/geometry_engine.py` | CadQuery STEP 解析、制造特征识别（孔/型腔/凸台）、STL/GLB 导出 |
| `services/cam_engine.py` | Stock-aware CAM 引擎：毛坯计算 + 截面差集 + 扫描线生成 + 内置刀具库 + 自动选刀 + **刀路坐标逆变换回模型空间** |
| `tasks.py` | 同步任务函数：parse_step_task / generate_cam_task |

### 2.3 底层几何与 CAM 引擎池

#### 2.3.1 几何解析与特征识别 (CadQuery/OpenCASCADE)
* 后端进程内直接完成 STEP/B-Rep 读取，无 FreeCAD 外部 subprocess 依赖
* 主要能力：
  * B-Rep STEP 装配体导入解析
  * 面 (Face) 级法向量提取（通过 `ParameterRange` UV 中点获取，兼容平面/圆柱/锥面等所有面类型）
  * 面质心与边界点收集
  * 包围盒 (BoundBox) 和体积 (Volume) 特征提取
  * **制造特征识别** (`_recognize_features`):
    * **孔 (hole)**: 圆柱面 + 中心低于零件顶面 → 提取直径、深度、轴向
    * **凸台 (boss)**: 圆柱面中心位于零件顶面附近，或小于零件顶面面积的平面
    * **型腔 (pocket)**: 法向朝上的平面 + 低于零件顶面 → 提取深度、XY 范围、面积
  * 三角化网格导出 STL (精度 0.1mm)
  * 尝试 GLB/GLTF 导出（失败自动回退 STL）
* Mock 降级: CadQuery 不可用时，生成基于 bbox 的方盒 OBJ + 6 面拓扑

#### 2.3.2 CAM 规划 (Stock-aware Roughing + OpenCAMLib Optional)
* **Stock-aware 粗加工** (默认策略):
  1. **毛坯计算**: 模型包围盒各方向外扩 3mm (`_compute_stock`)
  2. **逐层切片**: 从毛坯顶面向下，按 `step_down` 分层
  3. **截面差集**: 每层用 trimesh 截取零件截面 → shapely 2D 差集 (stock - part) 得出去除区域
  4. **扫描线填充**: 在去除区域内生成 zigzag 扫描路径
  5. **坐标还原**: 利用 `to_planar()` 返回的 `to_3D` 仿射矩阵还原截面坐标到网格空间
* **坐标变换管线** (装夹面 → 模型空间):
  1. `_load_prepared_mesh`: 加载网格 → 按装夹面法向旋转 (setup_normal → (0,0,-1)) → 平移到原点 → 记录正向变换矩阵 `forward = T @ R`，计算逆矩阵 `inverse = forward⁻¹`
  2. 刀路生成：在 prepared 坐标系下生成 (XY 为 prepared 坐标，Z 为 G-code 机床坐标 Z=0 在零件顶面)
  3. `_segments_machine_z_to_prepared`: 将 Z 从机床坐标系转换到 prepared 坐标系 (`z += part_top_z`)
  4. `_transform_segments_to_model_space`: 应用逆矩阵将 prepared 坐标还原到原始模型坐标系
  5. 前端接收到模型空间坐标，直接与模型同组渲染，无需额外变换
* **Z 轴约定**: 选定装夹面后，加工 Z 轴 = 装夹面法向的反方向 (面朝下放置，刀具从上方加工)
* **内置刀具库** (6 把): D2/D3/D4/D5/D6/D8 平底铣刀
* **自动选刀**: 根据识别到的制造特征自动选配刀具
  * 粗加工: 不超过零件最窄边 50% 的最大刀
  * 孔: 不超过孔径 80% 的最大刀
  * 型腔: 不超过最窄边 60% 的最大刀
  * 凸台: 沿用粗加工刀
* **OpenCAMLib**: 仍为运行时可选增强，当前默认走 stock-aware 粗加工
* 接口契约始终一致：返回刀路分段 (G0/G1, 模型空间坐标) + G-Code (机床坐标) + 刀具方案

---

## 3. 系统核心流程 (Data Flow)

### 3.1 上行解析流 (Upload & Preprocess / v1 同步主链)
1. 前端上传 `.step/.stp` 文件 (≤100 MB)
2. 后端 FastAPI：UUID 封装、文件写入、Job 记录 (`uploaded` 状态)
3. CadQuery 进程内解析：STEP/B-Rep 导入、拓扑特征提取
4. 落盘产物：STL 网格 + `topology.json` (包含特征、面、法向)
5. 返回给前端：渲染 URL、拓扑数据、**完整状态字段** (filename/status/stage/progress/error_code/error_message)

**Mock 降级**: 当 CadQuery/OCC 运行时不可用时：
- 自动生成基于 bbox 的方盒 OBJ 文件
- 生成 6 面拓扑数据 + 降级标记
- 写入 `topology.json` + 错误编码 (E2001)
- Job 状态标记为 `parsed_mock`
- 前端可继续展示模型预览和参数设置，但提示"降级解析"

**数据持久化**: 所有拓扑数据、CAM 结果、渲染文件都落盘，支持页面刷新后恢复历史作业

### 3.2 多维特征寻优流 (Craftsman Heuristics / 推荐引擎)
模型拓扑入库后，`craftsman.py` 接收工件体积 (volume) 和最大深度 (max_depth)。采用 **Min-Max 归一化** 消除量纲差异，配合可配置权重 (volume: 0.6, depth: 0.4) 计算加权欧氏距离，返回最近邻历史案例的工艺参数。无历史数据时返回安全默认值并标记 `is_guessed`。

### 3.3 下行生成流 (Toolpath & G-Code Generation / v1 同步主链)
1. 前端传入用户工艺参数 + 模型真实 bbox 尺寸 + 可选装夹面
2. 后端 `cam.py` 读取 `topology.json` 中的制造特征
3. **自动选刀**: `select_tools_for_features()` 根据特征类型和尺寸从内置刀具库选配粗加工刀和特征精加工刀
4. 寻找可用网格 (STL/OBJ)，用选出的粗加工刀径调用 `cam_engine.generate_cam_with_ocl()`：
   - 加载网格 → 按装夹面法向旋转 (→ Z 朝下) → 平移到原点 → 记录正向/逆变换矩阵
   - 计算毛坯（模型各向外扩 3mm）
   - 从毛坯顶面逐层向下切片
   - 每层：trimesh 截面 → `to_planar()` + 仿射还原 → shapely 差集 → 扫描线填充
   - 刀路 Z 坐标从 G-code 机床系 (Z=0 在零件顶面) 转换到 prepared 绝对坐标系
   - 应用逆变换矩阵将刀路坐标还原到原始模型坐标系
   - OpenCAMLib 可用时优先使用，否则自动降级
5. 产出：
   - **刀路分段** (G0 快速移动/G1 切削, **模型坐标系**) 供前端 3D 可视化直接叠加
   - **G-Code 文件** (.nc, **机床坐标系**) 落盘 + 返回 URL
   - **刀具选配方案** (roughing_tool + feature_tools) 含选刀理由
   - **加工时间估算** (基于切削总长 / 进给率)
   - **统计信息** (层数、切削总长、毛坯尺寸) 写入 `cam_result.json`
6. Job 状态：`uploaded` → `generating` → `done` (或 → `failed`)
7. 前端恢复功能：后续页面刷新或点击"最近作业"可重新打开本次结果

**错误处理**:
- OpenCAMLib 运行时错误 → 自动降级为 stock-aware 粗加工（无需前端感知）
- 网格缺失 → 返回 E3001 错误
- 其他异常 → 记录 error_code/error_message，前端展示并支持调试

---

## 4. 项目结构
```
CNC/
├── backend/
│   ├── main.py                    # FastAPI 入口 + 路由注册
│   ├── database.py                # SQLAlchemy + 轻量迁移
│   ├── models.py                  # ORM 模型 (Job/CAMRecord/ToolCard)
│   ├── requirements.txt           # Python 依赖 (版本锁定)
│   ├── routers/
│   │   ├── upload.py              # v1 同步上传 + CadQuery 解析
│   │   ├── cam.py                 # v1 同步 CAM 生成
│   │   ├── craftsman.py           # 专家推荐引擎
│   │   ├── internal_jobs.py       # 内部作业查询 (recent/detail)
│   │   └── jobs.py                # v2 异步任务 (可选)
│   ├── services/
│   │   ├── __init__.py            # 
│   │   ├── geometry_engine.py     # CadQuery STEP 解析 + STL/GLB 导出
│   │   └── cam_engine.py          # OpenCAMLib 适配 + 降级策略
│   ├── tasks.py                   # 同步任务函数
│   ├── utils/
│   │   └── __init__.py            # 
│   └── uploads/                   # 上传文件 + 产物目录 (job_id/)
├── frontend/
│   ├── .env                       # API base URL 配置
│   ├── package.json               # Node 依赖
│   ├── vite.config.ts             # Vite + TailwindCSS v4 插件
│   ├── tailwind.config.js         # Tailwind 内容扫描配置
│   └── src/
│       ├── App.tsx                # 主应用组件
│       ├── App.css                # 自定义样式
│       ├── index.css              # 全局样式 + Tailwind v4 导入
│       └── components/
│           ├── ModelViewer.tsx     # 3D 模型 + 面拾取 + 测量
│           ├── ToolpathViewer.tsx  # 刀路 3D 可视化
│           └── ErrorBoundary.tsx  # 错误边界
└── spec.md                        # 本文档
```

---

## 5. 启动方式

### 5.1 前置条件
* **Conda 环境**: `data`（Python 3.12，已包含 CadQuery/trimesh/shapely 等依赖）
* **Node.js**: ≥18（前端构建）
* 无需 Redis/Celery/Docker/PostgreSQL 等外部服务

### 5.2 后端
```bash
# 1. 激活 conda 环境
conda activate data

# 2. 安装依赖（首次或依赖变更后）
cd backend
pip install -r requirements.txt

# 3. 启动开发服务器（自动重载）
python -m uvicorn main:app --reload --host 0.0.0.0 --port 8000

# 后端地址: http://localhost:8000
# 健康检查: http://localhost:8000/  → {"status":"ok","message":"Cloud CAM API is running"}
```

**环境变量** (可选):
```bash
DATABASE_URL=sqlite:///./cloudcam.db   # 默认 SQLite，无需配置
```

### 5.3 前端
```bash
cd frontend

# 1. 安装依赖（首次或依赖变更后）
npm install

# 2. 启动开发服务器
npm run dev

# 前端地址: http://localhost:5173/
# API 代理配置: frontend/.env → VITE_API_BASE_URL=http://localhost:8000
```

### 5.4 一键启动（两个终端）
```bash
# 终端 1 — 后端
conda activate data && cd backend && python -m uvicorn main:app --reload --host 0.0.0.0 --port 8000

# 终端 2 — 前端
cd frontend && npm run dev
```

### 5.5 架构说明
当前采用简化的同步处理架构：
- 所有 STEP 解析和 G-Code 生成均为同步处理
- 数据库使用 SQLite，零配置
- 无需 Redis/Celery/Docker 等外部依赖
- 适合开发测试和单用户/低并发场景

如需高并发支持，可参考 `rfc-saas-industrialization.md` 中的 SaaS 工业化方案。

---

## 6. 关键踩坑点及解决方案备案

| 核心问题 | 问题溯源 | 最终解决方案 |
| :--- | :--- | :--- |
| **FreeCAD → CadQuery 重构** | FreeCAD DLL/Python 版本冲突、subprocess 并发不稳定、无头处理复杂度高。 | 改为 CadQuery 进程内 STEP 解析，直接调用 OpenCASCADE Python 绑定，避免 IPC 开销并加载 Mock 降级支持。 |
| **WebGL 白屏崩溃报错** | `<Stage>` 组件使用不受支持的 `preset` 值导致空指针。 | 降级为 `preset="soft"` 和 `environment="city"`，并加 `ErrorBoundary` 容错。 |
| **TailwindCSS v4 迁移** | 项目升级到 v4 但 CSS 仍用 v3 指令 (`@tailwind base`)，缺少 Vite 插件。 | 安装 `@tailwindcss/vite`，CSS 改为 `@import "tailwindcss"`，`vite.config.ts` 注册插件。 |
| **CadQuery 非平面面法向提取** | 原 FreeCAD 脚本调用 `face.Surface.getParameterByLength()` 对圆柱/锥面类型抛 `AttributeError`。 | 改用 `face.ParameterRange` 获取 UV 参数域中点，再调用 `face.normalAt(umid, vmid)`，兼容所有面类型（平面/圆柱/锥面/NURBS 等）。 |
| **Mock 模式无 3D 预览** | CadQuery 不可用时 Mock 返回 `render_file: null`，前端看不到模型。 | Mock 自动生成基于 bbox 的方盒 OBJ 文件 (`_generate_mock_box_obj`) + 拓扑 JSON，返回有效 render_url，前端可继续调试。 |
| **G-Code 与模型不匹配** | 早期 cam.py 硬编码 50×50 尺寸，不随模型 bbox 变化。 | 前端传入真实 `bbox_x/bbox_y/z_depth`，后端据此生成自适应分层 zigzag/drop-cutter 刀路。 |
| **页面刷新丢失作业** | 早期无持久化作业查询，页面刷新后当前工作状态丢失。 | 新增 `internal_jobs.py` (recent/detail 接口)，同步主链路落盘 topology.json + cam_result.json，前端支持恢复历史作业。 |
| **Three Fiber bufferAttribute 类型** | `ToolpathViewer.tsx` 用旧语法 `array/count/itemSize` 属性，与最新 react-three-fiber 不兼容。 | 改为 `args={[array, itemSize]}` 标准化语法。 |
| **未使用参数编译警告** | TypeScript 严格模式启用 `noUnusedParameters`，但个别组件传入未用到的参数。 | 清理 `ModelViewer.tsx` 中 `InteractiveModel` 的未使用参数 (`selectedFace`/`measurePoints`)。 |
| **OpenCAMLib 平台兼容性** | Windows/Python 版本差异导致 OCL 安装失败。 | 将 OpenCAMLib 从硬依赖改为运行时可选增强，装不上时自动降级到平面粗加工，接口契约不变。 |
| **刀路不覆盖模型 (全面加工缺失)** | 旧版 CAM 引擎对整个 bbox 做 zigzag 扫描，不区分毛坯和零件实体，导致加工掉零件本身。 | 重构为 stock-aware 架构：毛坯外扩 3mm → trimesh 截面 → shapely 差集 (stock - part) → 仅在去除区域生成扫描线。 |
| **毛坯无 Z 方向余量** | `_compute_stock` 只在 XY 加余量，Z 方向毛坯顶面 = 零件顶面，导致每层截面差集只剩周边窄环。 | 毛坯 Z 顶面增加 3mm 余量。首层切面在零件上方 → 截面为空 → 差集 = 整个毛坯 → 全面积覆盖加工。 |
| **截面 Z 超界钳位错误** | `_extract_section_geometry` 把超出零件的 Z 钳位回顶面，导致即使有 Z 余量仍返回实体截面。 | 超出零件边界直接返回空截面，表示该层全为需去除材料。 |
| **`to_planar()` 坐标偏移** | trimesh `to_planar()` 以截面质心为原点平移 2D 坐标，导致截面多边形与毛坯坐标系不匹配，刀路飘离模型。 | 利用 `to_planar()` 返回的 `to_3D` 仿射矩阵，通过 `shapely.affinity.affine_transform` 还原截面坐标到网格空间。 |
| **缺少制造特征识别** | 几何引擎只提取面法向和 bbox，无法识别孔、型腔、凸台等加工特征。 | 新增 `_recognize_features()`：遍历 CadQuery 面，按几何类型 (CYLINDER/PLANE)、法向、Z 位置、面积等启发式规则分类。 |
| **单一刀具硬编码** | CAM 路由硬编码 `TOOL_DIAMETER = 6.0`，不区分特征类型。 | 内置 D2–D8 刀具库 + `select_tools_for_features()` 自动选刀，粗加工用最大可用刀，特征按尺寸约束选配。 |
| **装夹面高亮不贴合模型** | 旧版 FaceHighlight 用固定大小的浮动圆盘，无法适配实际 B-Rep 面形状。 | BFS 洪泛算法 (`collectCoplanarFaceIndices`) 从点击三角形出发搜索所有共面三角形 (法向偏差 <5°, 上限 50000)，`buildHighlightGeometry` 构建贴合网格曲面的高亮几何体，使用 `polygonOffset` 防 Z-fighting。 |
| **刀路与模型坐标系不对齐** | 后端生成刀路时先旋转+平移网格到 prepared 坐标系，但刀路坐标未还原回原始模型空间，导致前端渲染时刀路偏移模型。 | `_load_prepared_mesh` 记录正向变换矩阵并计算逆矩阵；`_transform_segments_to_model_space` 将刀路坐标逆变换回原始模型空间，前端直接与模型同组渲染。 |
| **刀路 Z 坐标混用导致偏移** | 刀路 XY 使用 prepared 绝对坐标，但 Z 使用 G-code 机床坐标 (Z=0 在零件顶面)，逆变换时混合坐标系导致 Z 方向严重偏移。 | 新增 `_segments_machine_z_to_prepared`：在逆变换前将 Z 从机床坐标转为 prepared 绝对坐标 (`z += part_top_z`)，确保 XYZ 三轴统一在 prepared 坐标系下再做逆变换。 |
| **装夹面箭头方向错误** | 面高亮箭头指向面法向方向，但 CNC 约定加工 Z 轴 = 装夹面法向的反方向。 | 箭头方向改为 `normal.negate()`，指示加工 Z 轴方向（刀具进入方向）。 |

---

## 7. 技术栈版本汇总

| 组件 | 版本 | 说明 |
| :--- | :--- | :--- |
| **Frontend** | | |
| React | 19.2 | 核心框架 |
| React DOM | 19.2 | |
| Vite | 8.0 | 构建工具 |
| TypeScript | 6.0 | 编程语言 + 严格类型检查 |
| TailwindCSS | 4.2 | via `@tailwindcss/vite` 插件 |
| Three.js | 0.183 | 3D 渲染引擎 |
| @react-three/fiber | 9.5 | React 声明式 3D |
| @react-three/drei | 10.7 | Three.js 特效库 |
| lucide-react | 1.8 | 图标系统 |
| axios | 1.15 | HTTP 客户端 |
| **Backend** | | |
| Python | 3.12 | 编程语言（data 环境）|
| FastAPI | ≥0.110 | Web 框架 |
| Uvicorn | 0.44 | ASGI 服务器 |
| SQLAlchemy | ≥2.0 | ORM |
| SQLite | Latest | 默认数据库（可切 PostgreSQL） |
| CadQuery | Latest | OpenCASCADE Python 绑定，STEP 解析 + 特征识别 |
| trimesh | Latest | 网格加载、截面切片 |
| shapely | ≥2.1 | 2D 几何运算（差集、扫描线交集） |
| networkx | ≥3.6 | trimesh 间接依赖（空间图计算） |
| rtree | ≥1.4 | trimesh 间接依赖（空间索引） |
| OpenCAMLib | Optional | CAM 规划（运行时可选，失败自动降级） |

> 注：当前采用简化架构，Conda 环境 `data`，无需 Redis/Celery/Docker。如需生产级高并发部署，可参考 `rfc-saas-industrialization.md`。
