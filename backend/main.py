from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from database import engine, ensure_jobs_columns
import models
from fastapi.staticfiles import StaticFiles
from routers import upload, craftsman, cam, jobs

# 自动生成表结构
models.Base.metadata.create_all(bind=engine)
ensure_jobs_columns()

app = FastAPI(title="Cloud CAM API", description="Backend routing for STEP processing and CNC generation")

# Allow CORS for local dev — 生产环境请收窄 allow_origins 为前端实际域名
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 挂载基础文件下载目录 (例如生成的 gltf/obj 和 G-code 文件)
from pathlib import Path
Path("uploads").mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory="uploads"), name="static")

# 挂载路由
app.include_router(upload.router, prefix="/api/v1", tags=["upload"])
app.include_router(craftsman.router, prefix="/api/v1/craftsman", tags=["expert_system"])
app.include_router(cam.router, prefix="/api/v1/cam", tags=["cam_generation"])
app.include_router(jobs.router, prefix="/api/v2/jobs", tags=["jobs_async"])

@app.get("/")
def read_root():
    return {"status": "ok", "message": "Cloud CAM API is running"}
