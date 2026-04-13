import os
import math
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional
from sqlalchemy.orm import Session
from database import get_db
from models import Job, CAMRecord

router = APIRouter()

SAFE_Z = 5.0        # 安全高度
TOOL_DIAMETER = 6.0  # 默认刀具直径 mm
STEP_OVER_RATIO = 0.4  # 行距 = 刀具直径 * 比例

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

@router.post("/generate/")
async def generate_toolpath(req: GenerateRequest, db: Session = Depends(get_db)):
    """
    根据模型实际包围盒生成多层 zigzag 粗加工刀路和对应 G-Code。
    """
    job = db.query(Job).filter(Job.id == req.job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job Not Found")

    job_dir = os.path.join("uploads", req.job_id)
    if not os.path.exists(job_dir):
        raise HTTPException(status_code=404, detail="Job 目录不存在")

    job.status = "generating"
    db.commit()

    gcode_path = f"/static/{req.job_id}/output.nc"
    sd = req.rough_step_down
    step_over = TOOL_DIAMETER * STEP_OVER_RATIO
    bx, by, bz = req.bbox_x, req.bbox_y, req.z_depth

    # 计算层数
    num_layers = max(1, math.ceil(bz / sd))
    
    gcode_lines = [
        f"(Cloud CAM Generated for Job {req.job_id})",
        f"(Model: {bx:.1f} x {by:.1f} x {bz:.1f} mm)",
        f"(Params: step_down={sd} spindle={req.spindle_speed} feed={req.feed_rate})",
        "G21 (metric)",
        "G90 (absolute)",
        f"S{req.spindle_speed} M3",
        f"G0 Z{SAFE_Z}",
    ]
    toolpath_segments = []

    prev = [0.0, 0.0, SAFE_Z]

    for layer in range(num_layers):
        z = -min(sd * (layer + 1), bz)

        # 快移到本层起点上方
        toolpath_segments.append({"type": "G0", "from": list(prev), "to": [0, 0, SAFE_Z]})
        gcode_lines.append(f"G0 X0 Y0 Z{SAFE_Z}")
        prev = [0.0, 0.0, SAFE_Z]

        # 下刀
        toolpath_segments.append({"type": "G0", "from": list(prev), "to": [0, 0, z + 1]})
        gcode_lines.append(f"G0 Z{z + 1:.3f}")
        prev = [0.0, 0.0, z + 1]

        toolpath_segments.append({"type": "G1", "from": list(prev), "to": [0, 0, z]})
        gcode_lines.append(f"G1 Z{z:.3f} F{req.feed_rate * 0.5:.0f}")
        prev = [0.0, 0.0, z]

        # Zigzag 扫描本层
        y = 0.0
        forward = True
        while y <= by:
            x_start = 0.0 if forward else bx
            x_end = bx if forward else 0.0

            # 移动到行首
            if abs(prev[1] - y) > 0.01:
                toolpath_segments.append({"type": "G1", "from": list(prev), "to": [prev[0], y, z]})
                gcode_lines.append(f"G1 Y{y:.3f} F{req.feed_rate:.0f}")
                prev = [prev[0], y, z]

            # 扫描一行
            toolpath_segments.append({"type": "G1", "from": list(prev), "to": [x_end, y, z]})
            gcode_lines.append(f"G1 X{x_end:.3f} Y{y:.3f} F{req.feed_rate:.0f}")
            prev = [x_end, y, z]

            y += step_over
            forward = not forward

        # 层末抬刀
        toolpath_segments.append({"type": "G0", "from": list(prev), "to": [prev[0], prev[1], SAFE_Z]})
        gcode_lines.append(f"G0 Z{SAFE_Z}")
        prev = [prev[0], prev[1], SAFE_Z]

    # 回原点
    toolpath_segments.append({"type": "G0", "from": list(prev), "to": [0, 0, SAFE_Z]})
    gcode_lines.extend(["G0 X0 Y0", f"G0 Z{SAFE_Z}", "M5", "M30"])

    try:
        with open(os.path.join(job_dir, "output.nc"), "w") as f:
            f.write("\n".join(gcode_lines) + "\n")
        job.status = "done"
        job.gcode_url = gcode_path
        db.commit()
    except Exception as e:
        job.status = "failed"
        db.commit()
        raise HTTPException(status_code=500, detail=f"G-Code 生成失败: {str(e)}")

    # 写入历史表
    cam_record = CAMRecord(
        model_volume=req.volume or (bx * by * bz),
        bbox_x=bx,
        bbox_y=by,
        z_depth=bz,
        rough_tool_id=req.rough_tool_id,
        rough_step_down=sd,
        spindle_speed=req.spindle_speed,
        feed_rate=req.feed_rate,
    )
    db.add(cam_record)
    db.commit()

    # 估算加工时间 (粗略: 切削总长度 / feed_rate)
    total_cut_len = sum(
        math.sqrt(sum((b - a) ** 2 for a, b in zip(s["from"], s["to"])))
        for s in toolpath_segments if s["type"] == "G1"
    )
    est_minutes = round(total_cut_len / req.feed_rate, 1) if req.feed_rate > 0 else 0

    return {
        "status": "success",
        "estimated_time_minutes": est_minutes,
        "gcode_url": gcode_path,
        "toolpath_segments": toolpath_segments,
        "stats": {
            "layers": num_layers,
            "total_cut_length_mm": round(total_cut_len, 1),
        }
    }
