from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import trimesh


SAFE_Z_DEFAULT = 5.0


class CamEngineError(RuntimeError):
    """Raised when OpenCAMLib or fallback toolpath generation fails."""


@dataclass
class CamInputs:
    job_id: str
    mesh_path: Path
    bbox_x: float
    bbox_y: float
    z_depth: float
    step_down: float
    spindle_speed: int
    feed_rate: float
    tool_diameter: float = 6.0
    step_over_ratio: float = 0.4
    safe_z: float = SAFE_Z_DEFAULT
    setup_normal: tuple[float, float, float] | None = None


def generate_cam_with_ocl(inputs: CamInputs) -> dict[str, Any]:
    """
    Preferred pipeline: OpenCAMLib drop-cutter.
    If runtime binding is unavailable, falls back to a deterministic planar roughing path
    while keeping the same API contract.
    """
    try:
        mesh = _load_prepared_mesh(inputs)
        extents = mesh.bounds[1] - mesh.bounds[0]

        if _has_ocl_runtime():
            return _generate_dropcutter_toolpath(inputs, mesh, extents)
        return _generate_planar_fallback(inputs, mesh, extents, strategy="fallback_no_ocl")
    except Exception as exc:
        raise CamEngineError(f"CAM 生成失败: {exc}") from exc


def _load_prepared_mesh(inputs: CamInputs) -> trimesh.Trimesh:
    mesh = trimesh.load_mesh(str(inputs.mesh_path), force="mesh")
    if isinstance(mesh, trimesh.Scene):
        mesh = mesh.dump(concatenate=True)
    if not isinstance(mesh, trimesh.Trimesh):
        raise CamEngineError("无法加载有效的三角网格")

    prepared = mesh.copy()
    if inputs.setup_normal is not None:
        prepared.apply_transform(_rotation_matrix_from_vectors(np.asarray(inputs.setup_normal, dtype=float), np.array([0.0, 0.0, -1.0], dtype=float)))

    prepared.apply_translation(-prepared.bounds[0])
    return prepared


def _rotation_matrix_from_vectors(source: np.ndarray, target: np.ndarray) -> np.ndarray:
    src = source / max(np.linalg.norm(source), 1e-9)
    dst = target / max(np.linalg.norm(target), 1e-9)
    dot = float(np.clip(np.dot(src, dst), -1.0, 1.0))

    if math.isclose(dot, 1.0, abs_tol=1e-6):
        return np.eye(4)

    if math.isclose(dot, -1.0, abs_tol=1e-6):
        axis = np.cross(src, np.array([1.0, 0.0, 0.0], dtype=float))
        if np.linalg.norm(axis) < 1e-6:
            axis = np.cross(src, np.array([0.0, 1.0, 0.0], dtype=float))
        axis = axis / max(np.linalg.norm(axis), 1e-9)
        return trimesh.transformations.rotation_matrix(math.pi, axis)

    cross = np.cross(src, dst)
    skew = np.array([
        [0.0, -cross[2], cross[1]],
        [cross[2], 0.0, -cross[0]],
        [-cross[1], cross[0], 0.0],
    ])
    rotation = np.eye(3) + skew + (skew @ skew) * ((1.0 - dot) / max(np.linalg.norm(cross) ** 2, 1e-9))
    matrix = np.eye(4)
    matrix[:3, :3] = rotation
    return matrix


def _has_ocl_runtime() -> bool:
    try:
        import ocl  # type: ignore

        return ocl is not None
    except Exception:
        return False


