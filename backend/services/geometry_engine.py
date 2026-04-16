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
        manufacturing_features = _recognize_features(shape)
        feature_summary = _summarize_features(manufacturing_features)

        faces: list[dict[str, Any]] = []
        for idx, face in enumerate(shape.Faces()):
            center = face.Center()
            normal = _safe_face_normal(face, center)

            faces.append(
                {
                    "face_id": idx,
                    "surface_type": face.geomType(),
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
            "manufacturing_features": manufacturing_features,
            "feature_summary": feature_summary,
            "render_file": render_file,
            "fallback_render_file": stl_file,
        }
    except Exception as exc:
        raise GeometryEngineError(f"CadQuery 解析失败: {exc}") from exc


def _safe_face_normal(face: cq.Face, center: cq.Vector | None = None) -> cq.Vector:
    try:
        if center is not None:
            return face.normalAt(center)
    except Exception:
        pass

    try:
        u_min, u_max, v_min, v_max = face._uvBounds()  # type: ignore[attr-defined]
        return face.normalAt((u_min + u_max) * 0.5, (v_min + v_max) * 0.5)
    except Exception:
        return cq.Vector(0.0, 0.0, 1.0)


def _recognize_features(shape: cq.Shape) -> list[dict[str, Any]]:
    part_bbox = shape.BoundingBox()
    part_x = float(part_bbox.xlen)
    part_y = float(part_bbox.ylen)
    max_z = float(part_bbox.zmax)
    min_z = float(part_bbox.zmin)
    full_top_area = max(float(part_bbox.xlen * part_bbox.ylen), 1e-6)
    z_tol = max(float(part_bbox.zlen) * 0.02, 0.25)
    lateral_tol = max(min(float(part_bbox.xlen), float(part_bbox.ylen)) * 0.05, 0.5)

    recognized: list[dict[str, Any]] = []
    face_index = 0
    for face in shape.Faces():
        face_type = str(face.geomType()).upper()
        center = face.Center()
        normal = _safe_face_normal(face, center)
        bbox = face.BoundingBox()
        area = float(face.Area())

        if face_type == "CYLINDER":
            feature = _classify_cylindrical_feature(face_index, center, bbox, part_bbox, max_z, z_tol)
            if feature is not None:
                recognized.append(feature)
        elif face_type == "PLANE":
            feature = _classify_planar_feature(
                face_index=face_index,
                center=center,
                normal=normal,
                bbox=bbox,
                area=area,
                max_z=max_z,
                min_z=min_z,
                part_x=part_x,
                part_y=part_y,
                full_top_area=full_top_area,
                z_tol=z_tol,
                lateral_tol=lateral_tol,
            )
            if feature is not None:
                recognized.append(feature)

        face_index += 1

    return recognized


def _classify_cylindrical_feature(
    face_index: int,
    center: cq.Vector,
    bbox: Any,
    part_bbox: Any,
    max_z: float,
    z_tol: float,
) -> dict[str, Any] | None:
    dims = sorted([float(bbox.xlen), float(bbox.ylen), float(bbox.zlen)])
    diameter = max((dims[0] + dims[1]) * 0.5, 0.0)
    depth = float(dims[2])
    if diameter <= 0.2 or depth <= 0.2:
        return None

    max_part_span = max(float(part_bbox.xlen), float(part_bbox.ylen), float(part_bbox.zlen))
    if diameter > max_part_span * 0.9:
        return None

    axis = _dominant_axis(float(bbox.xlen), float(bbox.ylen), float(bbox.zlen))
    is_recessed = float(center.z) < max_z - z_tol
    feature_type = "hole" if is_recessed else "boss"

    return {
        "type": feature_type,
        "surface": "cylinder",
        "face_id": face_index,
        "diameter": round(diameter, 3),
        "depth": round(depth, 3),
        "axis": axis,
        "center": {"x": float(center.x), "y": float(center.y), "z": float(center.z)},
    }


def _classify_planar_feature(
    *,
    face_index: int,
    center: cq.Vector,
    normal: cq.Vector,
    bbox: Any,
    area: float,
    max_z: float,
    min_z: float,
    part_x: float,
    part_y: float,
    full_top_area: float,
    z_tol: float,
    lateral_tol: float,
) -> dict[str, Any] | None:
    if abs(float(normal.z)) < 0.9:
        return None

    bounds = {
        "x": round(float(bbox.xlen), 3),
        "y": round(float(bbox.ylen), 3),
    }
    if bounds["x"] <= 0.2 or bounds["y"] <= 0.2:
        return None

    center_payload = {"x": float(center.x), "y": float(center.y), "z": float(center.z)}
    is_top_like = abs(float(center.z) - max_z) <= z_tol
    is_inner_xy = bounds["x"] < part_x - lateral_tol or bounds["y"] < part_y - lateral_tol

    if float(normal.z) > 0 and not is_top_like:
        return {
            "type": "pocket",
            "surface": "plane",
            "face_id": face_index,
            "depth": round(max_z - float(center.z), 3),
            "bounds": bounds,
            "area": round(area, 3),
            "center": center_payload,
        }

    if float(normal.z) > 0 and is_top_like and is_inner_xy and area < full_top_area * 0.9:
        return {
            "type": "boss",
            "surface": "plane",
            "face_id": face_index,
            "height": round(float(center.z) - min_z, 3),
            "bounds": bounds,
            "area": round(area, 3),
            "center": center_payload,
        }

    return None


def _dominant_axis(x_len: float, y_len: float, z_len: float) -> str:
    axis_lengths = {"x": x_len, "y": y_len, "z": z_len}
    return max(axis_lengths, key=axis_lengths.get)


def _summarize_features(features: list[dict[str, Any]]) -> dict[str, int]:
    summary: dict[str, int] = {}
    for feature in features:
        key = str(feature.get("type", "unknown"))
        summary[key] = summary.get(key, 0) + 1
    return summary
