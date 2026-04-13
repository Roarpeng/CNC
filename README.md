# Cloud CAM — 云端智能 CNC 加工平台

基于 Web 的计算机辅助制造 (CAM) 平台，支持浏览器内 3D 模型预览、交互测量、装夹面选择、工艺参数智能推荐和 G-Code 生成与刀路可视化。

![Tech Stack](https://img.shields.io/badge/React-19-blue?logo=react) ![Tech Stack](https://img.shields.io/badge/FastAPI-Python-green?logo=fastapi) ![Tech Stack](https://img.shields.io/badge/Three.js-0.183-black?logo=threedotjs) ![Tech Stack](https://img.shields.io/badge/TailwindCSS-v4-06B6D4?logo=tailwindcss)

---

## 功能概览

| 功能 | 说明 |
| :--- | :--- |
| **STEP 文件上传** | 支持 `.step/.stp` 格式，≤100 MB，自动解析拓扑 |
| **3D 模型预览** | OBJ 网格渲染，工业光影环境，坐标轴辅助 |
| **交互测量** | 在模型表面点击两点，实时显示距离 (mm) |
| **装夹面选择** | 点击模型表面指定 CNC 装夹底面，法向可视化 |
| **专家参数推荐** | 基于加工历史的最近邻匹配，自动推荐工艺参数 |
| **G-Code 生成** | 基于模型实际尺寸的多层 zigzag 粗加工刀路 |
| **刀路可视化** | G0 (快移/红色) 和 G1 (切削/青色) 分色 3D 叠加显示 |
| **G-Code 下载** | 生成 GRBL 兼容 `.nc` 文件，可直接送入 CNC 机床 |

---

## 快速开始

### 前置条件

- **Node.js** ≥ 18
- **Python** ≥ 3.10
- **FreeCAD 1.1** (可选，用于真实 STEP 解析；缺失时自动 Mock 降级)

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

后端运行于 `http://localhost:8000`

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
│   ├── routers/
│   │   ├── upload.py              # 上传 + FreeCAD 解析
│   │   ├── cam.py                 # G-Code + 刀路生成
│   │   └── craftsman.py           # 专家推荐引擎
│   ├── utils/
│   │   └── freecad_env.py         # FreeCAD 环境扫描
│   ├── scripts/
│   │   └── freecad_processor.py   # FreeCAD 无头处理脚本
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
| `/static/{job_id}/{file}` | GET | 获取 OBJ 模型 / G-Code 文件 |

---

## 技术栈

| 层级 | 技术 |
| :--- | :--- |
| **前端框架** | React 19 + TypeScript 6 + Vite 8 |
| **样式** | TailwindCSS v4 |
| **3D 渲染** | Three.js 0.183 + @react-three/fiber + drei |
| **图标** | lucide-react |
| **后端框架** | FastAPI + SQLAlchemy + SQLite |
| **几何引擎** | FreeCAD 1.1 (无头沙箱子进程) |
| **G-Code** | GRBL 兼容格式 |

---

## 配置

### 环境变量

| 变量 | 位置 | 默认值 | 说明 |
| :--- | :--- | :--- | :--- |
| `VITE_API_BASE_URL` | `frontend/.env` | `http://localhost:8000` | 后端 API 地址 |
| `FREECAD_PATH` | 系统环境变量 | 自动扫描 | FreeCAD bin 目录路径 |

### FreeCAD 自动检测

后端自动在以下路径搜索 FreeCAD：
- `C:\Program Files\FreeCAD*\*bin`
- `%LOCALAPPDATA%\Programs\FreeCAD*\*bin`
- `/usr/lib/freecad/lib` (Linux)

未找到时自动降级为 Mock 模式，生成占位方盒模型。

---

## 许可证

MIT
