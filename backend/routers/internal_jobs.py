import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from models import Job

router = APIRouter()


@router.get("/recent")
def list_recent_jobs(limit: int = 12, db: Session = Depends(get_db)):
    safe_limit = max(1, min(limit, 50))
    jobs = (
        db.query(Job)
        .order_by(Job.updated_at.desc(), Job.created_at.desc())
        .limit(safe_limit)
        .all()
    )
    return {"items": [_serialize_job(job) for job in jobs]}


@router.get("/{job_id}")
def get_job_detail(job_id: str, db: Session = Depends(get_db)):
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job Not Found")
    return _serialize_job(job)


def _serialize_job(job: Job) -> dict:
    render_file = _detect_render_file(job.id)
    topology = _read_json(Path("uploads") / job.id / "topology.json")
    cam_result = _read_json(Path("uploads") / job.id / "cam_result.json")

    if topology is None and render_file:
        topology = {
            "render_file": render_file,
        }

    return {
        "job_id": job.id,
        "filename": job.filename,
        "status": job.status,
        "stage": job.stage,
        "progress": job.progress,
        "error_code": job.error_code,
        "error_message": job.error_message,
        "gcode_url": job.gcode_url,
        "render_url": f"/static/{job.id}/{render_file}" if render_file else None,
        "topology": topology,
        "cam_result": cam_result,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
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