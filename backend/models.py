from sqlalchemy import Column, Integer, String, Float, DateTime
from sqlalchemy.sql import func
from database import Base

class ToolCard(Base):
    __tablename__ = "toolcards"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    tool_type = Column(String) # 例如: "flat_endmill"平底刀, "ball_endmill"球头刀
    diameter = Column(Float)   # 刀具直径 (mm)
    flutes = Column(Integer)   # 刃数
    default_feed_rate = Column(Float) # 默认进给率 (mm/min)
    max_spindle_speed = Column(Integer) # 最大主轴转速 (rpm)

class CAMRecord(Base):
    """
    专家工艺推荐系统的基础语料表 (Craftsman Master Data)
    记录每次加工成功时的模型特征及所选参数，作为之后最近邻距离推算的基础。
    """
    __tablename__ = "cam_records"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String, index=True) 
    
    # === 模型特征 (Features for distance calculation) ===
    model_volume = Column(Float) # 体积 (mm^3)
    bbox_x = Column(Float)       # 包围盒X长度 (mm)
    bbox_y = Column(Float)       # 包围盒Y长度 (mm)
    z_depth = Column(Float)      # 加工最大深度 (mm)
    material = Column(String)    # 加工材质 (如: Aluminum)

    # === 采用的最终工艺参数 (Selected Strategy parameters) ===
    rough_tool_id = Column(Integer) # 所选粗加工用刀 
    rough_step_down = Column(Float) # 粗加工背吃刀量 (Z方向下刀量)
    finish_tool_id = Column(Integer) # 所选精加用刀
    spindle_speed = Column(Integer) # 主轴转速
    feed_rate = Column(Float)       # G-Code进给量

    created_at = Column(DateTime(timezone=True), server_default=func.now())

class Job(Base):
    """用于异步记录生成状态表的结构"""
    __tablename__ = "jobs"
    
    id = Column(String, primary_key=True, index=True) # 使用UUID作为任务ID
    filename = Column(String)
    status = Column(String) # 状态: uploaded, toolpath_generating, done, failed
    stage = Column(String, nullable=True) # 子阶段: parsing, meshing, cam, postprocessing
    progress = Column(Integer, default=0) # 0-100
    error_code = Column(String, nullable=True)
    error_message = Column(String, nullable=True)
    gcode_url = Column(String, nullable=True) # 最终产物下载路径
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
