# Cloud CAM 工业级云端加工管理平台系统规范 (Spec)

## 1. 项目愿景与定位
本项目定位于“**基于 Web 的计算机辅助制造 (Cloud CAM) 平台与专家推荐系统**”。旨在改变传统加工行业必须在重型本地工控机上打开复杂 CAM 软件的现状，允许用户通过浏览器直接预览、测量并生成 CNC 刀路，同时借助系统内置的加工历史实现“工艺大师”的辅助参数推荐。

## 2. 总体软硬件架构设计 (MVC 分离)
系统严格遵循前后端分离架构，划分为三个核心运行层：

### 2.1 交互表现层 (Frontend)
* **主框架**: `React 18` + `Vite` 构建的超速轻量化前端。
* **语言规范**: `TypeScript` + 严格检查。
* **样式引擎**: `TailwindCSS` 打造以暗色系 (`Slate-900`) 为主的现代工业质感 UI。
* **3D 驱动渲染**: 围绕 `Three.js` 生态群（`@react-three/fiber` 声明式引擎 与 `@react-three/drei` 特效库），完成了 `glTF / OBJ` 的网格模型载入和包含多方位平行光的工业化影棚 (`<Stage>`) 渲染展示。

### 2.2 业务计算与总线层 (Backend)
* **主框架**: Python `FastAPI`，负责承受高并发上传、校验下发与通信机制。
* **数据库持久层**: 暂定 `SQLite` 作为底层结构，依靠 `SQLAlchemy` ORM 构建多维数据实体。包含：
  * `jobs`：异步解析控制池与输出通道。
  * `cam_records` (工艺大师历史表)：记录用户的体积、加工深度模型拓扑数据，以及最优开粗、精扫、转速与进给参数，是专家预测引擎直接检索的语料。

### 2.3 底层 C++ 几何引擎池 (Isolated Processor)
* 基于 **FreeCAD 1.1 的无头沙盒架构**。由 Python 后端衍生执行。
* 通过直接接管 `FreeCADCmd` 或独立内嵌匹配环境的 `python.exe` 建立进程隔离，规避了 `python311.dll` 跨版本的核心冲突。
* 主要处理高耗能拓扑计算：B-Rep 装配体导入解析、面 (Face) 级拾取数据抽离，以及转化为供浏览器展示的三维网格格式流。

## 3. 系统核心流程 (Data Flow)

1. **上行解析流 (Upload & Preprocess)**:
   用户前端传入 `.step/.stp` 文件 -> FastAPI 进行 UUID 封装存档 -> 通过子进程调用底层 `FreeCAD Engine` -> 取出所有表面的绝对法向量 (Normals)、引力中心点，以及 Bounding Box 极限长宽深供预估 -> 返回带 `OBJ/glTF` 缓存地址的 JSON 图谱回挂至前端。
   *(设计有 Mock 层用于当 FreeCAD 缺位时的备用前端验证流)。*

2. **多维特征寻优流 (Craftsman Heuristics / 推荐引擎)**:
   当模型拓扑入库后，`craftsman.py` 路由将拦截工件体积 (volume) 和最高降频深度 (max_depth)。计算与历史 `cam_records` 中最近邻（欧氏距离最优）的过往案例，反向覆盖推荐诸如下刀深度 (`step_down`) 或进给率 (`feed_rate`) 的机加工参数。

3. **下行生成流 (Toolpath & Simulation)**:
   前后端参数达成一致后，下放至路由 `cam.py`，后台即可载入 FreeCAD Path Workbench (CAM 模块)，配置生成目标 CNC 机床可直接消费的 GRBL 兼容型宏编译 G-Code，并在前端模拟出工具进给路线。

## 4. 关键踩坑点及解决方案备案

| 核心问题 | 问题溯源 | 最终解决方案 |
| :--- | :--- | :--- |
| **WebGL 白屏崩溃报错** | `@react-three/drei` 的 `<Stage>` 组件 `preset` 参数值（如使用不受支持的 `machining`），渲染器试图去搜寻不存在的环境光配置对象导致空指针。 | 通过热更新即时降级为官方受支持的柔光预设 `preset="soft"` 和工业光影环境予以解决。 |
| **FreeCAD DLL Load Failed** | 作为核心外置驱动包的 FreeCAD 1.1，其内部 C++ 集成框架强锁定了发行打包自带的 Python3.11 及相关 DLL；而服务端虚拟运行环境是 Python 3.12，跨版本在全局空间引入引发动态链接库冲突。 | 在网关入口 `upload.py` 层完全废弃原有执行通道，改用动态扫描直接找到 C 盘内 `FreeCAD/bin/python.exe` 作为专用沙箱触发 `subprocess.run`。确保它在自己原生环境内运行处理后截取其 stdout 打印出的 JSON。 |
| **Console ImportGui 错误** | 后端尝试加载 FreeCAD 的 GUI 包抛出崩溃。 | 严格剔除了核心预处理代码 `freecad_processor.py` 中的 `import ImportGui`，保证其纯无头无界面解析 STEP 数据，实现绝对的性能静默执行。 |
