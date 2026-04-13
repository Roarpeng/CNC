"""
统一的 FreeCAD 环境发现模块。
upload.py 和 freecad_processor.py 都应引用此处逻辑，避免重复扫描。
"""

import os
import glob
from functools import lru_cache


@lru_cache(maxsize=1)
def find_freecad_python() -> str:
    """
    返回 FreeCAD 自带 python.exe 的完整路径 (Windows)。
    找不到时返回 'python' 作为降级 fallback。
    """
    search_paths: list[str] = []

    if os.name == 'nt':
        search_paths.extend(glob.glob(r"C:\Program Files\FreeCAD*\*bin\python.exe"))
        local_appdata = os.environ.get("LOCALAPPDATA", "")
        if local_appdata:
            search_paths.extend(
                glob.glob(os.path.join(local_appdata, r"Programs\FreeCAD*\*bin\python.exe"))
            )
    else:
        # Linux: 通常 FreeCAD 安装后自带 python 在 /usr/lib/freecad/bin/
        search_paths.extend(glob.glob("/usr/lib/freecad*/bin/python*"))

    if search_paths:
        return sorted(search_paths)[-1]

    return "python"


@lru_cache(maxsize=1)
def find_freecad_lib_path() -> str | None:
    """
    返回 FreeCAD 的 lib/bin 目录路径 (供 freecad_processor.py 添加到 sys.path)。
    """
    env_path = os.environ.get("FREECAD_PATH")
    if env_path and os.path.exists(env_path):
        return env_path

    if os.name == 'nt':
        search_paths = glob.glob(r"C:\Program Files\FreeCAD*\*bin")
        local_appdata = os.environ.get("LOCALAPPDATA", "")
        if local_appdata:
            search_paths.extend(
                glob.glob(os.path.join(local_appdata, r"Programs\FreeCAD*\*bin"))
            )
        if search_paths:
            return sorted(search_paths)[-1]
    else:
        if os.path.exists("/usr/lib/freecad/lib"):
            return "/usr/lib/freecad/lib"

    return None
