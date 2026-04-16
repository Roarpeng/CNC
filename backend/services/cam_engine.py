from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import trimesh
from shapely import affinity as shapely_affinity
from shapely.geometry import GeometryCollection, LineString, MultiLineString, box
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union


SAFE_Z_CLEARANCE = 10.0
AREA_EPS = 1e-3
SEGMENT_EPS = 1e-3
STOCK_MARGIN = 3.0
ARC_TESSELLATION_STEPS = 24
HELIX_STEP_DOWN_PER_REV = 1.0
BOTTOM_CLEARANCE = 0.2

TOOL_LIBRARY: list[dict[str, Any]] = [
    {"id": 1, "diameter": 2.0, "name": "D2 平底铣刀", "type": "flat_endmill", "flutes": 2},
    {"id": 2, "diameter": 3.0, "name": "D3 平底铣刀", "type": "flat_endmill", "flutes": 2},
    {"id": 3, "diameter": 4.0, "name": "D4 平底铣刀", "type": "flat_endmill", "flutes": 3},
    {"id": 4, "diameter": 5.0, "name": "D5 平底铣刀", "type": "flat_endmill", "flutes": 3},
    {"id": 5, "diameter": 6.0, "name": "D6 平底铣刀", "type": "flat_endmill", "flutes": 4},
    {"id": 6, "diameter": 8.0, "name": "D8 平底铣刀", "type": "flat_endmill", "flutes": 4},
]


def get_tool_library() -> list[dict[str, Any]]:
    return [t.copy() for t in TOOL_LIBRARY]


def _find_tool_by_max_diameter(max_d: float) -> dict[str, Any] | None:
    candidates = [t for t in TOOL_LIBRARY if t["diameter"] <= max_d]
    return candidates[-1].copy() if candidates else None


def select_tools_for_features(
    manufacturing_features: list[dict[str, Any]],
    part_dims: dict[str, float] | None = None,
) -> dict[str, Any]:
    min_part_dim = 999.0
    if part_dims:
        min_part_dim = min(part_dims.get("bbox_x", 999), part_dims.get("bbox_y", 999))

    roughing_max_d = min(8.0, min_part_dim * 0.5)
    roughing_tool = _find_tool_by_max_diameter(roughing_max_d) or TOOL_LIBRARY[0].copy()

    feature_tools: list[dict[str, Any]] = []
    for feat in manufacturing_features:
        ftype = feat.get("type", "")
        tool: dict[str, Any] | None = None
        reason = ""

        if ftype == "hole":
            diameter = feat.get("diameter", 0.0)
            max_d = diameter * 0.8
            tool = _find_tool_by_max_diameter(max_d)
            if tool:
                reason = f"孔径 {diameter:.1f}mm → 选 D{tool['diameter']:.0f} 钻铣"
            else:
                reason = f"孔径 {diameter:.1f}mm 过小，无匹配刀具"
        elif ftype == "pocket":
            bounds = feat.get("bounds", {})
            min_dim = min(bounds.get("x", 999.0), bounds.get("y", 999.0))
            max_d = min_dim * 0.6
            tool = _find_tool_by_max_diameter(max_d)
            if tool:
                reason = f"型腔最窄边 {min_dim:.1f}mm → 选 D{tool['diameter']:.0f} 清角"
            else:
                reason = f"型腔最窄边 {min_dim:.1f}mm 过窄，无匹配刀具"
        elif ftype == "boss":
            tool = roughing_tool.copy()
            reason = f"凸台外形由粗加工覆盖 → 沿用 D{tool['diameter']:.0f}"

        feature_tools.append({
            "feature_type": ftype,
            "feature_face_id": feat.get("face_id"),
            "diameter": feat.get("diameter"),
            "depth": feat.get("depth"),
            "bounds": feat.get("bounds"),
            "tool": tool,
            "reason": reason,
        })

    return {
        "roughing_tool": roughing_tool,
        "feature_tools": feature_tools,
    }


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
    safe_z: float = SAFE_Z_CLEARANCE
    setup_normal: tuple[float, float, float] | None = None
    manufacturing_features: list[dict[str, Any]] = field(default_factory=list)
    tool_plan: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def generate_cam_with_ocl(inputs: CamInputs) -> dict[str, Any]:
    """Multi-phase CAM pipeline:
    1. Stock-aware roughing (G0/G1)
    2. Feature-based finishing — Z-axis holes (G2/G3 helical), pockets (G2/G3 contour)

    Toolpath segment coordinates are returned in the original model coordinate
    space so the frontend can overlay them directly on the un-rotated mesh.
    """
    try:
        mesh, inverse_transform = _load_prepared_mesh(inputs)
        part_bounds = mesh.bounds
        part_top_z = float(part_bounds[1][2])

        dynamic_safe_z = SAFE_Z_CLEARANCE
        inputs = CamInputs(
            job_id=inputs.job_id,
            mesh_path=inputs.mesh_path,
            bbox_x=inputs.bbox_x,
            bbox_y=inputs.bbox_y,
            z_depth=inputs.z_depth,
            step_down=inputs.step_down,
            spindle_speed=inputs.spindle_speed,
            feed_rate=inputs.feed_rate,
            tool_diameter=inputs.tool_diameter,
            step_over_ratio=inputs.step_over_ratio,
            safe_z=dynamic_safe_z,
            setup_normal=inputs.setup_normal,
            manufacturing_features=inputs.manufacturing_features,
            tool_plan=inputs.tool_plan,
        )

        if _has_ocl_runtime():
            result = _generate_dropcutter_toolpath(inputs, mesh, part_bounds)
        else:
            result = _generate_planar_fallback(inputs, mesh, part_bounds, strategy="stock_aware_fallback")

        forward_transform = np.linalg.inv(inverse_transform)
        feature_result = _generate_feature_toolpaths(inputs, part_bounds, forward_transform)
        if feature_result["toolpath_segments"]:
            result["gcode_lines"].extend(feature_result["gcode_lines"])
            result["toolpath_segments"].extend(feature_result["toolpath_segments"])
            result["stats"]["feature_ops"] = feature_result["stats"]
            cut_extra = _cutting_length(feature_result["toolpath_segments"])
            result["stats"]["total_cut_length_mm"] = round(
                result["stats"]["total_cut_length_mm"] + cut_extra, 1
            )
            if inputs.feed_rate > 0:
                result["estimated_time_minutes"] = round(
                    result["stats"]["total_cut_length_mm"] / inputs.feed_rate, 1
                )

        _segments_machine_z_to_prepared(result["toolpath_segments"], part_top_z)
        _transform_segments_to_model_space(result["toolpath_segments"], inverse_transform)
        return result
    except Exception as exc:
        raise CamEngineError(f"CAM 生成失败: {exc}") from exc


