# Cloud CAM SaaS 工业化改造 RFC

状态: Draft
作者: 平台架构组
日期: 2026-04-14

## 1. 背景与目标

当前系统已完成核心流程闭环（上传 -> 几何解析 -> CAM -> 刀路可视化），但执行模型仍以同步 API 驱动为主，存在以下风险：

1. 计算任务与请求生命周期耦合，峰值并发下会阻塞 Web 线程。
2. 文件链路仍以本地静态文件为主，难以支撑跨实例扩容与高吞吐下载。
3. SQLite 在高并发写状态场景下存在锁争用风险。
4. 缺少 SaaS 必需的多租户、审计、可观测、计费基础能力。

本 RFC 目标：在保持现有产品功能可用的前提下，把系统升级为可商业化运行的多租户工业级 Cloud CAM 平台。

## 2. 非目标

1. 本期不重写前端业务流程（保留现有交互模式）。
2. 本期不实现完整计费结算，仅预埋计量数据。
3. 本期不引入 Kubernetes 专属能力，先保证在 Docker Compose/VM 集群可稳定运行。

## 3. 总体架构

### 3.1 逻辑分层

1. API 层（FastAPI）
- 负责认证鉴权、参数校验、提交任务、查询状态、签名下载。

2. 调度层（Celery + Redis）
- 负责异步任务分发、重试、超时、死信处理。

3. 计算层（Worker）
- parse worker: CadQuery STEP/B-Rep 解析。
- cam worker: OpenCAMLib 刀路计算。
- post worker: GLB 转换、Draco 压缩、缩略图/统计信息。

4. 数据层（PostgreSQL）
- 存储任务状态、工艺历史、租户与权限、审计日志。

5. 对象存储层（S3/MinIO）
- 存储上传原件、网格产物、G-code、日志产物。

6. 分发层（CDN）
- 对 GLB/G-code 提供边缘加速和缓存。

### 3.2 关键原则

1. 提交即返回：API 只做入队，不做重计算。
2. 任务幂等：同输入参数哈希不重复计算。
3. 可观测优先：每个 job 全链路可追踪。
4. 产物可回放：任意失败可定位到阶段和输入。

## 4. 任务状态机设计

状态枚举：

1. queued
2. parsing
3. meshing
4. cam_generating
5. postprocessing
6. completed
7. failed
8. canceled

失败码建议：

1. E1001 文件校验失败
2. E2001 几何解析失败
3. E3001 OCL 计算失败
4. E3002 OCL 降级执行
5. E4001 后处理失败
6. E5001 存储写入失败
7. E9001 未知异常

## 5. API 契约（v2）

### 5.1 提交任务

POST /api/v2/jobs

请求体：

```json
{
  "project_id": "uuid",
  "source_object_key": "tenant-a/raw/part.step",
  "cam_profile": {
    "rough_tool_id": 1,
    "rough_step_down": 1.5,
    "feed_rate": 1200,
    "spindle_speed": 8000,
    "strategy": "rough+finish"
  }
}
```

响应体：

```json
{
  "job_id": "uuid",
  "status": "queued",
  "poll_url": "/api/v2/jobs/{job_id}"
}
```

### 5.2 查询任务

GET /api/v2/jobs/{job_id}

响应体：

```json
{
  "job_id": "uuid",
  "status": "cam_generating",
  "stage": "drop_cutter",
  "progress": 64,
  "error_code": null,
  "error_message": null,
  "started_at": "...",
  "updated_at": "..."
}
```

### 5.3 查询产物

GET /api/v2/jobs/{job_id}/artifacts

响应体：

```json
{
  "render_glb_url": "https://cdn.example.com/...",
  "render_glb_draco": true,
  "gcode_url": "https://cdn.example.com/...",
  "preview_png_url": "https://cdn.example.com/...",
  "stats": {
    "strategy": "ocl_drop_cutter",
    "total_cut_length_mm": 1532.2,
    "estimated_time_minutes": 21.8
  }
}
```

### 5.4 实时进度（可选）

1. SSE: GET /api/v2/jobs/{job_id}/events
2. WebSocket: /ws/jobs/{job_id}

## 6. 数据库模型改造（PostgreSQL）

### 6.1 jobs 表（新增/扩展）

1. id uuid pk
2. tenant_id uuid not null index
3. project_id uuid not null index
4. user_id uuid not null index
5. status varchar(32) not null index
6. stage varchar(64)
7. progress int default 0
8. error_code varchar(32)
9. error_message text
10. source_object_key text not null
11. render_object_key text
12. gcode_object_key text
13. input_hash varchar(64) index
14. retry_count int default 0
15. created_at timestamptz
16. started_at timestamptz
17. finished_at timestamptz
18. updated_at timestamptz

索引建议：

1. (tenant_id, created_at desc)
2. (tenant_id, status, updated_at)
3. unique (tenant_id, input_hash) where status in ('queued','parsing','meshing','cam_generating','postprocessing')

### 6.2 cam_records 表增强

新增字段：

1. tenant_id uuid index
2. material varchar(64)
3. machine_model varchar(64)
4. quality_score float
5. cycle_time_seconds float
6. ocl_strategy varchar(64)

### 6.3 租户与权限基础表