def _generate_dropcutter_toolpath(inputs: CamInputs, mesh: trimesh.Trimesh, extents: np.ndarray) -> dict[str, Any]:
    """
    OpenCAMLib binding adapter.

    The exact Python API differs across OpenCAMLib builds/distributions.
    We keep the adapter conservative: if required symbols are missing,
    we transparently downgrade to planar fallback instead of failing request.
    """
    try:
        import ocl  # type: ignore

        required_symbols = ["STLSurf", "DropCutter", "CLPoint", "BallCutter"]
        if not all(hasattr(ocl, sym) for sym in required_symbols):
            return _generate_planar_fallback(inputs, mesh, extents, strategy="fallback_ocl_symbols_missing")

        surf = ocl.STLSurf()

        for tri in mesh.triangles:
            p1, p2, p3 = tri
            # Most OpenCAMLib builds expose Triangle(x1,y1,z1,x2,y2,z2,x3,y3,z3).
            if hasattr(ocl, "Triangle"):
                surf.addTriangle(
                    ocl.Triangle(
                        float(p1[0]), float(p1[1]), float(p1[2]),
                        float(p2[0]), float(p2[1]), float(p2[2]),
                        float(p3[0]), float(p3[1]), float(p3[2]),
                    )
                )
            else:
                return _generate_planar_fallback(inputs, mesh, extents, strategy="fallback_ocl_triangle_missing")

        drop = ocl.DropCutter()
        drop.setSTL(surf)
        cutter_radius = max(inputs.tool_diameter * 0.5, 0.1)
        cutter = ocl.BallCutter(float(cutter_radius), float(inputs.tool_diameter * 4.0))
        drop.setCutter(cutter)

        step_over = max(inputs.tool_diameter * inputs.step_over_ratio, 0.1)
        y = 0.0
        forward = True
        while y <= float(extents[1]) + 1e-6:
            x_from = 0.0 if forward else float(extents[0])
            x_to = float(extents[0]) if forward else 0.0
            drop.appendPoint(ocl.CLPoint(float(x_from), float(y), float(inputs.safe_z)))
            drop.appendPoint(ocl.CLPoint(float(x_to), float(y), float(inputs.safe_z)))
            y += step_over
            forward = not forward

        drop.run()
        cl_points = list(drop.getCLPoints())
        if len(cl_points) < 2:
            return _generate_planar_fallback(inputs, mesh, extents, strategy="fallback_ocl_empty")

        gcode_lines = [
            f"(Cloud CAM OCL Generated for Job {inputs.job_id})",
            f"(Model: {float(extents[0]):.1f} x {float(extents[1]):.1f} x {float(extents[2]):.1f} mm)",
            f"(Params: step_down={inputs.step_down} spindle={inputs.spindle_speed} feed={inputs.feed_rate})",
            "(Strategy: OpenCAMLib Drop-Cutter)",
            "G21 (metric)",
            "G90 (absolute)",
            f"S{inputs.spindle_speed} M3",
            f"G0 Z{inputs.safe_z}",
        ]

        toolpath_segments: list[dict[str, Any]] = []
        prev = [0.0, 0.0, inputs.safe_z]

        first = cl_points[0]
        first_p = [float(first.x), float(first.y), float(first.z)]
        toolpath_segments.append({"type": "G0", "from": list(prev), "to": [first_p[0], first_p[1], inputs.safe_z]})
        gcode_lines.append(f"G0 X{first_p[0]:.3f} Y{first_p[1]:.3f} Z{inputs.safe_z:.3f}")

        toolpath_segments.append({"type": "G1", "from": [first_p[0], first_p[1], inputs.safe_z], "to": first_p})
        gcode_lines.append(f"G1 Z{first_p[2]:.3f} F{inputs.feed_rate * 0.5:.0f}")
        prev = list(first_p)

        for p in cl_points[1:]:
            nxt = [float(p.x), float(p.y), float(p.z)]
            toolpath_segments.append({"type": "G1", "from": list(prev), "to": nxt})
            gcode_lines.append(f"G1 X{nxt[0]:.3f} Y{nxt[1]:.3f} Z{nxt[2]:.3f} F{inputs.feed_rate:.0f}")
            prev = nxt

        toolpath_segments.append({"type": "G0", "from": list(prev), "to": [prev[0], prev[1], inputs.safe_z]})
        gcode_lines.append(f"G0 Z{inputs.safe_z:.3f}")
        gcode_lines.extend(["G0 X0 Y0", "M5", "M30"])

        total_cut_len = _cutting_length(toolpath_segments)

        return {
            "gcode_lines": gcode_lines,
            "toolpath_segments": toolpath_segments,
            "estimated_time_minutes": round(total_cut_len / inputs.feed_rate, 1) if inputs.feed_rate > 0 else 0,
            "stats": {
                "layers": 1,
                "total_cut_length_mm": round(total_cut_len, 1),
                "strategy": "ocl_drop_cutter",
            },
        }
    except Exception:
        return _generate_planar_fallback(inputs, mesh, extents, strategy="fallback_ocl_runtime_error")