# ---------------------------------------------------------------------------
# Mesh preparation
# ---------------------------------------------------------------------------

def _load_prepared_mesh(inputs: CamInputs) -> tuple[trimesh.Trimesh, np.ndarray]:
    """Load mesh, apply setup rotation + origin translation; return (prepared, inverse_4x4)."""
    mesh = trimesh.load_mesh(str(inputs.mesh_path), force="mesh")
    if isinstance(mesh, trimesh.Scene):
        mesh = mesh.dump(concatenate=True)
    if not isinstance(mesh, trimesh.Trimesh):
        raise CamEngineError("无法加载有效的三角网格")

    prepared = mesh.copy()
    forward = np.eye(4, dtype=float)

    if inputs.setup_normal is not None:
        rot = _rotation_matrix_from_vectors(
            np.asarray(inputs.setup_normal, dtype=float),
            np.array([0.0, 0.0, -1.0], dtype=float),
        )
        prepared.apply_transform(rot)
        forward = rot @ forward

    translation = -prepared.bounds[0].copy()
    prepared.apply_translation(translation)
    t_mat = np.eye(4, dtype=float)
    t_mat[:3, 3] = translation
    forward = t_mat @ forward

    inverse = np.linalg.inv(forward)
    return prepared, inverse


# ---------------------------------------------------------------------------
# Coordinate transforms
# ---------------------------------------------------------------------------

def _segments_machine_z_to_prepared(
    segments: list[dict[str, Any]],
    part_top_z: float,
) -> None:
    """Toolpath Z values use G-code convention (Z=0 at part top, negative downward).
    Convert them to prepared-mesh frame (absolute Z) so the inverse transform works correctly."""
    for seg in segments:
        for key in ("from", "to"):
            seg[key][2] += part_top_z
        if "center" in seg and seg["center"] is not None and len(seg["center"]) >= 3:
            seg["center"][2] += part_top_z


def _transform_segments_to_model_space(
    segments: list[dict[str, Any]],
    inverse: np.ndarray,
) -> None:
    """In-place transform of toolpath segment coordinates back to original model space."""
    rot = inverse[:3, :3]
    trans = inverse[:3, 3]
    for seg in segments:
        for key in ("from", "to"):
            pt = np.asarray(seg[key], dtype=float)
            transformed = rot @ pt + trans
            seg[key] = [round(float(transformed[0]), 6), round(float(transformed[1]), 6), round(float(transformed[2]), 6)]
        if "center" in seg and seg["center"] is not None and len(seg["center"]) >= 3:
            pt = np.asarray(seg["center"], dtype=float)
            transformed = rot @ pt + trans
            seg["center"] = [round(float(transformed[0]), 6), round(float(transformed[1]), 6), round(float(transformed[2]), 6)]


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