1. tenants
2. users
3. memberships
4. projects
5. api_keys
6. audit_logs

## 7. Celery 编排设计

### 7.1 队列拓扑

1. q_parse_cpu
2. q_cam_cpu
3. q_postprocess_io
3. q_dead_letter

### 7.2 DAG

1. task_parse_step(job_id)
2. task_generate_toolpath(job_id)
3. task_generate_glb_draco(job_id)
4. task_publish_artifacts(job_id)

使用 chain：

parse -> cam -> postprocess -> publish

### 7.3 重试策略

1. 几何解析失败：最多 1 次（多为输入问题）
2. 存储/网络失败：指数退避重试 3 次
3. 超时：按任务阶段设置 hard time limit

### 7.4 幂等策略

1. 任务开始前检查 job.status 是否已终态。
2. 以 input_hash 做同租户去重。
3. 发布产物时写入对象 key 前先检查是否已存在。

## 8. 渲染产物升级（GLB + Draco）

### 8.1 产物规范

1. 内部 CAM 计算网格: STL/三角网格
2. 前端渲染网格: GLB（Draco 压缩）
3. 文件命名: content-hash，保证缓存友好

### 8.2 前端改造

1. 主加载器改为 GLTFLoader
2. 保留 OBJ/STL fallback（仅用于历史兼容）
3. 增加加载分级：低模预览 -> 全精度替换

### 8.3 传输优化

1. CDN 缓存策略：immutable + 长缓存
2. 下载链接签名过期时间：10~30 分钟

## 9. 安全与合规

1. 上传安全：扩展名+MIME 双校验，限制最大尺寸，拒绝压缩炸弹。
2. 鉴权：JWT + API Key（服务对服务）。
3. 数据隔离：所有查询必须 tenant_id 过滤。
4. 审计：记录提交任务、下载产物、参数修改行为。
5. 敏感配置：统一环境变量与密钥管理（不入库、不入 git）。

## 10. 可观测性与 SLO

### 10.1 指标

1. API p95 延迟
2. 队列排队时长
3. 任务阶段耗时分布
4. 失败率与重试率
5. 单任务 CPU 秒与存储体积

### 10.2 日志与追踪

1. 结构化日志字段：trace_id, tenant_id, job_id, stage, error_code
2. OpenTelemetry 链路：API -> Celery -> Worker -> DB -> Object Storage

### 10.3 SLO 建议

1. 提交接口可用性 99.9%
2. 中型任务（<80MB）30 分钟内完成率 99%
3. 任务状态更新延迟 < 3 秒

## 11. 交付里程碑（4 个 PR 波次）

### PR-1 基础设施波次（1~2 周）

1. 引入 Celery/Redis 基础框架
2. 新增 jobs v2 API（提交/状态查询）
3. 抽象 JobService 与 TaskDispatcher

验收：API 可提交任务并更新状态到 queued/parsing。

### PR-2 数据层波次（1~2 周）

1. 接入 PostgreSQL
2. 引入 Alembic 迁移
3. 完成 jobs/cam_records 新字段与索引

验收：并发状态写入无锁库错误，迁移可重复执行。

### PR-3 产物链路波次（2 周）

1. 对象存储接入（S3/MinIO）
2. GLB+Draco 后处理任务
3. 前端 GLB 主链路加载

验收：复杂模型加载体积降低 60% 以上。

### PR-4 SaaS 能力波次（2 周）

1. 多租户与 RBAC
2. 审计日志
3. 指标与 tracing 仪表盘

验收：租户间数据隔离通过测试，关键指标可视化。

## 12. 风险与回滚

1. 风险：OCL 绑定版本碎片化。
- 缓解：适配层 + fallback + 版本白名单。

2. 风险：任务积压导致 SLA 退化。
- 缓解：队列分级、worker 自动扩容、告警阈值。

3. 风险：迁移阶段双写不一致。
- 缓解：灰度发布，先只读比对，再切流。

回滚策略：

1. API 保留 v1，v2 可灰度开关。
2. 任务调度异常时，降级回同步模式仅用于内部运维通道。
3. 关键迁移脚本提供 down 版本。

## 13. 验收清单（上线门槛）

1. 压测：20 并发大文件提交，API 稳定无超时风暴。
2. 正确性：金样件路径偏差在阈值内。
3. 稳定性：连续 72 小时 soak test 无严重告警。
4. 安全性：鉴权、越权、签名下载测试通过。
5. 可运维：Dashboard 覆盖 API/队列/Worker/DB/存储。

## 14. 推荐目录结构（目标态）

```text
backend/
  app/
    api/
      v1/
      v2/
    core/
      config.py
      security.py
      logging.py
    db/
      session.py
      models/
      migrations/
    services/
      geometry/
      cam/
      artifact/
      jobs/
    tasks/
      celery_app.py
      parse_tasks.py
      cam_tasks.py
      post_tasks.py
```

## 15. 立即执行建议（本周）

1. 先落地 PR-1 最小闭环（提交任务 + 状态查询 + 单 worker 跑 parse）。
2. 并行准备 PostgreSQL/Alembic 迁移脚本。
3. 选型并验证一个 GLB+Draco 转换工具链，形成固定镜像。
