from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import trimesh
from shapely import affinity as shapely_affinity
from shapely.geometry import GeometryCollection, LineString, MultiLineString, box
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union


SAFE_Z_DEFAULT = 5.0
AREA_EPS = 1e-3
SEGMENT_EPS = 1e-3
STOCK_MARGIN = 3.0

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
    """
    Based on recognized manufacturing features, recommend a roughing tool
    and per-feature finishing tools from the built-in library.
    """
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
    safe_z: float = SAFE_Z_DEFAULT
    setup_normal: tuple[float, float, float] | None = None


def generate_cam_with_ocl(inputs: CamInputs) -> dict[str, Any]:
    """
    Preferred pipeline: OpenCAMLib drop-cutter.
    If runtime binding is unavailable, falls back to a deterministic planar roughing path
    while keeping the same API contract.

    Toolpath segment coordinates are returned in the original model coordinate
    space so the frontend can overlay them directly on the un-rotated mesh.
    """
    try:
        mesh, inverse_transform = _load_prepared_mesh(inputs)
        part_bounds = mesh.bounds

        if _has_ocl_runtime():
            result = _generate_dropcutter_toolpath(inputs, mesh, part_bounds)
        else:
            result = _generate_planar_fallback(inputs, mesh, part_bounds, strategy="stock_aware_fallback")

        part_top_z = float(part_bounds[1][2])
        _segments_machine_z_to_prepared(result["toolpath_segments"], part_top_z)
        _transform_segments_to_model_space(result["toolpath_segments"], inverse_transform)
        return result
    except Exception as exc:
        raise CamEngineError(f"CAM 生成失败: {exc}") from exc


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


def _segments_machine_z_to_prepared(
    segments: list[dict[str, Any]],
    part_top_z: float,
) -> None:
    """Toolpath Z values use G-code convention (Z=0 at part top, negative downward).
    Convert them to prepared-mesh frame (absolute Z) so the inverse transform works correctly."""
    for seg in segments:
        for key in ("from", "to"):
            seg[key][2] += part_top_z


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


def _generate_dropcutter_toolpath(inputs: CamInputs, mesh: trimesh.Trimesh, part_bounds: np.ndarray) -> dict[str, Any]:
    """
    Stock-aware roughing currently shares the same planner for OCL/non-OCL paths.
    This keeps the generated path conservative and avoids machining away the part.
    """
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

    gcode_lines = [
        f"(Cloud CAM Generated for Job {inputs.job_id})",
        f"(Model: {float(extents[0]):.1f} x {float(extents[1]):.1f} x {float(extents[2]):.1f} mm)",
        f"(Params: step_down={inputs.step_down} spindle={inputs.spindle_speed} feed={inputs.feed_rate})",
        f"(Strategy: {strategy})",
        "G21 (metric)",
        "G90 (absolute)",
        f"S{inputs.spindle_speed} M3",
        f"G0 Z{inputs.safe_z}",
    ]

    toolpath_segments: list[dict[str, Any]] = []
    prev = [0.0, 0.0, inputs.safe_z]
    machined_layers = 0

    stock_top_z = float(stock_bounds[1][2])
    stock_bot_z = float(stock_bounds[0][2])
    part_top_z = float(part_bounds[1][2])

    for layer in range(num_layers):
        cut_plane_z = max(stock_top_z - step_down * (layer + 1), stock_bot_z)
        cut_depth = cut_plane_z - part_top_z
        removal_geometry = _compute_removal_regions(mesh, stock_bounds, cut_plane_z, tool_radius)
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

    toolpath_segments.append({"type": "G0", "from": list(prev), "to": [0.0, 0.0, inputs.safe_z]})
    gcode_lines.extend(["G0 X0 Y0", "M5", "M30"])

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
) -> BaseGeometry:
    stock_polygon = box(
        float(stock_bounds[0][0]),
        float(stock_bounds[0][1]),
        float(stock_bounds[1][0]),
        float(stock_bounds[1][1]),
    ).buffer(-tool_radius)
    if stock_polygon.is_empty:
        return GeometryCollection()

    part_section = _extract_section_geometry(mesh, cut_plane_z)
    if part_section.is_empty:
        return stock_polygon

    removal = stock_polygon.difference(part_section.buffer(tool_radius))
    return _clean_geometry(removal)


def _extract_section_geometry(mesh: trimesh.Trimesh, cut_plane_z: float) -> BaseGeometry:
    z_min = float(mesh.bounds[0][2])
    z_max = float(mesh.bounds[1][2])
    if cut_plane_z >= z_max - 1e-6 or cut_plane_z <= z_min + 1e-6:
        return GeometryCollection()
    section = mesh.section(
        plane_origin=np.array([0.0, 0.0, cut_plane_z], dtype=float),
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

    # to_planar() centres coordinates on the section centroid.
    # Apply the to_3D affine (rotation + translation) to restore mesh-frame x,y.
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


def _generate_bbox_fallback(inputs: CamInputs, stock_bounds: np.ndarray, strategy: str) -> dict[str, Any]:
    step_over = max(inputs.tool_diameter * inputs.step_over_ratio, 0.1)
    tool_radius = max(inputs.tool_diameter * 0.5, 0.1)
    stock_height = float(stock_bounds[1][2] - stock_bounds[0][2])
    num_layers = max(1, math.ceil(stock_height / max(inputs.step_down, 0.1)))
    extents = stock_bounds[1] - stock_bounds[0]
    stock_polygon = box(
        float(stock_bounds[0][0]),
        float(stock_bounds[0][1]),
        float(stock_bounds[1][0]),
        float(stock_bounds[1][1]),
    ).buffer(-tool_radius)

    gcode_lines = [
        f"(Cloud CAM Generated for Job {inputs.job_id})",
        f"(Model: {float(extents[0]):.1f} x {float(extents[1]):.1f} x {float(extents[2]):.1f} mm)",
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
        cut_depth = -min(inputs.step_down * (layer + 1), stock_height)
        scan_segments = _build_layer_scan_segments(stock_polygon, step_over)
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