# ---------------------------------------------------------------------------
# G-code helpers
# ---------------------------------------------------------------------------

def _gcode_header(inputs: CamInputs, extents: np.ndarray) -> list[str]:
    return [
        f"(Cloud CAM Generated for Job {inputs.job_id})",
        f"(Model: {float(extents[0]):.1f} x {float(extents[1]):.1f} x {float(extents[2]):.1f} mm)",
        f"(Params: step_down={inputs.step_down} spindle={inputs.spindle_speed} feed={inputs.feed_rate})",
        "G17 (XY plane selection)",
        "G21 (metric)",
        "G90 (absolute positioning)",
        "G40 (cancel cutter radius compensation)",
        "G49 (cancel tool length offset)",
    ]


def _gcode_tool_start(tool: dict[str, Any], spindle_speed: int, label: str = "") -> list[str]:
    tid = tool.get("id", 1)
    name = tool.get("name", f"D{tool.get('diameter', 0)}")
    lines = [
        f"(--- Tool T{tid}: {name}{', ' + label if label else ''} ---)",
        f"T{tid} M6",
        f"S{spindle_speed} M3",
        "G4 P1 (dwell 1s for spindle ramp-up)",
    ]
    return lines


def _gcode_footer(safe_z: float) -> list[str]:
    return [
        f"G0 Z{safe_z:.3f} (retract)",
        "G28 G91 Z0 (return Z home)",
        "G28 G91 X0 Y0 (return XY home)",
        "G90 (restore absolute)",
        "M5 (spindle stop)",
        "M9 (coolant off)",
        "M30 (program end)",
    ]


# ---------------------------------------------------------------------------
# Phase 1: Stock-aware roughing
# ---------------------------------------------------------------------------

def _generate_dropcutter_toolpath(inputs: CamInputs, mesh: trimesh.Trimesh, part_bounds: np.ndarray) -> dict[str, Any]:
    return _generate_planar_fallback(inputs, mesh, part_bounds, strategy="stock_aware_roughing")