def _generate_planar_fallback(inputs: CamInputs, mesh: trimesh.Trimesh, extents: np.ndarray, strategy: str) -> dict[str, Any]:
    """Geometry-aware fallback that scans only rows intersecting the prepared mesh."""
    step_over = max(inputs.tool_diameter * inputs.step_over_ratio, 0.1)
    z_depth = float(extents[2])
    num_layers = max(1, math.ceil(z_depth / max(inputs.step_down, 0.1)))
    section_rows = _build_section_rows(mesh, float(extents[1]), step_over)

    if not section_rows:
        return _generate_bbox_fallback(inputs, extents, strategy=f"{strategy}_bbox")

    gcode_lines = [
        f"(Cloud CAM Generated for Job {inputs.job_id})",
        f"(Model: {float(extents[0]):.1f} x {float(extents[1]):.1f} x {z_depth:.1f} mm)",
        f"(Params: step_down={inputs.step_down} spindle={inputs.spindle_speed} feed={inputs.feed_rate})",
        f"(Strategy: {strategy})",
        "G21 (metric)",
        "G90 (absolute)",
        f"S{inputs.spindle_speed} M3",
        f"G0 Z{inputs.safe_z}",
    ]

    toolpath_segments: list[dict[str, Any]] = []
    prev = [0.0, 0.0, inputs.safe_z]

    for layer in range(num_layers):
        z = -min(inputs.step_down * (layer + 1), z_depth)

        forward = True
        first_y, first_x_min, first_x_max = section_rows[0]
        first_x = first_x_min if forward else first_x_max

        toolpath_segments.append({"type": "G0", "from": list(prev), "to": [first_x, first_y, inputs.safe_z]})
        gcode_lines.append(f"G0 X{first_x:.3f} Y{first_y:.3f} Z{inputs.safe_z:.3f}")
        prev = [first_x, first_y, inputs.safe_z]

        toolpath_segments.append({"type": "G0", "from": list(prev), "to": [first_x, first_y, z + 1.0]})
        gcode_lines.append(f"G0 Z{z + 1.0:.3f}")
        prev = [first_x, first_y, z + 1.0]

        toolpath_segments.append({"type": "G1", "from": list(prev), "to": [first_x, first_y, z]})
        gcode_lines.append(f"G1 Z{z:.3f} F{inputs.feed_rate * 0.5:.0f}")
        prev = [first_x, first_y, z]

        for y, x_min, x_max in section_rows:
            x_start, x_end = (x_min, x_max) if forward else (x_max, x_min)

            if abs(prev[0] - x_start) > 0.01 or abs(prev[1] - y) > 0.01:
                toolpath_segments.append({"type": "G1", "from": list(prev), "to": [x_start, y, z]})
                gcode_lines.append(f"G1 X{x_start:.3f} Y{y:.3f} F{inputs.feed_rate:.0f}")
                prev = [x_start, y, z]

            toolpath_segments.append({"type": "G1", "from": list(prev), "to": [x_end, y, z]})
            gcode_lines.append(f"G1 X{x_end:.3f} Y{y:.3f} F{inputs.feed_rate:.0f}")
            prev = [x_end, y, z]

            forward = not forward

        toolpath_segments.append({"type": "G0", "from": list(prev), "to": [prev[0], prev[1], inputs.safe_z]})
        gcode_lines.append(f"G0 Z{inputs.safe_z:.3f}")
        prev = [prev[0], prev[1], inputs.safe_z]

    toolpath_segments.append({"type": "G0", "from": list(prev), "to": [0.0, 0.0, inputs.safe_z]})
    gcode_lines.extend(["G0 X0 Y0", "M5", "M30"])

    total_cut_len = _cutting_length(toolpath_segments)

    return {
        "gcode_lines": gcode_lines,
        "toolpath_segments": toolpath_segments,
        "estimated_time_minutes": round(total_cut_len / inputs.feed_rate, 1) if inputs.feed_rate > 0 else 0,
        "stats": {
            "layers": num_layers,
            "total_cut_length_mm": round(total_cut_len, 1),
            "strategy": strategy,
        },
    }


