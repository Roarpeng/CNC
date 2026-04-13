import math
from typing import Dict, Any
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from database import get_db
from models import CAMRecord

router = APIRouter()

# 可配置的特征权重
WEIGHT_VOLUME = 0.4
WEIGHT_DEPTH = 0.6

@router.get("/recommend/")
def get_recommendation(volume: float, max_depth: float, db: Session = Depends(get_db)):
    """
    依靠工业界特征"多维欧氏距离"算法，在往期积累库中寻找最合适的刀具与进给。
    采用 Min-Max 归一化消除量纲差异。
    """
    records = db.query(CAMRecord).all()
    if not records:
        # Fallback 策略
        return {
            "rough_tool_id": 1, 
            "rough_step_down": 2.0,
            "spindle_speed": 4000,
            "feed_rate": 800.0,
            "is_guessed": True
        }

    # Min-Max 归一化参数
    volumes = [r.model_volume for r in records if r.model_volume is not None]
    depths = [r.z_depth for r in records if r.z_depth is not None]

    vol_min, vol_max = (min(volumes), max(volumes)) if volumes else (0, 1)
    dep_min, dep_max = (min(depths), max(depths)) if depths else (0, 1)
    vol_range = vol_max - vol_min if vol_max != vol_min else 1.0
    dep_range = dep_max - dep_min if dep_max != dep_min else 1.0

    def normalize_vol(v: float) -> float:
        return (v - vol_min) / vol_range

    def normalize_dep(d: float) -> float:
        return (d - dep_min) / dep_range

    query_vol = normalize_vol(volume)
    query_dep = normalize_dep(max_depth)

    best_record = None
    min_distance = float('inf')
    
    for r in records:
        if r.model_volume is None or r.z_depth is None:
            continue
        vol_diff = normalize_vol(r.model_volume) - query_vol
        dep_diff = normalize_dep(r.z_depth) - query_dep
        dist = math.sqrt(WEIGHT_VOLUME * (vol_diff ** 2) + WEIGHT_DEPTH * (dep_diff ** 2))
        if dist < min_distance:
            min_distance = dist
            best_record = r

    if not best_record:
        return {
            "rough_tool_id": 1,
            "rough_step_down": 2.0,
            "spindle_speed": 4000,
            "feed_rate": 800.0,
            "is_guessed": True
        }
            
    return {
        "rough_tool_id": best_record.rough_tool_id,
        "rough_step_down": best_record.rough_step_down,
        "finish_tool_id": best_record.finish_tool_id,
        "spindle_speed": best_record.spindle_speed,
        "feed_rate": best_record.feed_rate,
        "confidence_distance": round(min_distance, 4),
        "is_guessed": False
    }