def _generate_planar_fallback(inputs: CamInputs, mesh: trimesh.Trimesh, part_bounds: np.ndarray, strategy: str) -> dict[str, Any]:
    """Generate stock-aware raster roughing that removes only stock-minus-part regions."""
    step_over = max(inputs.tool_diameter * inputs.step_over_ratio, 0.1)
    step_down = max(inputs.step_down, 0.1)
    tool_radius = max(inputs.tool_diameter * 0.5, 0.1)
    extents = part_bounds[1] - part_bounds[0]
    stock_bounds = _compute_stock(part_bounds)
    stock_height = float(stock_bounds[1][2] - stock_bounds[0][2])
    num_layers = max(1, math.ceil(stock_height / step_down))

    roughing_tool = (inputs.tool_plan or {}).get("roughing_tool") or {
        "id": 1, "diameter": inputs.tool_diameter, "name": f"D{inputs.tool_diameter:.0f}"
    }

    gcode_lines = _gcode_header(inputs, extents)
    gcode_lines.append(f"(Strategy: {strategy})")
    gcode_lines.extend(_gcode_tool_start(roughing_tool, inputs.spindle_speed, "Roughing"))
    gcode_lines.append(f"G0 Z{inputs.safe_z:.3f}")

    toolpath_segments: list[dict[str, Any]] = []
    prev = [0.0, 0.0, inputs.safe_z]
    machined_layers = 0

    stock_top_z = float(stock_bounds[1][2])
    stock_bot_z = float(stock_bounds[0][2]) + BOTTOM_CLEARANCE
    part_top_z = float(part_bounds[1][2])

    cumulative_section: BaseGeometry = GeometryCollection()

    for layer in range(num_layers):
        cut_plane_z = max(stock_top_z - step_down * (layer + 1), stock_bot_z)
        cut_depth = cut_plane_z - part_top_z
        current_section = _extract_section_geometry(mesh, cut_plane_z)
        if not current_section.is_empty:
            if cumulative_section.is_empty:
                cumulative_section = current_section
            else:
                cumulative_section = unary_union([cumulative_section, current_section])
        removal_geometry = _compute_removal_regions(
            mesh, stock_bounds, cut_plane_z, tool_radius,
            part_section_override=cumulative_section if not cumulative_section.is_empty else None,
        )
        if removal_geometry.is_empty:
            continue

        scan_segments = _build_layer_scan_segments(removal_geometry, step_over)
        if not scan_segments:
            continue

        machined_layers += 1
        for start, end in scan_segments:
            toolpath_segments.append({"type": "G0", "from": list(prev), "to": [start[0], start[1], inputs.safe_z]})
            gcode_lines.append(f"G0 X{start[0]:.3f} Y{start[1]:.3f} Z{inputs.safe_z:.3f}")
            prev = [start[0], start[1], inputs.safe_z]

            toolpath_segments.append({"type": "G1", "from": list(prev), "to": [start[0], start[1], cut_depth]})
            gcode_lines.append(f"G1 Z{cut_depth:.3f} F{inputs.feed_rate * 0.5:.0f}")
            prev = [start[0], start[1], cut_depth]

            toolpath_segments.append({"type": "G1", "from": list(prev), "to": [end[0], end[1], cut_depth]})
            gcode_lines.append(f"G1 X{end[0]:.3f} Y{end[1]:.3f} F{inputs.feed_rate:.0f}")
            prev = [end[0], end[1], cut_depth]

            toolpath_segments.append({"type": "G0", "from": list(prev), "to": [end[0], end[1], inputs.safe_z]})
            gcode_lines.append(f"G0 Z{inputs.safe_z:.3f}")
            prev = [end[0], end[1], inputs.safe_z]

    if not toolpath_segments:
        return _generate_bbox_fallback(inputs, stock_bounds, strategy=f"{strategy}_bbox")

    gcode_lines.append("M5 (spindle stop after roughing)")

    toolpath_segments.append({"type": "G0", "from": list(prev), "to": [0.0, 0.0, inputs.safe_z]})
    gcode_lines.append(f"G0 X0 Y0 Z{inputs.safe_z:.3f}")

    total_cut_len = _cutting_length(toolpath_segments)

    return {
        "gcode_lines": gcode_lines,
        "toolpath_segments": toolpath_segments,
        "estimated_time_minutes": round(total_cut_len / inputs.feed_rate, 1) if inputs.feed_rate > 0 else 0,
        "stats": {
            "layers": machined_layers,
            "total_cut_length_mm": round(total_cut_len, 1),
            "strategy": strategy,
            "stock": {
                "x": round(float(stock_bounds[1][0] - stock_bounds[0][0]), 3),
                "y": round(float(stock_bounds[1][1] - stock_bounds[0][1]), 3),
                "z": round(float(stock_bounds[1][2] - stock_bounds[0][2]), 3),
            },
        },
    }


# ---------------------------------------------------------------------------
# Phase 2 & 3: Feature-based toolpaths (holes, pockets)
# ---------------------------------------------------------------------------

def _generate_feature_toolpaths(
    inputs: CamInputs,
    part_bounds: np.ndarray,
    forward_transform: np.ndarray,
) -> dict[str, Any]:
    """Generate G2/G3 toolpaths for recognized manufacturing features.
    Feature center coordinates arrive in model space — they must be transformed
    to prepared-mesh space via *forward_transform* so that the downstream
    _segments_machine_z_to_prepared + _transform_segments_to_model_space
    pipeline can convert them back correctly (same as roughing segments)."""
    features = inputs.manufacturing_features
    tool_plan = inputs.tool_plan
    if not features or not tool_plan:
        return {"gcode_lines": [], "toolpath_segments": [], "stats": {}}

    feature_tools = tool_plan.get("feature_tools", [])
    part_top_z = float(part_bounds[1][2])

    tool_groups: dict[int, list[tuple[dict[str, Any], dict[str, Any]]]] = {}
    for feat, ft_entry in zip(features, feature_tools):
        tool = ft_entry.get("tool")
        if tool is None:
            continue
        tid = tool["id"]
        tool_groups.setdefault(tid, []).append((feat, ft_entry))

    all_gcode: list[str] = []
    all_segments: list[dict[str, Any]] = []
    stats: dict[str, Any] = {"holes_machined": 0, "pockets_machined": 0, "skipped_non_z_holes": 0}

    for tid, group in sorted(tool_groups.items()):
        tool = group[0][1]["tool"]
        tool_radius = tool["diameter"] / 2.0
        spindle_speed = _adjusted_spindle(inputs.spindle_speed, tool["diameter"], inputs.tool_diameter)
        feed = _adjusted_feed(inputs.feed_rate, tool["diameter"], inputs.tool_diameter)

        tool_segs: list[dict[str, Any]] = []
        tool_gcode: list[str] = []

        for feat, ft_entry in group:
            ftype = feat.get("type", "")
            prepared_feat = _transform_feature_to_prepared(feat, forward_transform, part_top_z)
            if ftype == "hole":
                if feat.get("axis") != "z":
                    stats["skipped_non_z_holes"] += 1
                    continue
                h_segs, h_gcode = _generate_hole_helical_toolpath(
                    prepared_feat, tool_radius, feed, inputs.safe_z, part_top_z,
                )
                tool_segs.extend(h_segs)
                tool_gcode.extend(h_gcode)
                stats["holes_machined"] += 1
            elif ftype == "pocket":
                p_segs, p_gcode = _generate_pocket_contour_toolpath(
                    prepared_feat, tool_radius, feed, inputs.safe_z, part_top_z, inputs.step_down,
                )
                tool_segs.extend(p_segs)
                tool_gcode.extend(p_gcode)
                stats["pockets_machined"] += 1

        if tool_segs:
            all_gcode.extend(_gcode_tool_start(tool, spindle_speed, ft_entry.get("reason", "")))
            all_gcode.append(f"G0 Z{inputs.safe_z:.3f}")
            all_gcode.extend(tool_gcode)
            all_gcode.append("M5 (spindle stop)")
            all_segments.extend(tool_segs)

    if all_gcode:
        all_gcode.extend(_gcode_footer(inputs.safe_z))

    return {"gcode_lines": all_gcode, "toolpath_segments": all_segments, "stats": stats}


