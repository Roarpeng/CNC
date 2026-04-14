from __future__ import annotations

from pathlib import Path
from typing import Any

import cadquery as cq
import trimesh


class GeometryEngineError(RuntimeError):
    """Raised when CAD parsing or mesh export fails."""


def parse_step_with_cadquery(step_path: str, output_dir: str, mesh_tolerance: float = 0.1) -> dict[str, Any]:
    """
    Parse STEP with CadQuery/OCC and export a render mesh.

    Returns the same topology contract expected by frontend:
    {
      "features": {"volume", "bbox_x", "bbox_y", "z_depth"},
      "faces": [{"face_id", "normal", "center"}],
      "render_file": "*.stl"
    }
    """
    try:
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        workplane = cq.importers.importStep(step_path)
        shape = workplane.val()

        bbox = shape.BoundingBox()
        features = {
            "volume": float(shape.Volume()),
            "bbox_x": float(bbox.xlen),
            "bbox_y": float(bbox.ylen),
            "z_depth": float(bbox.zlen),
        }

        faces: list[dict[str, Any]] = []
        for idx, face in enumerate(shape.Faces()):
            center = face.Center()
            try:
                normal = face.normalAt(center)
            except Exception:
                normal = cq.Vector(0.0, 0.0, 1.0)

            faces.append(
                {
                    "face_id": idx,
                    "normal": {"x": float(normal.x), "y": float(normal.y), "z": float(normal.z)},
                    "center": {"x": float(center.x), "y": float(center.y), "z": float(center.z)},
                }
            )

        base_name = Path(step_path).stem
        stl_file = f"{base_name}.stl"
        stl_path = output_path / stl_file
        cq.exporters.export(shape, str(stl_path), tolerance=mesh_tolerance)

        # 优先生成 glb 供前端加载，失败时自动回退到 stl。
        render_file = stl_file
        try:
            glb_file = f"{base_name}.glb"
            glb_path = output_path / glb_file
            tri_mesh = trimesh.load_mesh(str(stl_path), force="mesh")
            tri_mesh.export(str(glb_path))
            render_file = glb_file
        except Exception:
            pass

        return {
            "features": features,
            "faces": faces,
            "render_file": render_file,
            "fallback_render_file": stl_file,
        }
    except Exception as exc:
        raise GeometryEngineError(f"CadQuery 解析失败: {exc}") from exc
