import sys
import json
import os
import glob

def find_freecad_path():
    env_path = os.environ.get("FREECAD_PATH")
    if env_path and os.path.exists(env_path):
        return env_path
        
    if os.name == 'nt':
        search_paths = glob.glob(r"C:\Program Files\FreeCAD*\*bin")
        local_appdata = os.environ.get("LOCALAPPDATA", "")
        if local_appdata:
            search_paths.extend(glob.glob(os.path.join(local_appdata, r"Programs\FreeCAD*\*bin")))
            
        if search_paths:
            # 排序后取最新版本
            return sorted(search_paths)[-1]
    else:
        if os.path.exists("/usr/lib/freecad/lib"):
            return "/usr/lib/freecad/lib"
    return None

FREECAD_PATH = find_freecad_path()

if not FREECAD_PATH:
    # 直接向 stdout 抛出 JSON 避免后端崩溃
    print(json.dumps({"error": "FreeCAD Runtime not found on the system."}))
    sys.exit(1)

if FREECAD_PATH not in sys.path:
    # 修复 Python 3.8+ 在 Windows 下无法找到 FreeCAD .dll 的报错核心点
    if os.name == 'nt' and hasattr(os, 'add_dll_directory'):
        os.add_dll_directory(FREECAD_PATH)
    sys.path.append(FREECAD_PATH)

import FreeCAD
import Part
import Mesh

def process_step_to_gltf(step_path: str, output_dir: str):
    """
    处理 STEP 文件：
    1. 提取包围盒体积和最大深度
    2. 计算各个面的法向量和中心，用于 Web 前端装夹对齐拾取
    3. 输出 .obj 与 .json 供前端消费 (FreeCAD 默认不直接原生支持输出完好材质 glTF，通常转 OBJ 或用额外库导出 GLB)
    """
    doc = FreeCAD.newDocument("CloudCAM")
    Part.insert(step_path, doc.Name)
    
    obj = doc.Objects[0]
    shape = obj.Shape
    
    # 提取特征
    bbox = shape.BoundBox
    volume = shape.Volume
    z_depth = bbox.ZLength
    features = {
        "volume": volume,
        "bbox_x": bbox.XLength,
        "bbox_y": bbox.YLength,
        "z_depth": z_depth
    }
    
    # 提取所有拓扑面的法相
    faces_data = []
    for idx, face in enumerate(shape.Faces):
        # 取面质心处的法向量
        try:
            # 通过面的参数域中心获取法向
            umin, umax, vmin, vmax = face.ParameterRange
            umid = (umin + umax) / 2.0
            vmid = (vmin + vmax) / 2.0
            normal = face.normalAt(umid, vmid)
        except Exception:
            normal = FreeCAD.Vector(0, 0, 1)
            
        faces_data.append({
            "face_id": idx,
            "normal": {"x": normal.x, "y": normal.y, "z": normal.z},
            "center": {"x": face.CenterOfMass.x, "y": face.CenterOfMass.y, "z": face.CenterOfMass.z}
        })
        
    # 导出渲染用的 Mesh (此处先统一导出 OBJ 供 Web展示，因 OBJ 是最安全的 ASCII 无损支持)
    base_name = os.path.basename(step_path).split('.')[0]
    obj_path = os.path.join(output_dir, f"{base_name}.obj")
    
    mesh = doc.addObject("Mesh::Feature", "Mesh")
    mesh.Mesh = Mesh.Mesh(shape.tessellate(0.1)) # 细分精度
    Mesh.export([mesh], obj_path)
    
    return {
        "features": features,
        "faces": faces_data,
        "render_file": f"{base_name}.obj"
    }

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output_dir", required=True)
    args = parser.parse_args()
    
    res = process_step_to_gltf(args.input, args.output_dir)
    # 将 JSON 结果打印至 std_out 供主服务端截取
    print(json.dumps(res))
