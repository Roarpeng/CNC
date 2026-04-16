import os
import json
import logging
from pathlib import Path

from database import SessionLocal
from models import CAMRecord, Job
from services.cam_engine import CamEngineError, CamInputs, generate_cam_with_ocl
from services.geometry_engine import GeometryEngineError, parse_step_with_cadquery

logger = logging.getLogger(__name__)


def _get_mesh_path(job_dir: str) -> Path | None:
    candidates = sorted(Path(job_dir).glob("*.stl")) + sorted(Path(job_dir).glob("*.obj"))
    return candidates[0] if candidates else None


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _set_job_state(job: Job, db, status: str, stage: str, progress: int, error_code: str | None = None, error_message: str | None = None) -> None:
    job.status = status
    job.stage = stage
    job.progress = progress
    job.error_code = error_code
    job.error_message = error_message
    db.commit()


def parse_step_task(job_id: str, input_file_path: str, output_dir: str) -> dict:
    """同步解析 STEP 文件，提取拓扑信息并生成网格文件。"""
    db = SessionLocal()
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        if not job:
            return {"status": "failed", "error": "Job Not Found"}

        _set_job_state(job, db, status="parsing", stage="parsing", progress=10)

        try:
            topology = parse_step_with_cadquery(input_file_path, output_dir)
            _write_json(Path(output_dir) / "topology.json", topology)
            _set_job_state(job, db, status="parsed", stage="meshing", progress=100)
            return {"status": "parsed", "topology": topology}
        except GeometryEngineError as exc:
            logger.warning("CadQuery parse failed for job %s: %s", job_id, str(exc))
            mock_obj = _generate_mock_box_obj(50.0, 50.0, 20.0)
            mock_obj_path = Path(output_dir) / "mock_model.obj"
            mock_obj_path.write_text(mock_obj)
            topology = {
                "features": {"volume": 15000.5, "bbox_x": 50.0, "bbox_y": 50.0, "z_depth": 20.0},
                "faces": [
                    {"face_id": 0, "normal": {"x": 0, "y": 0, "z": 1}, "center": {"x": 25, "y": 25, "z": 20}},
                    {"face_id": 1, "normal": {"x": 0, "y": 0, "z": -1}, "center": {"x": 25, "y": 25, "z": 0}},
                    {"face_id": 2, "normal": {"x": 0, "y": -1, "z": 0}, "center": {"x": 25, "y": 0, "z": 10}},
                    {"face_id": 3, "normal": {"x": 0, "y": 1, "z": 0}, "center": {"x": 25, "y": 50, "z": 10}},
                    {"face_id": 4, "normal": {"x": -1, "y": 0, "z": 0}, "center": {"x": 0, "y": 25, "z": 10}},
                    {"face_id": 5, "normal": {"x": 1, "y": 0, "z": 0}, "center": {"x": 50, "y": 25, "z": 10}},
                ],
                "manufacturing_features": [],
                "feature_summary": {},
                "render_file": "mock_model.obj",
            }
            _write_json(Path(output_dir) / "topology.json", topology)
            _set_job_state(job, db, status="parsed_mock", stage="meshing", progress=100, error_code="E2001", error_message=str(exc))
            return {"status": "parsed_mock", "topology": topology}
    except Exception as exc:
        logger.exception("parse_step_task failed for job %s", job_id)
        job = db.query(Job).filter(Job.id == job_id).first()
        if job:
            _set_job_state(job, db, status="failed", stage="parsing", progress=100, error_code="E9001", error_message=str(exc))
        return {"status": "failed", "error": str(exc)}
    finally:
        db.close()


