# Cloud CAM 工业级云端加工管理平台系统规范 (Spec)

> **最后更新**: 2026-04-13

## 1. 项目愿景与定位
本项目定位于"**基于 Web 的计算机辅助制造 (Cloud CAM) 平台与专家推荐系统**"。旨在改变传统加工行业必须在重型本地工控机上打开复杂 CAM 软件的现状，允许用户通过浏览器直接预览、测量并生成 CNC 刀路，同时借助系统内置的加工历史实现"工艺大师"的辅助参数推荐。

---

## 2. 总体软硬件架构设计 (MVC 分离)
系统严格遵循前后端分离架构，划分为三个核心运行层：

### 2.1 交互表现层 (Frontend)
* **主框架**: `React 19` + `Vite 8` 构建的超速轻量化前端。
* **语言规范**: `TypeScript 6` + 严格检查 (`verbatimModuleSyntax`)。
* **样式引擎**: `TailwindCSS v4` (通过 `@tailwindcss/vite` 插件集成)，以暗色系 (`Slate-900`) 为主的现代工业质感 UI。
* **3D 驱动渲染**: 围绕 `Three.js 0.183` 生态群（`@react-three/fiber 9` 声明式引擎 与 `@react-three/drei 10` 特效库），完成了 OBJ 网格模型载入和工业化影棚 (`<Stage>`) 渲染展示。
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
* **模型特征卡片**: 显示体积、XY 尺寸、最大 Z 深度。
* **工艺参数面板**: 显示专家推荐参数（背吃刀量、主轴转速、进给率），**用户可编辑覆写**。标注"专家推荐"或"默认值"来源。
* **G-Code 结果卡片**: 显示预计加工时间、加工层数、切削总长度，提供 `.nc` 文件下载。
* **生成按钮**: 底部固定，带加载状态和禁用逻辑。

#### 2.1.3 前端关键文件
| 文件路径 | 职责 |
| :--- | :--- |
| `src/App.tsx` | 主应用：状态管理、上传/生成流程、侧边栏 UI、工具栏 |
| `src/components/ModelViewer.tsx` | 3D 模型渲染：OBJ 加载、面拾取、测量、刀路叠加 |
| `src/components/ToolpathViewer.tsx` | 刀路 3D 可视化：G0/G1 分色线段、起止标记 |
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
| `/api/v1/upload/` | POST | 上传 STEP 文件 → FreeCAD 解析 → 返回 OBJ URL + 拓扑数据 |
| `/api/v1/craftsman/recommend/` | GET | 输入 volume + max_depth → 欧氏距离最近邻 → 返回推荐工艺参数 |
| `/api/v1/cam/generate/` | POST | 输入工艺参数 + 模型 bbox → 多层 zigzag 粗加工 → 返回 G-Code + 刀路分段 |

#### 2.2.2 后端关键文件
| 文件路径 | 职责 |
| :--- | :--- |
| `main.py` | FastAPI 应用入口，CORS、静态文件、路由注册 |
| `database.py` | SQLAlchemy 引擎、Session 管理 |
| `models.py` | ORM 模型定义 (Job, CAMRecord, ToolCard) |
| `routers/upload.py` | 上传路由：文件校验、FreeCAD 子进程、Mock 降级 (含 OBJ 方盒生成) |
| `routers/cam.py` | CAM 路由：基于真实 bbox 的多层 zigzag 刀路生成 + G-Code 输出 |
| `routers/craftsman.py` | 专家推荐：Min-Max 归一化 + 加权欧氏距离 |
| `utils/freecad_env.py` | FreeCAD 环境扫描工具 (带缓存) |
| `scripts/freecad_processor.py` | FreeCAD 无头处理脚本：STEP → 拓扑 + OBJ mesh |

### 2.3 底层 C++ 几何引擎池 (Isolated Processor)
* 基于 **FreeCAD 1.1 的无头沙盒架构**。由 Python 后端衍生 `subprocess` 执行。
* 通过动态扫描定位 `FreeCAD/bin/python.exe` (含 `LOCALAPPDATA`、`Program Files` 搜索) 建立进程隔离，规避 `python311.dll` 跨版本冲突。搜索结果带缓存避免重复扫描。
* 主要处理：
  * B-Rep STEP 装配体导入解析
  * 面 (Face) 级法向量提取（通过 `ParameterRange` UV 中点获取，兼容平面/圆柱/锥面等所有面类型）
  * 面质心 (CenterOfMass) 计算
  * 包围盒 (BoundBox) 和体积 (Volume) 特征提取
  * 三角化网格导出 OBJ (精度 0.1mm)

---

## 3. 系统核心流程 (Data Flow)

### 3.1 上行解析流 (Upload & Preprocess)
用户前端传入 `.step/.stp` 文件 (≤100 MB) → FastAPI 进行 UUID 封装存档 → 写入 Job 记录 → 通过子进程调用底层 `FreeCAD Engine` (超时 120s) → 取出所有表面的法向量、质心，以及 Bounding Box 极限长宽深 → 导出 OBJ 网格 → 返回带 OBJ 缓存地址的 JSON 拓扑数据。

