# Cloud CAM — 云端智能 CNC 加工平台

基于 Web 的计算机辅助制造 (CAM) 平台，支持浏览器内 3D 模型预览、交互测量、装夹面选择、工艺参数智能推荐和 G-Code 生成与刀路可视化。

![Tech Stack](https://img.shields.io/badge/React-19-blue?logo=react) ![Tech Stack](https://img.shields.io/badge/FastAPI-Python-green?logo=fastapi) ![Tech Stack](https://img.shields.io/badge/Three.js-0.183-black?logo=threedotjs) ![Tech Stack](https://img.shields.io/badge/TailwindCSS-v4-06B6D4?logo=tailwindcss)

---

## 功能概览

| 功能 | 说明 |
| :--- | :--- |
| **STEP 文件上传** | 支持 `.step/.stp` 格式，≤100 MB，自动解析拓扑 |
| **3D 模型预览** | OBJ/STL 网格渲染，工业光影环境，坐标轴辅助 |
| **交互测量** | 在模型表面点击两点，实时显示距离 (mm) |
| **装夹面选择** | 点击模型表面指定 CNC 装夹底面，法向可视化 |
| **专家参数推荐** | 基于加工历史的最近邻匹配，自动推荐工艺参数 |
| **G-Code 生成** | OpenCAMLib Drop-cutter 刀位计算（不可用时自动降级） |
| **刀路可视化** | G0 (快移/红色) 和 G1 (切削/青色) 分色 3D 叠加显示 |
| **G-Code 下载** | 生成 GRBL 兼容 `.nc` 文件，可直接送入 CNC 机床 |

---

## 快速开始

### 前置条件

- **Node.js** ≥ 18
- **Python** ≥ 3.10
- **CadQuery 2.5+**
- **OpenCAMLib Python 绑定** (建议安装；缺失时自动降级为平面粗加工)

### 1. 克隆项目

```bash
git clone <repo-url>
cd CNC
```

### 2. 启动后端

```bash
# 创建并激活虚拟环境
python -m venv .venv
# Windows:
.venv\Scripts\activate
# 或使用 conda:
# conda activate Ai_cnc

cd backend
pip install -r requirements.txt
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

后端运行于 `http://localhost:8000`（使用 SQLite 本地数据库，无需额外配置）

### 3. 启动前端

```bash
cd frontend
npm install
npm run dev
```

前端运行于 `http://localhost:5173`

---

## 使用流程

```
上传 STEP 文件  →  查看 3D 模型  →  测量 / 选装夹面  →  调整工艺参数  →  生成 G-Code  →  查看刀路 / 下载
```

1. **上传** — 点击左侧上传区域，选择 `.step` 或 `.stp` 文件
2. **预览** — 右侧 3D 区域自动加载模型，可旋转 / 平移 / 缩放
3. **测量** — 点击工具栏「测量」按钮，在模型上点击两点查看距离
4. **选面** — 点击工具栏「选择装夹面」，点击模型底面指定装夹位置
5. **参数** — 左侧面板显示专家推荐参数，可手动编辑覆写
6. **生成** — 点击「生成 G-Code」按钮，等待生成完成
7. **查看** — 刀路自动叠加在 3D 模型上，红色=快移，青色=切削
8. **下载** — 点击「下载 .nc 文件」获取 G-Code

---

## 项目结构

```
CNC/
├── backend/
│   ├── main.py                    # FastAPI 入口
│   ├── database.py                # SQLAlchemy 设置
│   ├── models.py                  # ORM 模型 (Job, CAMRecord, ToolCard)
│   ├── requirements.txt           # Python 依赖
│   ├── services/
│   │   ├── geometry_engine.py     # CadQuery STEP解析 + STL导出
│   │   └── cam_engine.py          # OpenCAMLib 刀路生成适配层
│   ├── routers/
│   │   ├── upload.py              # 上传 + CadQuery 解析
│   │   ├── cam.py                 # G-Code + OCL/降级刀路生成
│   │   └── craftsman.py           # 专家推荐引擎
│   └── uploads/                   # 运行时文件存储
├── frontend/
│   ├── .env                       # API 地址配置
│   ├── vite.config.ts             # Vite + TailwindCSS v4
│   └── src/
│       ├── App.tsx                # 主应用
│       └── components/
│           ├── ModelViewer.tsx     # 3D 交互 (旋转/测量/选面/刀路)
│           ├── ToolpathViewer.tsx  # 刀路可视化
│           └── ErrorBoundary.tsx  # 错误边界
├── spec.md                        # 详细技术规范
└── README.md                      # 本文件
```

---

## API 接口

| 端点 | 方法 | 说明 |
| :--- | :--- | :--- |
| `/api/v1/upload/` | POST | 上传 STEP 文件，返回 3D 模型 URL + 拓扑数据 |
| `/api/v1/craftsman/recommend/` | GET | 输入体积+深度，返回推荐工艺参数 |
| `/api/v1/cam/generate/` | POST | 输入参数+模型尺寸，返回 G-Code + 刀路分段 |
| `/api/v2/jobs/` | POST | 异步提交 STEP 解析任务，立即返回 `job_id` |
| `/api/v2/jobs/{job_id}` | GET | 查询异步任务状态与产物 URL |
| `/api/v2/jobs/{job_id}/cam` | POST | 异步提交 CAM 生成任务 |
| `/api/v2/jobs/{job_id}/artifacts` | GET | 查询渲染/刀路产物与统计信息 |
| `/static/{job_id}/{file}` | GET | 获取 GLB/STL/OBJ 模型 / G-Code 文件 |

---

## 技术栈

| 层级 | 技术 |
| :--- | :--- |
| **前端框架** | React 19 + TypeScript + Vite |
| **样式** | TailwindCSS v4 |
| **3D 渲染** | Three.js + @react-three/fiber + drei |
| **图标** | lucide-react |
| **后端框架** | FastAPI + SQLAlchemy + SQLite |
| **几何引擎** | CadQuery (OpenCASCADE) |
| **CAM 引擎** | OpenCAMLib (Drop-cutter) |
| **G-Code** | GRBL 兼容格式 |

> 注：项目采用简化架构，所有请求同步处理，无需 Redis/Celery/PostgreSQL。适合开发测试和单用户场景。

---

## 配置

### 环境变量

| 变量 | 位置 | 默认值 | 说明 |
| :--- | :--- | :--- | :--- |
| `VITE_API_BASE_URL` | `frontend/.env` | `http://localhost:8000` | 后端 API 地址 |
| `DATABASE_URL` | 系统环境变量 | `sqlite:///./cloudcam.db` | 数据库连接（默认 SQLite） |

OpenCAMLib 绑定不可用时，`/api/v1/cam/generate/` 会自动降级为平面粗加工策略，并在返回 `stats.strategy` 中标记降级原因。

---

## 许可证

MIT