def _transform_feature_to_prepared(
    feat: dict[str, Any],
    forward_transform: np.ndarray,
    part_top_z: float,
) -> dict[str, Any]:
    """Transform a feature's center from model space to prepared-mesh space,
    and convert Z to machine coordinates (Z=0 at part top)."""
    prepared = dict(feat)
    center = feat.get("center")
    if center is None:
        return prepared

    pt_model = np.array([
        float(center.get("x", 0)),
        float(center.get("y", 0)),
        float(center.get("z", 0)),
        1.0,
    ], dtype=float)
    pt_prepared = forward_transform @ pt_model

    prepared["center"] = {
        "x": float(pt_prepared[0]),
        "y": float(pt_prepared[1]),
        "z": float(pt_prepared[2]),
    }
    return prepared


def _adjusted_spindle(base_rpm: int, tool_d: float, ref_d: float) -> int:
    """Smaller tools need higher RPM to maintain surface speed."""
    if tool_d <= 0 or ref_d <= 0:
        return base_rpm
    ratio = ref_d / tool_d
    return min(int(base_rpm * ratio), 24000)


def _adjusted_feed(base_feed: float, tool_d: float, ref_d: float) -> float:
    """Smaller tools need proportionally lower feed."""
    if tool_d <= 0 or ref_d <= 0:
        return base_feed
    ratio = tool_d / ref_d
    return round(base_feed * ratio, 0)