**Mock 降级**: 当 FreeCAD 不可用时，自动生成基于 bbox 的方盒 OBJ + 6 面拓扑数据，保证前端 3D 预览和交互功能可用。

### 3.2 多维特征寻优流 (Craftsman Heuristics / 推荐引擎)
模型拓扑入库后，`craftsman.py` 接收工件体积 (volume) 和最大深度 (max_depth)。采用 **Min-Max 归一化** 消除量纲差异，配合可配置权重 (volume: 0.6, depth: 0.4) 计算加权欧氏距离，返回最近邻历史案例的工艺参数。无历史数据时返回安全默认值并标记 `is_guessed`。

### 3.3 下行生成流 (Toolpath & G-Code Generation)
前端传入用户确认的工艺参数 **+ 模型真实 bbox 尺寸** → `cam.py` 根据实际包围盒生成：
* **多层 zigzag 粗加工刀路**: 层数 = `ceil(z_depth / step_down)`，行距 = 刀具直径 × 步进比例 (默认 6mm × 40% = 2.4mm)
* **分段刀路数据** (含 `G0`/`G1` 类型) 供前端 3D 可视化
* **GRBL 兼容 G-Code** (.nc 文件) 供 CNC 机床直接消费
* **加工时间估算**: 基于切削段总长度 / 进给率

---

## 4. 项目结构
```
CNC/
├── backend/
│   ├── main.py                    # FastAPI 入口
│   ├── database.py                # SQLAlchemy 设置
│   ├── models.py                  # ORM 模型
│   ├── requirements.txt           # Python 依赖 (版本锁定)
│   ├── routers/
│   │   ├── upload.py              # 上传 + FreeCAD 解析
│   │   ├── cam.py                 # G-Code + 刀路生成
│   │   └── craftsman.py           # 专家推荐引擎
│   ├── utils/
│   │   └── freecad_env.py         # FreeCAD 环境扫描
│   ├── scripts/
│   │   └── freecad_processor.py   # FreeCAD 无头处理脚本
│   └── uploads/                   # 上传文件 + 生成产物
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

### 5.1 后端
```bash
# 激活虚拟环境
conda activate Ai_cnc   # 或对应的 venv
cd backend
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### 5.2 前端
```bash
cd frontend
npm install
npm run dev
# 访问 http://localhost:5173
```

---

## 6. 关键踩坑点及解决方案备案

| 核心问题 | 问题溯源 | 最终解决方案 |
| :--- | :--- | :--- |
| **WebGL 白屏崩溃报错** | `<Stage>` 组件使用不受支持的 `preset` 值导致空指针。 | 降级为 `preset="soft"` 和 `environment="city"`，并加 `ErrorBoundary` 容错。 |
| **FreeCAD DLL Load Failed** | FreeCAD 1.1 锁定 Python 3.11 DLL，与服务端 Python 3.12 冲突。 | 废弃直接导入，改用动态扫描 `FreeCAD/bin/python.exe` 作为沙箱 `subprocess`。结果带缓存。 |
| **Console ImportGui 错误** | 后端加载 FreeCAD GUI 包崩溃。 | 剔除 `import ImportGui`，纯无头执行。 |
| **TailwindCSS 样式不生效** | 项目使用 TailwindCSS v4 但 CSS 仍用 v3 指令 (`@tailwind base`)，且缺少 Vite 插件。 | 安装 `@tailwindcss/vite`，CSS 改为 `@import "tailwindcss"`，`vite.config.ts` 注册插件。 |
| **FreeCAD 处理非平面崩溃** | `freecad_processor.py` 调用 `face.Surface.getParameterByLength()` 对圆柱/锥面等非平面类型抛 `AttributeError`。 | 改用 `face.ParameterRange` 获取 UV 参数域中点，再调用 `face.normalAt(umid, vmid)`，兼容所有面类型。 |
| **Mock 模式无 3D 预览** | FreeCAD 不可用时 Mock 返回 `render_file: null`，前端显示"模型预览不可用"。 | Mock 降级时自动生成基于 bbox 的方盒 OBJ 文件 (`_generate_mock_box_obj`)，返回有效 render_url。 |
| **G-Code 与模型不匹配** | cam.py 硬编码 50×50 尺寸的刀路，不随模型变化。 | 前端传入真实 `bbox_x/bbox_y/z_depth`，后端据此生成多层 zigzag 粗加工刀路。 |

---

## 7. 技术栈版本汇总

| 组件 | 版本 |
| :--- | :--- |
| React | 19.2 |
| Vite | 8.0 |
| TypeScript | 6.0 |
| TailwindCSS | 4.2 (via `@tailwindcss/vite`) |
| Three.js | 0.183 |
| @react-three/fiber | 9.5 |
| @react-three/drei | 10.7 |
| lucide-react | 1.8 |
| FastAPI | ≥0.110 |
| SQLAlchemy | ≥2.0 |
| FreeCAD | 1.1 (无头沙箱模式) |
| Python (后端) | 3.12 (Ai_cnc 虚拟环境) |
| Python (FreeCAD) | 3.11 (FreeCAD 内置) |
