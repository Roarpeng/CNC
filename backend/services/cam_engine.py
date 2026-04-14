from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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


def generate_cam_with_ocl(inputs: CamInputs) -> dict[str, Any]:
    """
    Preferred pipeline: OpenCAMLib drop-cutter.
    If runtime binding is unavailable, falls back to a deterministic planar roughing path
    while keeping the same API contract.
    """
    try:
        if _has_ocl_runtime():
            return _generate_dropcutter_toolpath(inputs)
        return _generate_planar_fallback(inputs, strategy="fallback_no_ocl")
    except Exception as exc:
        raise CamEngineError(f"CAM 生成失败: {exc}") from exc


def _has_ocl_runtime() -> bool:
    try:
        import ocl  # type: ignore

        return ocl is not None
    except Exception:
        return False


def _generate_dropcutter_toolpath(inputs: CamInputs) -> dict[str, Any]:
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
            return _generate_planar_fallback(inputs, strategy="fallback_ocl_symbols_missing")

        mesh = trimesh.load_mesh(str(inputs.mesh_path), force="mesh")
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
                return _generate_planar_fallback(inputs, strategy="fallback_ocl_triangle_missing")

        drop = ocl.DropCutter()
        drop.setSTL(surf)
        cutter_radius = max(inputs.tool_diameter * 0.5, 0.1)
        cutter = ocl.BallCutter(float(cutter_radius), float(inputs.tool_diameter * 4.0))
        drop.setCutter(cutter)

        step_over = max(inputs.tool_diameter * inputs.step_over_ratio, 0.1)
        y = 0.0
        forward = True
        while y <= inputs.bbox_y + 1e-6:
            x_from = 0.0 if forward else inputs.bbox_x
            x_to = inputs.bbox_x if forward else 0.0
            drop.appendPoint(ocl.CLPoint(float(x_from), float(y), float(inputs.safe_z)))
            drop.appendPoint(ocl.CLPoint(float(x_to), float(y), float(inputs.safe_z)))
            y += step_over
            forward = not forward

        drop.run()
        cl_points = list(drop.getCLPoints())
        if len(cl_points) < 2:
            return _generate_planar_fallback(inputs, strategy="fallback_ocl_empty")

        gcode_lines = [
            f"(Cloud CAM OCL Generated for Job {inputs.job_id})",
            f"(Model: {inputs.bbox_x:.1f} x {inputs.bbox_y:.1f} x {inputs.z_depth:.1f} mm)",
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
        return _generate_planar_fallback(inputs, strategy="fallback_ocl_runtime_error")


def _generate_planar_fallback(inputs: CamInputs, strategy: str) -> dict[str, Any]:
    """Compatibility fallback that preserves the existing API contract."""
    step_over = max(inputs.tool_diameter * inputs.step_over_ratio, 0.1)
    num_layers = max(1, math.ceil(inputs.z_depth / max(inputs.step_down, 0.1)))

    gcode_lines = [
        f"(Cloud CAM Generated for Job {inputs.job_id})",
        f"(Model: {inputs.bbox_x:.1f} x {inputs.bbox_y:.1f} x {inputs.z_depth:.1f} mm)",
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
        z = -min(inputs.step_down * (layer + 1), inputs.z_depth)

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
        while y <= inputs.bbox_y + 1e-6:
            x_end = inputs.bbox_x if forward else 0.0

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