def _build_section_rows(mesh: trimesh.Trimesh, y_extent: float, step_over: float) -> list[tuple[float, float, float]]:
    rows: list[tuple[float, float, float]] = []
    y = 0.0
    while y <= y_extent + 1e-6:
        segments = trimesh.intersections.mesh_plane(
            mesh,
            plane_normal=np.array([0.0, 1.0, 0.0], dtype=float),
            plane_origin=np.array([0.0, y, 0.0], dtype=float),
        )
        if len(segments) > 0:
            xs = np.asarray(segments)[:, :, 0].reshape(-1)
            x_min = float(xs.min())
            x_max = float(xs.max())
            if x_max - x_min > 0.05:
                rows.append((float(y), x_min, x_max))
        y += step_over

    if rows and rows[-1][0] < y_extent - 1e-6:
        rows.append((y_extent, rows[-1][1], rows[-1][2]))

    return rows


def _generate_bbox_fallback(inputs: CamInputs, extents: np.ndarray, strategy: str) -> dict[str, Any]:
    step_over = max(inputs.tool_diameter * inputs.step_over_ratio, 0.1)
    z_depth = float(extents[2])
    num_layers = max(1, math.ceil(z_depth / max(inputs.step_down, 0.1)))

    gcode_lines = [
        f"(Cloud CAM Generated for Job {inputs.job_id})",
        f"(Model: {float(extents[0]):.1f} x {float(extents[1]):.1f} x {z_depth:.1f} mm)",
        f"(Params: step_down={inputs.step_down} spindle={inputs.spindle_speed} feed={inputs.feed_rate})",
        f"(Strategy: {strategy})",
        "G21 (metric)",
        "G90 (absolute)",
        f"S{inputs.spindle_speed} M3",
        f"G0 Z{inputs.safe_z}",
    ]

    toolpath_segments: list[dict[str, Any]] = []
    prev = [0.0, 0.0, inputs.safe_z]

    for layer in range(num_layers):
        z = -min(inputs.step_down * (layer + 1), z_depth)

        toolpath_segments.append({"type": "G0", "from": list(prev), "to": [0.0, 0.0, inputs.safe_z]})
        gcode_lines.append(f"G0 X0 Y0 Z{inputs.safe_z:.3f}")
        prev = [0.0, 0.0, inputs.safe_z]

        toolpath_segments.append({"type": "G0", "from": list(prev), "to": [0.0, 0.0, z + 1.0]})
        gcode_lines.append(f"G0 Z{z + 1.0:.3f}")
        prev = [0.0, 0.0, z + 1.0]

        toolpath_segments.append({"type": "G1", "from": list(prev), "to": [0.0, 0.0, z]})
        gcode_lines.append(f"G1 Z{z:.3f} F{inputs.feed_rate * 0.5:.0f}")
        prev = [0.0, 0.0, z]

        y = 0.0
        forward = True
        while y <= float(extents[1]) + 1e-6:
            x_end = float(extents[0]) if forward else 0.0

            if abs(prev[1] - y) > 0.01:
                toolpath_segments.append({"type": "G1", "from": list(prev), "to": [prev[0], y, z]})
                gcode_lines.append(f"G1 Y{y:.3f} F{inputs.feed_rate:.0f}")
                prev = [prev[0], y, z]

            toolpath_segments.append({"type": "G1", "from": list(prev), "to": [x_end, y, z]})
            gcode_lines.append(f"G1 X{x_end:.3f} Y{y:.3f} F{inputs.feed_rate:.0f}")
            prev = [x_end, y, z]

            y += step_over
            forward = not forward

        toolpath_segments.append({"type": "G0", "from": list(prev), "to": [prev[0], prev[1], inputs.safe_z]})
        gcode_lines.append(f"G0 Z{inputs.safe_z:.3f}")
        prev = [prev[0], prev[1], inputs.safe_z]

    toolpath_segments.append({"type": "G0", "from": list(prev), "to": [0.0, 0.0, inputs.safe_z]})
    gcode_lines.extend(["G0 X0 Y0", "M5", "M30"])

    total_cut_len = _cutting_length(toolpath_segments)

    return {
        "gcode_lines": gcode_lines,
        "toolpath_segments": toolpath_segments,
        "estimated_time_minutes": round(total_cut_len / inputs.feed_rate, 1) if inputs.feed_rate > 0 else 0,
        "stats": {
            "layers": num_layers,
            "total_cut_length_mm": round(total_cut_len, 1),
            "strategy": strategy,
        },
    }


def _cutting_length(toolpath_segments: list[dict[str, Any]]) -> float:
    return sum(
        math.sqrt(sum((b - a) ** 2 for a, b in zip(seg["from"], seg["to"])))
        for seg in toolpath_segments
        if seg["type"] == "G1"
    )
