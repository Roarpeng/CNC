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


@dataclass
class WorkEnvelope:
    x_min: float
    x_max: float
    y_min: float
    y_max: float
    z_min: float
    z_max: float


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
        envelope = _resolve_work_envelope(mesh, inputs)
        safe_z_abs = envelope.z_max + abs(inputs.safe_z)
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
        y = envelope.y_min
        forward = True
        while y <= envelope.y_max + 1e-6:
            x_from = envelope.x_min if forward else envelope.x_max
            x_to = envelope.x_max if forward else envelope.x_min
            drop.appendPoint(ocl.CLPoint(float(x_from), float(y), float(safe_z_abs)))
            drop.appendPoint(ocl.CLPoint(float(x_to), float(y), float(safe_z_abs)))
            y += step_over
            forward = not forward

        drop.run()
        cl_points = list(drop.getCLPoints())
        if len(cl_points) < 2:
            return _generate_planar_fallback(inputs, strategy="fallback_ocl_empty")

        gcode_lines = [
            f"(Cloud CAM OCL Generated for Job {inputs.job_id})",
            f"(Model: {envelope.x_max - envelope.x_min:.1f} x {envelope.y_max - envelope.y_min:.1f} x {envelope.z_max - envelope.z_min:.1f} mm)",
            f"(Params: step_down={inputs.step_down} spindle={inputs.spindle_speed} feed={inputs.feed_rate})",
            "(Strategy: OpenCAMLib Drop-Cutter)",
            "G21 (metric)",
            "G90 (absolute)",
            f"S{inputs.spindle_speed} M3",
            f"G0 Z{safe_z_abs:.3f}",
        ]

        toolpath_segments: list[dict[str, Any]] = []
        prev = [envelope.x_min, envelope.y_min, safe_z_abs]

        first = cl_points[0]
        first_p = [float(first.x), float(first.y), float(first.z)]
        toolpath_segments.append({"type": "G0", "from": list(prev), "to": [first_p[0], first_p[1], safe_z_abs]})
        gcode_lines.append(f"G0 X{first_p[0]:.3f} Y{first_p[1]:.3f} Z{safe_z_abs:.3f}")

        toolpath_segments.append({"type": "G1", "from": [first_p[0], first_p[1], safe_z_abs], "to": first_p})
        gcode_lines.append(f"G1 Z{first_p[2]:.3f} F{inputs.feed_rate * 0.5:.0f}")
        prev = list(first_p)

        for p in cl_points[1:]:
            nxt = [float(p.x), float(p.y), float(p.z)]
            toolpath_segments.append({"type": "G1", "from": list(prev), "to": nxt})
            gcode_lines.append(f"G1 X{nxt[0]:.3f} Y{nxt[1]:.3f} Z{nxt[2]:.3f} F{inputs.feed_rate:.0f}")
            prev = nxt

        toolpath_segments.append({"type": "G0", "from": list(prev), "to": [prev[0], prev[1], safe_z_abs]})
        gcode_lines.append(f"G0 Z{safe_z_abs:.3f}")
        gcode_lines.extend([f"G0 X{envelope.x_min:.3f} Y{envelope.y_min:.3f}", "M5", "M30"])

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
    mesh = trimesh.load_mesh(str(inputs.mesh_path), force="mesh")
    envelope = _resolve_work_envelope(mesh, inputs)

    step_over = max(inputs.tool_diameter * inputs.step_over_ratio, 0.1)
    z_span = max(envelope.z_max - envelope.z_min, 0.1)
    num_layers = max(1, math.ceil(z_span / max(inputs.step_down, 0.1)))
    safe_z_abs = envelope.z_max + abs(inputs.safe_z)

    gcode_lines = [
        f"(Cloud CAM Generated for Job {inputs.job_id})",
        f"(Model: {envelope.x_max - envelope.x_min:.1f} x {envelope.y_max - envelope.y_min:.1f} x {envelope.z_max - envelope.z_min:.1f} mm)",
        f"(Params: step_down={inputs.step_down} spindle={inputs.spindle_speed} feed={inputs.feed_rate})",
        f"(Strategy: {strategy})",
        "G21 (metric)",
        "G90 (absolute)",
        f"S{inputs.spindle_speed} M3",
        f"G0 Z{safe_z_abs:.3f}",
    ]

    toolpath_segments: list[dict[str, Any]] = []
    prev = [envelope.x_min, envelope.y_min, safe_z_abs]

    for layer in range(num_layers):
        z = max(envelope.z_max - inputs.step_down * (layer + 1), envelope.z_min)
        plunge_start = min(z + 1.0, safe_z_abs)

        toolpath_segments.append({"type": "G0", "from": list(prev), "to": [envelope.x_min, envelope.y_min, safe_z_abs]})
        gcode_lines.append(f"G0 X{envelope.x_min:.3f} Y{envelope.y_min:.3f} Z{safe_z_abs:.3f}")
        prev = [envelope.x_min, envelope.y_min, safe_z_abs]

        toolpath_segments.append({"type": "G0", "from": list(prev), "to": [envelope.x_min, envelope.y_min, plunge_start]})
        gcode_lines.append(f"G0 Z{plunge_start:.3f}")
        prev = [envelope.x_min, envelope.y_min, plunge_start]

        toolpath_segments.append({"type": "G1", "from": list(prev), "to": [envelope.x_min, envelope.y_min, z]})
        gcode_lines.append(f"G1 Z{z:.3f} F{inputs.feed_rate * 0.5:.0f}")
        prev = [envelope.x_min, envelope.y_min, z]

        y = envelope.y_min
        forward = True
        while y <= envelope.y_max + 1e-6:
            x_end = envelope.x_max if forward else envelope.x_min

            if abs(prev[1] - y) > 0.01:
                toolpath_segments.append({"type": "G1", "from": list(prev), "to": [prev[0], y, z]})
                gcode_lines.append(f"G1 Y{y:.3f} F{inputs.feed_rate:.0f}")
                prev = [prev[0], y, z]

            toolpath_segments.append({"type": "G1", "from": list(prev), "to": [x_end, y, z]})
            gcode_lines.append(f"G1 X{x_end:.3f} Y{y:.3f} F{inputs.feed_rate:.0f}")
            prev = [x_end, y, z]

            y += step_over
            forward = not forward

        toolpath_segments.append({"type": "G0", "from": list(prev), "to": [prev[0], prev[1], safe_z_abs]})
        gcode_lines.append(f"G0 Z{safe_z_abs:.3f}")
        prev = [prev[0], prev[1], safe_z_abs]

    toolpath_segments.append({"type": "G0", "from": list(prev), "to": [envelope.x_min, envelope.y_min, safe_z_abs]})
    gcode_lines.extend([f"G0 X{envelope.x_min:.3f} Y{envelope.y_min:.3f}", "M5", "M30"])

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


def _resolve_work_envelope(mesh: trimesh.Trimesh, inputs: CamInputs) -> WorkEnvelope:
    try:
        bounds = mesh.bounds
        if bounds is not None and len(bounds) == 2:
            mins = bounds[0]
            maxs = bounds[1]
            x_min, x_max = sorted((float(mins[0]), float(maxs[0])))
            y_min, y_max = sorted((float(mins[1]), float(maxs[1])))
            z_min, z_max = sorted((float(mins[2]), float(maxs[2])))
            if (x_max - x_min) > 1e-6 and (y_max - y_min) > 1e-6 and (z_max - z_min) > 1e-6:
                return WorkEnvelope(
                    x_min=x_min,
                    x_max=x_max,
                    y_min=y_min,
                    y_max=y_max,
                    z_min=z_min,
                    z_max=z_max,
                )
    except Exception:
        pass

    return WorkEnvelope(
        x_min=0.0,
        x_max=max(inputs.bbox_x, 0.1),
        y_min=0.0,
        y_max=max(inputs.bbox_y, 0.1),
        z_min=0.0,
        z_max=max(inputs.z_depth, 0.1),
    )