def generate_cam_task(job_id: str, cam_req: dict) -> dict:
    """同步生成 CAM 刀路和 G-Code。"""
    db = SessionLocal()
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        if not job:
            return {"status": "failed", "error": "Job Not Found"}

        job_dir = os.path.join("uploads", job_id)
        if not os.path.exists(job_dir):
            _set_job_state(job, db, status="failed", stage="cam", progress=100, error_code="E3001", error_message="Job 目录不存在")
            return {"status": "failed", "error": "Job 目录不存在"}

        mesh_path = _get_mesh_path(job_dir)
        if not mesh_path:
            _set_job_state(job, db, status="failed", stage="cam", progress=100, error_code="E3001", error_message="缺少可用于 CAM 的网格文件")
            return {"status": "failed", "error": "缺少可用于 CAM 的网格文件"}

        _set_job_state(job, db, status="generating", stage="cam", progress=30)

        try:
            result = generate_cam_with_ocl(
                CamInputs(
                    job_id=job_id,
                    mesh_path=mesh_path,
                    bbox_x=cam_req["bbox_x"],
                    bbox_y=cam_req["bbox_y"],
                    z_depth=cam_req["z_depth"],
                    step_down=cam_req["rough_step_down"],
                    spindle_speed=cam_req["spindle_speed"],
                    feed_rate=cam_req["feed_rate"],
                    setup_normal=tuple(cam_req["selected_face"]["normal"][key] for key in ("x", "y", "z")) if cam_req.get("selected_face") else None,
                    manufacturing_features=cam_req.get("manufacturing_features", []),
                    tool_plan=cam_req.get("tool_plan"),
                )
            )
        except CamEngineError as exc:
            _set_job_state(job, db, status="failed", stage="cam", progress=100, error_code="E3001", error_message=str(exc))
            return {"status": "failed", "error": str(exc)}

        output_path = os.path.join(job_dir, "output.nc")
        with open(output_path, "w", encoding="utf-8") as f:
            f.write("\n".join(result["gcode_lines"]) + "\n")

        job.gcode_url = f"/static/{job_id}/output.nc"
        _set_job_state(job, db, status="done", stage="completed", progress=100)

        cam_record = CAMRecord(
            model_volume=cam_req.get("volume") or (cam_req["bbox_x"] * cam_req["bbox_y"] * cam_req["z_depth"]),
            bbox_x=cam_req["bbox_x"],
            bbox_y=cam_req["bbox_y"],
            z_depth=cam_req["z_depth"],
            rough_tool_id=cam_req["rough_tool_id"],
            rough_step_down=cam_req["rough_step_down"],
            spindle_speed=cam_req["spindle_speed"],
            feed_rate=cam_req["feed_rate"],
        )
        db.add(cam_record)
        db.commit()

        _write_json(Path(job_dir) / "cam_result.json", {
            "estimated_time_minutes": result["estimated_time_minutes"],
            "stats": result["stats"],
        })

        return {
            "status": "done",
            "gcode_url": job.gcode_url,
            "estimated_time_minutes": result["estimated_time_minutes"],
            "stats": result["stats"],
        }
    except Exception as exc:
        logger.exception("generate_cam_task failed for job %s", job_id)
        job = db.query(Job).filter(Job.id == job_id).first()
        if job:
            _set_job_state(job, db, status="failed", stage="cam", progress=100, error_code="E9001", error_message=str(exc))
        return {"status": "failed", "error": str(exc)}
    finally:
        db.close()


def _generate_mock_box_obj(sx: float, sy: float, sz: float) -> str:
    verts = [
        (0, 0, 0), (sx, 0, 0), (sx, sy, 0), (0, sy, 0),
        (0, 0, sz), (sx, 0, sz), (sx, sy, sz), (0, sy, sz),
    ]
    normals = [
        (0, 0, -1), (0, 0, 1),
        (0, -1, 0), (0, 1, 0),
        (-1, 0, 0), (1, 0, 0),
    ]
    faces = [
        (1, 2, 3, 1), (1, 3, 4, 1),
        (5, 7, 6, 2), (5, 8, 7, 2),
        (1, 6, 2, 3), (1, 5, 6, 3),
        (3, 8, 4, 4), (3, 7, 8, 4),
        (1, 4, 8, 5), (1, 8, 5, 5),
        (2, 6, 7, 6), (2, 7, 3, 6),
    ]
    lines = ["# Mock box OBJ generated by Cloud CAM"]
    for v in verts:
        lines.append(f"v {v[0]} {v[1]} {v[2]}")
    for n in normals:
        lines.append(f"vn {n[0]} {n[1]} {n[2]}")
    for f in faces:
        lines.append(f"f {f[0]}//{f[3]} {f[1]}//{f[3]} {f[2]}//{f[3]}")
    return "\n".join(lines) + "\n"
