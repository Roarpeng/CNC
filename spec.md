# Cloud CAM 工业级云端加工管理平台系统规范 (Spec)

> **最后更新**: 2026-04-14

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
  * **选择装夹面** (Face Select): 点击模型表面选择 CNC 装夹底面，显示半透明橙色圆盘和黄色法向箭头。
* **刀路可视化叠加**: 生成 G-Code 后，3D 场景自动叠加显示刀路：
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
* **工艺参数面板**: 显示专家推荐参数（背吃刀量、主轴转速、进给率），**用户可编辑覆写**。标注"专家推荐"或"默认值"来源。
* **G-Code 结果卡片**: 显示预计加工时间、加工层数、切削总长度，提供 `.nc` 文件下载。
* **生成按钮**: 底部固定，带加载状态和禁用逻辑。

#### 2.1.3 前端关键文件
| 文件路径 | 职责 |
| :--- | :--- |
| `src/App.tsx` | 主应用：状态管理、上传/生成流程、侧边栏 UI、工具栏、**作业列表与恢复** (新增) |
| `src/components/ModelViewer.tsx` | 3D 模型渲染：OBJ/STL/GLB 加载、面拾取、测量、刀路叠加；已修复未使用参数 |
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
| `/api/v1/cam/generate/` | POST | **[v1 同步主链]** 输入工艺参数 + 模型 bbox → OpenCAMLib Drop-cutter (自动降级) → cam_result.json 落盘 → 返回 G-Code URL + 刀路分段 |
| `/api/v1/jobs/recent` | GET | **[内部查询]** 返回最近 12 个作业摘要（文件名、状态、阶段、时间戳） |
| `/api/v1/jobs/{job_id}` | GET | **[内部查询]** 返回单个作业完整信息（拓扑、CAM 结果、渲染 URL、错误信息、时间戳） |
| `/api/v2/jobs/` | POST | **[异步可选]** 提交异步解析任务，返回 job_id |
| `/api/v2/jobs/{job_id}` | GET | **[异步可选]** 查询异步任务状态 |
| `/api/v2/jobs/{job_id}/cam` | POST | **[异步可选]** 异步提交 CAM 生成任务 |
| `/api/v2/jobs/{job_id}/artifacts` | GET | **[异步可选]** 查询异步任务产物（拓扑、CAM 结果、渲染文件） |

#### 2.2.2 后端关键文件
| 文件路径 | 职责 |
| :--- | :--- |
| `main.py` | FastAPI 应用入口，CORS、静态文件、路由注册、运行时迁移 |
| `database.py` | SQLAlchemy 引擎、Session 管理、轻量自愈迁移 (`ensure_jobs_columns`) |
| `models.py` | ORM 模型定义 (Job 含 stage/progress/error_code, CAMRecord, ToolCard) |
| `routers/upload.py` | **v1 同步**: 文件校验、CadQuery 解析、Mock 降级、状态落盘、JSON 写入 |
| `routers/cam.py` | **v1 同步**: OpenCAMLib 刀路 + 降级策略 + G-Code + 状态落盘 |
| `routers/craftsman.py` | 专家推荐：Min-Max 归一化 + 加权欧氏距离 |
| `routers/internal_jobs.py` | **内部查询**: recent 列表与 detail 接口，支持恢复历史作业 |
| `routers/jobs.py` | **v2 异步** (可选): Celery 任务提交与状态查询 |
| `services/geometry_engine.py` | CadQuery STEP 进程内解析、特征提取、STL/GLB 导出 |
| `services/cam_engine.py` | OpenCAMLib 适配层（Drop-cutter + 平面粗加工降级） |
| `celery_app.py` | **异步可选**: Celery 配置 (Redis broker) |
| `tasks.py` | **异步可选**: parse_step_task / generate_cam_task 异步任务定义 |

### 2.3 底层几何与 CAM 引擎池

