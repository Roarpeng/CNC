import json
import os
from pathlib import Path
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional
from sqlalchemy.orm import Session
from database import get_db
from models import Job, CAMRecord
from services.cam_engine import (
    CamInputs,
    generate_cam_with_ocl,
    CamEngineError,
    select_tools_for_features,
    get_tool_library,
)

router = APIRouter()

STEP_OVER_RATIO = 0.4


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


class FaceVector(BaseModel):
    x: float
    y: float
    z: float


class SelectedFacePayload(BaseModel):
    face_index: int
    normal: FaceVector
    center: FaceVector


class GenerateRequest(BaseModel):
    job_id: str
    rough_tool_id: int
    rough_step_down: float
    spindle_speed: int
    feed_rate: float
    # 模型真实尺寸
    bbox_x: float
    bbox_y: float
    z_depth: float
    volume: Optional[float] = None
    selected_face: Optional[SelectedFacePayload] = None

@router.get("/tools/")
async def list_tools():
    """返回内置刀具库。"""
    return {"tools": get_tool_library()}


@router.post("/generate/")
async def generate_toolpath(req: GenerateRequest, db: Session = Depends(get_db)):
    """
    使用 OpenCAMLib 生成 CAM 刀路；若运行时不可用则自动降级为平面粗加工。
    自动根据识别到的加工特征选配刀具。
    """
    job = db.query(Job).filter(Job.id == req.job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job Not Found")

    job_dir = os.path.join("uploads", req.job_id)
    if not os.path.exists(job_dir):
        raise HTTPException(status_code=404, detail="Job 目录不存在")

    job.status = "generating"
    job.stage = "cam"
    job.progress = 35
    job.error_code = None
    job.error_message = None
    db.commit()

    topology = _read_topology(job_dir)
    mfg_features = topology.get("manufacturing_features", []) if topology else []
    part_dims = topology.get("features") if topology else None

    tool_plan = select_tools_for_features(mfg_features, part_dims)
    roughing_tool = tool_plan["roughing_tool"]
    roughing_diameter = roughing_tool["diameter"]

    gcode_path = f"/static/{req.job_id}/output.nc"
    bx, by, bz = req.bbox_x, req.bbox_y, req.z_depth
    sd = req.rough_step_down

    mesh_candidates = sorted(Path(job_dir).glob("*.stl")) + sorted(Path(job_dir).glob("*.obj"))
    mesh_path = mesh_candidates[0] if mesh_candidates else None

    if not mesh_path:
        job.status = "failed"
        job.stage = "cam"
        job.progress = 100
        job.error_code = "E3001"
        job.error_message = "缺少可用于 CAM 的网格文件 (stl/obj)"
        db.commit()
        raise HTTPException(status_code=404, detail="缺少可用于 CAM 的网格文件 (stl/obj)")

    try:
        cam_result = generate_cam_with_ocl(
            CamInputs(
                job_id=req.job_id,
                mesh_path=mesh_path,
                bbox_x=req.bbox_x,
                bbox_y=req.bbox_y,
                z_depth=req.z_depth,
                step_down=req.rough_step_down,
                spindle_speed=req.spindle_speed,
                feed_rate=req.feed_rate,
                tool_diameter=roughing_diameter,
                step_over_ratio=STEP_OVER_RATIO,
                setup_normal=(
                    req.selected_face.normal.x,
                    req.selected_face.normal.y,
                    req.selected_face.normal.z,
                ) if req.selected_face else None,
                manufacturing_features=mfg_features,
                tool_plan=tool_plan,
            )
        )
    except CamEngineError as e:
        job.status = "failed"
        job.stage = "cam"
        job.progress = 100
        job.error_code = "E3001"
        job.error_message = str(e)
        db.commit()
        raise HTTPException(status_code=500, detail=str(e))

    gcode_lines = cam_result["gcode_lines"]
    toolpath_segments = cam_result["toolpath_segments"]

    try:
        with open(os.path.join(job_dir, "output.nc"), "w") as f:
            f.write("\n".join(gcode_lines) + "\n")
        _write_json(Path(job_dir) / "cam_result.json", {
            "estimated_time_minutes": cam_result["estimated_time_minutes"],
            "stats": cam_result["stats"],
            "toolpath_segments": toolpath_segments,
            "tool_plan": tool_plan,
        })
        job.status = "done"
        job.stage = "completed"
        job.progress = 100
        job.gcode_url = gcode_path
        db.commit()
    except Exception as e:
        job.status = "failed"
        job.stage = "cam"
        job.progress = 100
        job.error_code = "E5001"
        job.error_message = str(e)
        db.commit()
        raise HTTPException(status_code=500, detail=f"G-Code 生成失败: {str(e)}")

    cam_record = CAMRecord(
        model_volume=req.volume or (bx * by * bz),
        bbox_x=bx,
        bbox_y=by,
        z_depth=bz,
        rough_tool_id=roughing_tool["id"],
        rough_step_down=sd,
        spindle_speed=req.spindle_speed,
        feed_rate=req.feed_rate,
    )
    db.add(cam_record)
    db.commit()

    return {
        "job_id": req.job_id,
        "status": "success",
        "job_status": job.status,
        "stage": job.stage,
        "progress": job.progress,
        "estimated_time_minutes": cam_result["estimated_time_minutes"],
        "gcode_url": gcode_path,
        "toolpath_segments": toolpath_segments,
        "stats": cam_result["stats"],
        "tool_plan": tool_plan,
    }


def _read_topology(job_dir: str) -> dict | None:
    topo_path = Path(job_dir) / "topology.json"
    if not topo_path.exists():
        return None
    try:
        return json.loads(topo_path.read_text(encoding="utf-8"))
    except Exception:
        return None