def _generate_hole_helical_toolpath(
    feat: dict[str, Any],
    tool_radius: float,
    feed: float,
    safe_z: float,
    part_top_z: float,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Generate helical milling toolpath for a Z-axis hole using G2 arcs."""
    cx = float(feat["center"]["x"])
    cy = float(feat["center"]["y"])
    hole_radius = float(feat.get("diameter", 0)) / 2.0
    depth = min(float(feat.get("depth", 0)), part_top_z)

    helix_radius = hole_radius - tool_radius
    if helix_radius < 0.05:
        return [], []

    z_start = 0.0
    z_end = -depth
    plunge_feed = feed * 0.3
    step_per_rev = min(HELIX_STEP_DOWN_PER_REV, depth)

    segments: list[dict[str, Any]] = []
    gcode: list[str] = []

    start_x = cx + helix_radius
    start_y = cy

    gcode.append(f"(Hole D{hole_radius * 2:.1f} at X{cx:.1f} Y{cy:.1f})")
    segments.append({"type": "G0", "from": [0.0, 0.0, safe_z], "to": [start_x, start_y, safe_z]})
    gcode.append(f"G0 X{start_x:.3f} Y{start_y:.3f} Z{safe_z:.3f}")

    segments.append({"type": "G0", "from": [start_x, start_y, safe_z], "to": [start_x, start_y, z_start]})
    gcode.append(f"G0 Z{z_start:.3f}")

    current_z = z_start
    i_off = cx - start_x
    j_off = cy - start_y

    while current_z > z_end + 1e-6:
        next_z = max(current_z - step_per_rev, z_end)

        z_mid = (current_z + next_z) / 2.0
        from_pt = [start_x, start_y, current_z]
        mid_pt = [cx - helix_radius, cy, z_mid]
        to_pt = [start_x, start_y, next_z]

        segments.append({
            "type": "G2", "from": from_pt, "to": list(mid_pt),
            "center": [cx, cy, z_mid], "radius": helix_radius,
        })
        gcode.append(f"G2 X{mid_pt[0]:.3f} Y{mid_pt[1]:.3f} Z{z_mid:.3f} I{i_off:.3f} J{j_off:.3f} F{plunge_feed:.0f}")

        i_off_2 = cx - mid_pt[0]
        j_off_2 = cy - mid_pt[1]
        segments.append({
            "type": "G2", "from": list(mid_pt), "to": list(to_pt),
            "center": [cx, cy, next_z], "radius": helix_radius,
        })
        gcode.append(f"G2 X{to_pt[0]:.3f} Y{to_pt[1]:.3f} Z{next_z:.3f} I{i_off_2:.3f} J{j_off_2:.3f} F{plunge_feed:.0f}")

        current_z = next_z

    cleanup_mid = [cx - helix_radius, cy, z_end]
    cleanup_end = [start_x, start_y, z_end]
    segments.append({
        "type": "G2", "from": [start_x, start_y, z_end], "to": list(cleanup_mid),
        "center": [cx, cy, z_end], "radius": helix_radius,
    })
    gcode.append(f"G2 X{cleanup_mid[0]:.3f} Y{cleanup_mid[1]:.3f} I{i_off:.3f} J{j_off:.3f} F{feed:.0f}")

    i_off_2 = cx - cleanup_mid[0]
    j_off_2 = cy - cleanup_mid[1]
    segments.append({
        "type": "G2", "from": list(cleanup_mid), "to": list(cleanup_end),
        "center": [cx, cy, z_end], "radius": helix_radius,
    })
    gcode.append(f"G2 X{cleanup_end[0]:.3f} Y{cleanup_end[1]:.3f} I{i_off_2:.3f} J{j_off_2:.3f} F{feed:.0f}")

    segments.append({"type": "G0", "from": list(cleanup_end), "to": [start_x, start_y, safe_z]})
    gcode.append(f"G0 Z{safe_z:.3f}")

    return segments, gcode


def _generate_pocket_contour_toolpath(
    feat: dict[str, Any],
    tool_radius: float,
    feed: float,
    safe_z: float,
    part_top_z: float,
    step_down: float,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Generate rectangular contour toolpath for a pocket feature with rounded corners."""
    center = feat.get("center", {})
    cx = float(center.get("x", 0))
    cy = float(center.get("y", 0))
    depth = min(float(feat.get("depth", 0)), part_top_z)
    bounds = feat.get("bounds", {})
    bx = float(bounds.get("x", 0)) / 2.0
    by = float(bounds.get("y", 0)) / 2.0

    if bx < tool_radius + 0.1 or by < tool_radius + 0.1 or depth <= 0:
        return [], []

    offset_x = bx - tool_radius
    offset_y = by - tool_radius
    corner_r = min(tool_radius, offset_x, offset_y)

    segments: list[dict[str, Any]] = []
    gcode: list[str] = []

    gcode.append(f"(Pocket {bx * 2:.1f}x{by * 2:.1f} depth {depth:.1f} at X{cx:.1f} Y{cy:.1f})")

    z_start = 0.0
    z_end = -depth
    num_layers = max(1, math.ceil(depth / max(step_down, 0.1)))
    plunge_feed = feed * 0.3

    entry_x = cx + offset_x - corner_r
    entry_y = cy - offset_y

    segments.append({"type": "G0", "from": [0.0, 0.0, safe_z], "to": [entry_x, entry_y, safe_z]})
    gcode.append(f"G0 X{entry_x:.3f} Y{entry_y:.3f} Z{safe_z:.3f}")

    for layer_i in range(num_layers):
        z = max(z_start - step_down * (layer_i + 1), z_end)

        prev_pt = [entry_x, entry_y, safe_z if layer_i == 0 else z + step_down]
        segments.append({"type": "G1", "from": list(prev_pt), "to": [entry_x, entry_y, z]})
        gcode.append(f"G1 X{entry_x:.3f} Y{entry_y:.3f} Z{z:.3f} F{plunge_feed:.0f}")

        contour = _pocket_contour_points(cx, cy, offset_x, offset_y, corner_r)

        prev = [entry_x, entry_y, z]
        for seg in contour:
            if seg["type"] == "G1":
                to_pt = [seg["x"], seg["y"], z]
                segments.append({"type": "G1", "from": list(prev), "to": list(to_pt)})
                gcode.append(f"G1 X{seg['x']:.3f} Y{seg['y']:.3f} F{feed:.0f}")
                prev = to_pt
            elif seg["type"] in ("G2", "G3"):
                to_pt = [seg["x"], seg["y"], z]
                segments.append({
                    "type": seg["type"], "from": list(prev), "to": list(to_pt),
                    "center": [seg["cx"], seg["cy"], z], "radius": corner_r,
                })
                gcode.append(
                    f"{seg['type']} X{seg['x']:.3f} Y{seg['y']:.3f} "
                    f"I{seg['cx'] - prev[0]:.3f} J{seg['cy'] - prev[1]:.3f} F{feed:.0f}"
                )
                prev = to_pt

    segments.append({"type": "G0", "from": list(prev), "to": [entry_x, entry_y, safe_z]})
    gcode.append(f"G0 Z{safe_z:.3f}")

    return segments, gcode


def _pocket_contour_points(
    cx: float, cy: float, ox: float, oy: float, r: float,
) -> list[dict[str, Any]]:
    """Generate a closed rectangular contour with rounded corners (CW = G2).
    Starting point: bottom-right straight edge start."""
    pts: list[dict[str, Any]] = []

    pts.append({"type": "G1", "x": cx + ox, "y": cy - oy + r})
    pts.append({"type": "G2", "x": cx + ox - r, "y": cy + oy, "cx": cx + ox - r, "cy": cy + oy - r})

    pts.append({"type": "G1", "x": cx - ox + r, "y": cy + oy})
    pts.append({"type": "G2", "x": cx - ox, "y": cy + oy - r, "cx": cx - ox + r, "cy": cy + oy - r})

    pts.append({"type": "G1", "x": cx - ox, "y": cy - oy + r})
    pts.append({"type": "G2", "x": cx - ox + r, "y": cy - oy, "cx": cx - ox + r, "cy": cy - oy + r})

    pts.append({"type": "G1", "x": cx + ox - r, "y": cy - oy})
    pts.append({"type": "G2", "x": cx + ox, "y": cy - oy + r, "cx": cx + ox - r, "cy": cy - oy + r})

    return pts


# ---------------------------------------------------------------------------
# Stock & section geometry
# ---------------------------------------------------------------------------

def _compute_stock(part_bounds: np.ndarray, margin_xy: float = 3.0, margin_z: float = 3.0) -> np.ndarray:
    stock_min = part_bounds[0].copy()
    stock_max = part_bounds[1].copy()
    stock_min[0] -= margin_xy
    stock_min[1] -= margin_xy
    stock_max[0] += margin_xy
    stock_max[1] += margin_xy
    stock_max[2] += margin_z
    return np.array([stock_min, stock_max], dtype=float)


def _compute_removal_regions(
    mesh: trimesh.Trimesh,
    stock_bounds: np.ndarray,
    cut_plane_z: float,
    tool_radius: float,
    part_section_override: BaseGeometry | None = None,
) -> BaseGeometry:
    stock_polygon = box(
        float(stock_bounds[0][0]),
        float(stock_bounds[0][1]),
        float(stock_bounds[1][0]),
        float(stock_bounds[1][1]),
    ).buffer(-tool_radius)
    if stock_polygon.is_empty:
        return GeometryCollection()

    if part_section_override is not None:
        part_section = part_section_override
    else:
        part_section = _extract_section_geometry(mesh, cut_plane_z)

    if part_section.is_empty:
        return stock_polygon

    removal = stock_polygon.difference(part_section.buffer(tool_radius))
    return _clean_geometry(removal)


def _extract_section_geometry(mesh: trimesh.Trimesh, cut_plane_z: float) -> BaseGeometry:
    z_min = float(mesh.bounds[0][2])
    z_max = float(mesh.bounds[1][2])
    if cut_plane_z >= z_max - 1e-6:
        return GeometryCollection()
    if cut_plane_z < z_min:
        return GeometryCollection()
    effective_z = max(cut_plane_z, z_min + 0.05)
    effective_z = min(effective_z, z_max - 0.05)
    section = mesh.section(
        plane_origin=np.array([0.0, 0.0, effective_z], dtype=float),
        plane_normal=np.array([0.0, 0.0, 1.0], dtype=float),
    )
    if section is None:
        return GeometryCollection()

    if hasattr(section, "to_planar"):
        planar_section, to_3d = section.to_planar()
    else:
        planar_section, to_3d = section.to_2D()

    polygons = [poly.buffer(0) for poly in planar_section.polygons_full if poly.area > AREA_EPS]
    if not polygons:
        return GeometryCollection()
    merged = unary_union(polygons)

    a, b = float(to_3d[0, 0]), float(to_3d[0, 1])
    d, e = float(to_3d[1, 0]), float(to_3d[1, 1])
    dx, dy = float(to_3d[0, 3]), float(to_3d[1, 3])
    if not (abs(a - 1) < 1e-9 and abs(e - 1) < 1e-9 and abs(b) < 1e-9 and abs(d) < 1e-9
            and abs(dx) < 1e-9 and abs(dy) < 1e-9):
        merged = shapely_affinity.affine_transform(merged, [a, b, d, e, dx, dy])

    return _clean_geometry(merged)


def _clean_geometry(geometry: BaseGeometry) -> BaseGeometry:
    if geometry.is_empty:
        return GeometryCollection()
    cleaned = geometry.buffer(0)
    if cleaned.is_empty:
        return GeometryCollection()
    return cleaned


# ---------------------------------------------------------------------------
# Scan-line helpers
# ---------------------------------------------------------------------------

def _build_layer_scan_segments(removal_geometry: BaseGeometry, step_over: float) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    if removal_geometry.is_empty:
        return []

    min_x, min_y, max_x, max_y = removal_geometry.bounds
    segments: list[tuple[tuple[float, float], tuple[float, float]]] = []
    y = min_y
    forward = True

    while y <= max_y + 1e-6:
        row_segments = _intersect_row(removal_geometry, y, min_x, max_x)
        if row_segments:
            ordered = row_segments if forward else list(reversed(row_segments))
            for x0, x1 in ordered:
                start = (x0, y) if forward else (x1, y)
                end = (x1, y) if forward else (x0, y)
                segments.append((start, end))
            forward = not forward
        y += step_over

    return segments


def _intersect_row(removal_geometry: BaseGeometry, y: float, min_x: float, max_x: float) -> list[tuple[float, float]]:
    line = LineString([(min_x - 1.0, y), (max_x + 1.0, y)])
    intersection = removal_geometry.intersection(line)
    intervals: list[tuple[float, float]] = []

    for geom in _iter_line_geometries(intersection):
        coords = list(geom.coords)
        if len(coords) < 2:
            continue
        x0 = float(coords[0][0])
        x1 = float(coords[-1][0])
        if abs(x1 - x0) <= SEGMENT_EPS:
            continue
        intervals.append((min(x0, x1), max(x0, x1)))

    intervals.sort(key=lambda item: item[0])
    return intervals


def _iter_line_geometries(geometry: BaseGeometry) -> list[LineString]:
    if geometry.is_empty:
        return []
    if isinstance(geometry, LineString):
        return [geometry]
    if isinstance(geometry, MultiLineString):
        return [line for line in geometry.geoms if line.length > SEGMENT_EPS]
    if isinstance(geometry, GeometryCollection):
        lines: list[LineString] = []
        for geom in geometry.geoms:
            lines.extend(_iter_line_geometries(geom))
        return lines
    return []


# ---------------------------------------------------------------------------
# Fallback & utilities
# ---------------------------------------------------------------------------

def _generate_bbox_fallback(inputs: CamInputs, stock_bounds: np.ndarray, strategy: str) -> dict[str, Any]:
    """Safe fallback: return empty toolpath with warning instead of cutting through the part."""
    extents = stock_bounds[1] - stock_bounds[0]
    gcode_lines = _gcode_header(inputs, extents)
    gcode_lines.extend([
        f"(Strategy: {strategy} — stock margin too narrow for selected tool)",
        "M5",
        "M30",
    ])
    return {
        "gcode_lines": gcode_lines,
        "toolpath_segments": [],
        "estimated_time_minutes": 0,
        "stats": {
            "layers": 0,
            "total_cut_length_mm": 0,
            "strategy": strategy,
            "warning": "刀具直径大于毛坯余量，无法生成安全刀路。请选用更小的刀具或增大毛坯余量。",
        },
    }


def _cutting_length(toolpath_segments: list[dict[str, Any]]) -> float:
    total = 0.0
    for seg in toolpath_segments:
        if seg["type"] in ("G1", "G2", "G3"):
            if seg["type"] == "G1":
                total += math.sqrt(sum((b - a) ** 2 for a, b in zip(seg["from"], seg["to"])))
            else:
                r = seg.get("radius", 0)
                if r > 0:
                    total += math.pi * r
                else:
                    total += math.sqrt(sum((b - a) ** 2 for a, b in zip(seg["from"], seg["to"])))
    return total