#### 2.3.1 几何解析 (CadQuery/OpenCASCADE)
* 后端进程内直接完成 STEP/B-Rep 读取，无 FreeCAD 外部 subprocess 依赖
* 主要能力：
  * B-Rep STEP 装配体导入解析
  * 面 (Face) 级法向量提取（通过 `ParameterRange` UV 中点获取，兼容平面/圆柱/锥面等所有面类型）
  * 面质心与边界点收集
  * 包围盒 (BoundBox) 和体积 (Volume) 特征提取
  * 三角化网格导出 STL (精度 0.1mm)
  * 尝试 GLB/GLTF 导出（失败自动回退 STL）
* Mock 降级: CadQuery 不可用时，生成基于 bbox 的方盒 OBJ + 6 面拓扑

#### 2.3.2 CAM 规划 (OpenCAMLib + Fallback)
* 优先使用 **OpenCAMLib (C++ Python 绑定)** 进行 3D Drop-cutter 刀位计算
* 运行时策略：
  * **第一层**: 尝试 OpenCAMLib Drop-cutter（若环境可用）
  * **第二层**: 自动降级到平面粗加工策略（分层开粗 + zigzag 扫描）
* 接口契约始终一致：返回刀路分段 (G0/G1) 和 G-Code
* OpenCAMLib 设计为**运行时可选增强**，非硬依赖

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
1. 前端传入用户工艺参数 + 模型真实 bbox 尺寸
2. 后端 `cam.py` 寻找可用网格 (STL/OBJ)
3. 调用 `cam_engine.generate_cam_with_ocl()`：
   - **优先**: OpenCAMLib Drop-cutter 3D 刀位计算
   - **降级**: 平面粗加工（分层开粗 + zigzag 扫描）
4. 产出：
   - **刀路分段** (G0 快速移动/G1 切削) 供前端 3D 可视化
   - **G-Code 文件** (.nc) 落盘 + 返回 URL
   - **加工时间估算** (基于切削总长 / 进给率)
   - **统计信息** (点数、分段数) 写入 `cam_result.json`
5. Job 状态：`uploaded` → `generating` → `done` (或 → `failed`)
6. 前端恢复功能：后续页面刷新或点击"最近作业"可重新打开本次结果

**错误处理**:
- OpenCAMLib 运行时错误 → 自动降级为平面粗加工（无需前端感知）
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
│   ├── celery_app.py              # Celery 配置 (可选)
│   ├── tasks.py                   # 异步任务定义 (可选)
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

### 5.1 后端 (v1 同步主流程)
```bash
# 激活虚拟环境
conda activate <your_env>   # 需要安装 requirements.txt
cd backend

# 方式 1: 开发环境 (自动重载)
C:/path/to/python.exe -m uvicorn main:app --reload --host 0.0.0.0 --port 8000

# 方式 2: 无外部依赖 (仅 SQLite)
# 无需 Redis/Celery 配置，v1 同步链路完全自洽
```

**环境变量** (可选):
```bash
# SQLite (默认)
DATABASE_URL=sqlite:///./cloudcam.db

# 或 PostgreSQL (生产)
DATABASE_URL=postgresql://user:pass@localhost/cloudcam
DB_POOL_SIZE=10
DB_MAX_OVERFLOW=20
```

### 5.2 前端
```bash
cd frontend
npm install

# 开发环境
npx vite --host 0.0.0.0 --port 5173

# 访问
# 本地: http://localhost:5173/
# 同网段: http://<network-ip>:5173/
```

### 5.3 异步支持 (可选，当前内部不需要)
```bash
# 启动 Redis
docker run -d -p 6379:6379 redis:latest

# 启动 Celery Worker
celery -A celery_app worker --loglevel=info

# Backend 会自动识别并使用异步链路 (/api/v2/jobs)
```

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
| CadQuery | Latest | OpenCASCADE Python 绑定，STEP 解析 |
| trimesh | Latest | |
| OpenCAMLib | Optional | CAM 规划（运行时可选，失败自动降级） |
| **异步可选** | | 内部当前不需要 |
| Celery | Latest | 任务队列框架 |
| Redis | Latest | Celery Broker |
| psycopg[binary] | Latest | PostgreSQL 驱动 |
| **Docker (可选)** | | |
| Python | 3.12 | Backend 容器基镜像 |
| Node | Latest | Frontend 构建容器 |
