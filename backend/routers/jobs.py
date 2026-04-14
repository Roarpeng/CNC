import uuid
import json
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from models import Job
from tasks import generate_cam_task, parse_step_task

router = APIRouter()

UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
MAX_FILE_SIZE = 100 * 1024 * 1024


class GenerateAsyncRequest(BaseModel):
    rough_tool_id: int
    rough_step_down: float
    spindle_speed: int
    feed_rate: float
    bbox_x: float
    bbox_y: float
    z_depth: float
    volume: float | None = None


@router.post("/")
async def create_job(file: UploadFile = File(...), db: Session = Depends(get_db)):
    if not (file.filename.lower().endswith(".step") or file.filename.lower().endswith(".stp")):
        raise HTTPException(status_code=400, detail="仅支持 .step / .stp 格式文件")

    contents = await file.read()
    if len(contents) > MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail=f"文件过大 (>{MAX_FILE_SIZE // 1024 // 1024} MB)")

    job_id = str(uuid.uuid4())
    safe_filename = f"{job_id}_{file.filename}"
    file_path = UPLOAD_DIR / safe_filename
    output_dir = UPLOAD_DIR / job_id
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        file_path.write_bytes(contents)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"保存文件失败: {exc}")

    job = Job(id=job_id, filename=file.filename, status="queued", stage="queued", progress=0)
    db.add(job)
    db.commit()

    parse_step_task.delay(job_id, str(file_path), str(output_dir))

    return {
        "job_id": job_id,
        "status": "queued",
        "message": "任务已提交，正在异步解析",
    }


@router.get("/{job_id}")
def get_job_status(job_id: str, db: Session = Depends(get_db)):
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job Not Found")

    render_file = _detect_render_file(job_id)
    render_url = f"/static/{job_id}/{render_file}" if render_file else None
    topology = _read_json(Path("uploads") / job_id / "topology.json")
    cam_result = _read_json(Path("uploads") / job_id / "cam_result.json")

    return {
        "job_id": job.id,
        "filename": job.filename,
        "status": job.status,
        "stage": job.stage,
        "progress": job.progress,
        "error_code": job.error_code,
        "error_message": job.error_message,
        "gcode_url": job.gcode_url,
        "render_url": render_url,
        "topology": topology,
        "cam_result": cam_result,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
    }


@router.post("/{job_id}/cam")
def enqueue_cam(job_id: str, req: GenerateAsyncRequest, db: Session = Depends(get_db)):
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job Not Found")

    if job.status not in {"parsed", "parsed_mock", "done"}:
        raise HTTPException(status_code=409, detail=f"当前状态 {job.status} 不允许提交 CAM 任务")

    generate_cam_task.delay(job_id, req.model_dump())

    return {
        "job_id": job_id,
        "status": "queued",
        "message": "CAM 任务已提交",
    }


@router.get("/{job_id}/artifacts")
def get_job_artifacts(job_id: str, db: Session = Depends(get_db)):
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job Not Found")

    render_file = _detect_render_file(job_id)
    topology = _read_json(Path("uploads") / job_id / "topology.json")
    cam_result = _read_json(Path("uploads") / job_id / "cam_result.json")

    return {
        "job_id": job.id,
        "status": job.status,
        "render_url": f"/static/{job_id}/{render_file}" if render_file else None,
        "gcode_url": job.gcode_url,
        "topology": topology,
        "cam_result": cam_result,
    }


def _detect_render_file(job_id: str) -> str | None:
    job_dir = Path("uploads") / job_id
    if not job_dir.exists():
        return None

    for ext in ("*.glb", "*.stl", "*.obj"):
        files = sorted(job_dir.glob(ext))
        if files:
            return files[0].name
    return None


def _read_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
