import { useEffect, useState } from 'react';
import axios from 'axios';
import { UploadCloud, Settings, Play, Download, AlertTriangle, Box, Ruler, Layers, CheckCircle2, Loader2, Move3d, Crosshair, Eye, EyeOff, RotateCw, FolderClock, Wrench } from 'lucide-react';
import type { InteractionMode, SelectedFace, MeasureResult } from './components/ModelViewer';
import type { ToolpathSegment } from './components/ToolpathViewer';
import ModelViewer from './components/ModelViewer';
import ErrorBoundary from './components/ErrorBoundary';
import './App.css';

const API = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';

type Status = 'idle' | 'uploading' | 'uploaded' | 'generating' | 'done' | 'error';

type JobSnapshot = {
  job_id: string;
  filename: string;
  status: string;
  stage?: string | null;
  progress?: number | null;
  error_code?: string | null;
  error_message?: string | null;
  gcode_url?: string | null;
  render_url?: string | null;
  topology?: any;
  cam_result?: {
    estimated_time_minutes?: number;
    stats?: Record<string, unknown>;
    toolpath_segments?: ToolpathSegment[];
  } | null;
  created_at?: string;
  updated_at?: string;
};

type ManufacturingFeature = {
  type: string;
  surface?: string;
  face_id?: number;
  diameter?: number;
  depth?: number;
  height?: number;
  area?: number;
  axis?: string;
  bounds?: { x?: number; y?: number };
};

type ToolInfo = {
  id: number;
  diameter: number;
  name: string;
  type: string;
  flutes?: number;
};

type FeatureToolEntry = {
  feature_type: string;
  feature_face_id?: number;
  diameter?: number;
  depth?: number;
  bounds?: { x?: number; y?: number };
  tool: ToolInfo | null;
  reason: string;
};

type ToolPlan = {
  roughing_tool: ToolInfo;
  feature_tools: FeatureToolEntry[];
};

function mapJobStatus(status?: string): Status {
  if (status === 'done') return 'done';
  if (status === 'failed') return 'error';
  if (status === 'generating') return 'generating';
  if (status === 'parsed' || status === 'parsed_mock' || status === 'uploaded') return 'uploaded';
  return 'idle';
}

function formatJobStatus(status?: string) {
  switch (status) {
    case 'done': return '已完成';
    case 'failed': return '失败';
    case 'generating': return '生成中';
    case 'parsing': return '解析中';
    case 'parsed_mock': return '解析完成(降级)';
    case 'parsed': return '解析完成';
    case 'queued': return '排队中';
    case 'uploaded': return '已上传';
    default: return '待处理';
  }
}

function formatStage(stage?: string | null) {
  switch (stage) {
    case 'queued': return '等待';
    case 'parsing': return '解析';
    case 'meshing': return '网格化';
    case 'cam': return '刀路';
    case 'completed': return '完成';
    default: return '未开始';
  }
}

function formatJobTime(value?: string) {
  if (!value) return '未知';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '未知';
  return date.toLocaleString('zh-CN', { hour12: false });
}

function formatFeatureType(type: string) {
  switch (type) {
    case 'hole': return '孔';
    case 'pocket': return '型腔';
    case 'boss': return '凸台';
    default: return type;
  }
}

function App() {
  const [file, setFile] = useState<File | null>(null);
  const [status, setStatus] = useState<Status>('idle');
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [modelData, setModelData] = useState<any>(null);
  const [currentJob, setCurrentJob] = useState<JobSnapshot | null>(null);
  const [recentJobs, setRecentJobs] = useState<JobSnapshot[]>([]);
  const [jobsLoading, setJobsLoading] = useState(false);
  const [craftsmanParams, setCraftsmanParams] = useState<any>(null);
  const [gcodeResult, setGcodeResult] = useState<any>(null);

  // 3D 交互状态
  const [viewMode, setViewMode] = useState<InteractionMode>('orbit');
  const [selectedFace, setSelectedFace] = useState<SelectedFace | null>(null);
  const [measureResult, setMeasureResult] = useState<MeasureResult | null>(null);
  const [showToolpath, setShowToolpath] = useState(true);
  const [toolpathSegments, setToolpathSegments] = useState<ToolpathSegment[]>([]);
  const [toolPlan, setToolPlan] = useState<ToolPlan | null>(null);

  // 可编辑的工艺参数 (由专家推荐初始化，用户可覆写)
  const [editParams, setEditParams] = useState({
    rough_step_down: 2.0,
    spindle_speed: 4000,
    feed_rate: 800.0,
    rough_tool_id: 1,
  });

  useEffect(() => {
    void loadRecentJobs();
  }, []);

  const syncJobToUi = (job: JobSnapshot) => {
    setCurrentJob(job);
    setStatus(mapJobStatus(job.status));
    setErrorMsg(job.error_message ? `${job.error_code ? `[${job.error_code}] ` : ''}${job.error_message}` : null);

    if (job.render_url || job.topology) {
      setModelData({
        job_id: job.job_id,
        render_url: job.render_url,
        topology: job.topology,
      });
    }

    const restoredCam = job.gcode_url || job.cam_result
      ? {
          estimated_time_minutes: job.cam_result?.estimated_time_minutes,
          gcode_url: job.gcode_url,
          stats: job.cam_result?.stats,
          toolpath_segments: job.cam_result?.toolpath_segments ?? [],
        }
      : null;

    setGcodeResult(restoredCam);
    setToolpathSegments(restoredCam?.toolpath_segments ?? []);
    setToolPlan((job.cam_result as any)?.tool_plan ?? null);
    setSelectedFace(null);
    setMeasureResult(null);
  };

  const loadRecentJobs = async () => {
    setJobsLoading(true);
    try {
      const res = await axios.get(`${API}/api/v1/jobs/recent`, { params: { limit: 8 } });
      setRecentJobs(res.data.items ?? []);
    } catch (err) {
      console.error('Load recent jobs failed', err);
    } finally {
      setJobsLoading(false);
    }
  };

  const loadJobDetail = async (jobId: string) => {
    try {
      const res = await axios.get(`${API}/api/v1/jobs/${jobId}`);
      syncJobToUi(res.data);
      if (res.data.topology?.features) {
        void fetchCraftsmanAdvice(res.data.topology.features);
      } else {
        setCraftsmanParams(null);
      }
    } catch (err: any) {
      const detail = err?.response?.data?.detail || err?.message || '读取作业失败';
      setErrorMsg(detail);
      setStatus('error');
    }
  };

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    if (!e.target.files || e.target.files.length === 0) return;
    const selectedFile = e.target.files[0];

    // 前端文件大小校验 (100 MB)
    if (selectedFile.size > 100 * 1024 * 1024) {
      setErrorMsg('文件过大 (>100 MB)，请压缩或简化模型后重试');
      setStatus('error');
      return;
    }

    setFile(selectedFile);
    setStatus('uploading');
    setErrorMsg(null);
    setGcodeResult(null);
    setCraftsmanParams(null);
    setModelData(null);
    setCurrentJob(null);
    setToolpathSegments([]);
    setToolPlan(null);

    const formData = new FormData();
    formData.append('file', selectedFile);

    try {
      const res = await axios.post(`${API}/api/v1/upload/`, formData);
      syncJobToUi(res.data);
      if (res.data.topology?.features) {
        void fetchCraftsmanAdvice(res.data.topology.features);
      }
      await loadRecentJobs();
    } catch (err: any) {
      const detail = err?.response?.data?.detail || err?.message || '上传失败';
      setErrorMsg(detail);
      setStatus('error');
    }
  };

  const fetchCraftsmanAdvice = async (features: any) => {
    try {
      const res = await axios.get(`${API}/api/v1/craftsman/recommend/`, {
        params: { volume: features.volume, max_depth: features.z_depth }
      });
      setCraftsmanParams(res.data);
      setEditParams({
        rough_step_down: res.data.rough_step_down,
        spindle_speed: res.data.spindle_speed,
        feed_rate: res.data.feed_rate,
        rough_tool_id: res.data.rough_tool_id ?? 1,
      });
    } catch (err) {
      console.error('Expert system failed', err);
    }
  };

  const handleGenerate = async () => {
    if (!modelData) return;
    setStatus('generating');
    setErrorMsg(null);

    try {
      const f = modelData.topology?.features;
      const res = await axios.post(`${API}/api/v1/cam/generate/`, {
        job_id: modelData.job_id,
        rough_tool_id: editParams.rough_tool_id,
        rough_step_down: editParams.rough_step_down,
        spindle_speed: editParams.spindle_speed,
        feed_rate: editParams.feed_rate,
        bbox_x: f?.bbox_x ?? 50,
        bbox_y: f?.bbox_y ?? 50,
        z_depth: f?.z_depth ?? 20,
        volume: f?.volume,
        selected_face: selectedFace ? {
          face_index: selectedFace.faceIndex,
          normal: { x: selectedFace.normal.x, y: selectedFace.normal.y, z: selectedFace.normal.z },
          center: { x: selectedFace.center.x, y: selectedFace.center.y, z: selectedFace.center.z },
        } : null,
      });
      setGcodeResult(res.data);
      if (res.data.toolpath_segments) {
        setToolpathSegments(res.data.toolpath_segments);
      }
      setToolPlan(res.data.tool_plan ?? null);
      setStatus('done');
      const nextJob: JobSnapshot = {
        ...(currentJob ?? {} as JobSnapshot),
        job_id: modelData.job_id,
        filename: currentJob?.filename ?? file?.name ?? '未命名文件',
        status: res.data.job_status ?? 'done',
        stage: res.data.stage ?? 'completed',
        progress: res.data.progress ?? 100,
        gcode_url: res.data.gcode_url,
        render_url: modelData.render_url,
        topology: modelData.topology,
        cam_result: {
          estimated_time_minutes: res.data.estimated_time_minutes,
          stats: res.data.stats,
          toolpath_segments: res.data.toolpath_segments ?? [],
        },
      };
      setCurrentJob(nextJob);
      await loadRecentJobs();
    } catch (err: any) {
      const detail = err?.response?.data?.detail || err?.message || 'G-Code 生成失败';
      setErrorMsg(detail);
      setStatus('error');
    }
  };

  const features = modelData?.topology?.features;
  const manufacturingFeatures = (modelData?.topology?.manufacturing_features ?? []) as ManufacturingFeature[];
  const featureSummary = (modelData?.topology?.feature_summary ?? {}) as Record<string, number>;
  const currentProgress = currentJob?.progress ?? (status === 'done' ? 100 : status === 'uploaded' ? 100 : 0);

  return (
    <div className="flex h-screen w-screen text-slate-200">
      {/* ====== 侧边栏 ====== */}
      <div className="w-[340px] min-w-[300px] bg-slate-800/80 backdrop-blur-xl border-r border-slate-700 flex flex-col z-10 shadow-2xl">

        {/* 头部 */}
        <div className="p-5 pb-3">
          <h1 className="text-2xl font-bold bg-gradient-to-r from-cyan-400 to-blue-500 bg-clip-text text-transparent">
            Cloud CAM
          </h1>
          <p className="text-xs text-slate-400 mt-1">Intelligent CNC Path Generation</p>
        </div>

        {/* 可滚动内容区 */}
        <div className="flex-1 overflow-y-auto px-5 pb-4 space-y-4 custom-scrollbar">

          {/* 上传区域 */}
          <div className={`relative border-2 border-dashed rounded-xl p-6 flex flex-col items-center justify-center gap-2 transition-all cursor-pointer group
            ${status === 'uploading' ? 'border-cyan-500 bg-cyan-950/30 pointer-events-none' :
              status === 'error' ? 'border-red-500/60 hover:border-red-400' :
              'border-slate-600 hover:border-cyan-400 hover:bg-slate-700/50'}`}>
            <input
              type="file"
              className="absolute inset-0 opacity-0 cursor-pointer"
              accept=".step,.stp"
              onChange={handleUpload}
              disabled={status === 'uploading' || status === 'generating'}
            />
            {status === 'uploading' ? (
              <Loader2 className="w-8 h-8 text-cyan-400 animate-spin" />
            ) : (
              <UploadCloud className="w-8 h-8 text-slate-400 group-hover:text-cyan-400 transition-colors" />
            )}
            <span className="text-sm font-medium text-center leading-tight">
              {status === 'uploading' ? '解析处理中...' : file ? file.name : '点击上传 STEP / STP 文件'}
            </span>
            {!file && <span className="text-[11px] text-slate-500">支持 .step / .stp，最大 100 MB</span>}
          </div>

          {/* 错误提示 */}
          {errorMsg && (
            <div className="flex items-start gap-2 bg-red-950/40 border border-red-500/30 rounded-lg p-3 text-xs text-red-300">
              <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0" />
              <span>{errorMsg}</span>
            </div>
          )}

          {currentJob && (
            <div className="bg-slate-900/70 rounded-lg border border-slate-700 p-4 space-y-3">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <div className="text-[11px] uppercase tracking-[0.24em] text-slate-500">当前作业</div>
                  <div className="mt-1 text-sm font-semibold text-slate-100 truncate">{currentJob.filename}</div>
                </div>
                <StatusBadge status={currentJob.status} />
              </div>

              <div className="grid grid-cols-2 gap-3 text-xs">
                <InfoItem label="阶段" value={formatStage(currentJob.stage)} />
                <InfoItem label="进度" value={`${currentProgress}%`} />
                <InfoItem label="作业 ID" value={currentJob.job_id.slice(0, 8)} mono />
                <InfoItem label="更新时间" value={formatJobTime(currentJob.updated_at)} />
              </div>

              <div className="h-2 rounded-full bg-slate-800 overflow-hidden">
                <div
                  className={`h-full rounded-full transition-all ${currentJob.status === 'failed' ? 'bg-red-500' : currentJob.status === 'done' ? 'bg-emerald-500' : 'bg-cyan-500'}`}
                  style={{ width: `${Math.max(6, Math.min(100, currentProgress))}%` }}
                />
              </div>

              {currentJob.status === 'parsed_mock' && (
                <div className="rounded-lg border border-amber-500/30 bg-amber-950/30 px-3 py-2 text-[11px] text-amber-300">
                  当前模型使用了降级解析结果，适合内部联调和流程验证，正式加工前建议复核网格。
                </div>
              )}
            </div>
          )}

          {/* 模型特征卡片 */}
          {features && (
            <div className="bg-slate-900/60 rounded-lg border border-slate-700 p-4 space-y-2">
              <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wide mb-2">模型特征</h3>
              <div className="grid grid-cols-2 gap-2 text-sm">
                <div className="flex items-center gap-2">
                  <Box className="w-3.5 h-3.5 text-cyan-500" />
                  <span className="text-slate-400 text-xs">体积</span>
                </div>
                <span className="text-right font-mono text-cyan-400 text-xs">{features.volume.toFixed(1)} mm&sup3;</span>

                <div className="flex items-center gap-2">
                  <Ruler className="w-3.5 h-3.5 text-cyan-500" />
                  <span className="text-slate-400 text-xs">尺寸 (X&times;Y)</span>
                </div>
                <span className="text-right font-mono text-cyan-400 text-xs">{features.bbox_x.toFixed(1)} &times; {features.bbox_y.toFixed(1)} mm</span>

                <div className="flex items-center gap-2">
                  <Layers className="w-3.5 h-3.5 text-cyan-500" />
                  <span className="text-slate-400 text-xs">最大深度 (Z)</span>
                </div>
                <span className="text-right font-mono text-cyan-400 text-xs">{features.z_depth.toFixed(1)} mm</span>
              </div>
            </div>
          )}

          {features && (
            <div className="bg-slate-900/60 rounded-lg border border-slate-700 p-4 space-y-3">
              <div className="flex items-center justify-between gap-3">
                <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wide">加工特征识别</h3>
                <span className="text-[11px] text-slate-500">{manufacturingFeatures.length} 项</span>
              </div>

              {manufacturingFeatures.length > 0 && (
                <div className="flex flex-wrap gap-2">
                  {Object.entries(featureSummary).map(([key, value]) => (
                    <span
                      key={key}
                      className="rounded-full border border-cyan-500/20 bg-cyan-950/30 px-2 py-1 text-[11px] text-cyan-300"
                    >
                      {formatFeatureType(key)} x {value}
                    </span>
                  ))}
                </div>
              )}

              {manufacturingFeatures.length === 0 ? (
                <div className="rounded-lg border border-dashed border-slate-700 px-3 py-3 text-xs text-slate-500">
                  暂未识别到典型孔/型腔/凸台特征，当前仍可按外形粗加工生成刀路。
                </div>
              ) : (
                <div className="space-y-2">
                  {manufacturingFeatures.slice(0, 6).map((feature, index) => (
                    <div key={`${feature.type}-${feature.face_id ?? index}`} className="rounded-lg border border-slate-800 bg-slate-950/40 px-3 py-2 text-xs">
                      <div className="flex items-center justify-between gap-3">
                        <span className="font-medium text-slate-200">{formatFeatureType(feature.type)}</span>
                        <span className="text-slate-500">Face #{feature.face_id ?? '-'}</span>
                      </div>
                      <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-slate-400">
                        {feature.diameter !== undefined && <span>直径: <span className="font-mono text-cyan-300">{feature.diameter.toFixed(2)} mm</span></span>}
                        {feature.depth !== undefined && <span>深度: <span className="font-mono text-cyan-300">{feature.depth.toFixed(2)} mm</span></span>}
                        {feature.height !== undefined && <span>高度: <span className="font-mono text-cyan-300">{feature.height.toFixed(2)} mm</span></span>}
                        {feature.axis && <span>轴向: <span className="font-mono text-cyan-300 uppercase">{feature.axis}</span></span>}
                        {feature.bounds?.x !== undefined && feature.bounds?.y !== undefined && (
                          <span>范围: <span className="font-mono text-cyan-300">{feature.bounds.x.toFixed(2)} x {feature.bounds.y.toFixed(2)} mm</span></span>
                        )}
                      </div>
                    </div>
                  ))}
                  {manufacturingFeatures.length > 6 && (
                    <div className="text-[11px] text-slate-500">
                      其余 {manufacturingFeatures.length - 6} 项已省略显示。
                    </div>
                  )}
                </div>
              )}
            </div>
          )}

          {/* 工艺参数面板 — 可编辑 */}
          {craftsmanParams && (
            <div className="space-y-3">
              <div className="flex items-center gap-2">
                <Settings className="w-4 h-4 text-indigo-400" />
                <h2 className="font-semibold text-sm text-slate-200">工艺参数</h2>
                {craftsmanParams.is_guessed && (
                  <span className="ml-auto text-[10px] px-1.5 py-0.5 rounded bg-amber-900/50 text-amber-400 border border-amber-700/40">默认值</span>
                )}
                {!craftsmanParams.is_guessed && (
                  <span className="ml-auto text-[10px] px-1.5 py-0.5 rounded bg-emerald-900/50 text-emerald-400 border border-emerald-700/40">专家推荐</span>
                )}
              </div>

              {craftsmanParams.confidence_distance !== undefined && !craftsmanParams.is_guessed && (
                <div className="text-[11px] text-slate-500">匹配置信距离: {craftsmanParams.confidence_distance}</div>
              )}

              <ParamInput label="背吃刀量 (Step Down)" unit="mm"
                value={editParams.rough_step_down}
                onChange={v => setEditParams(p => ({ ...p, rough_step_down: v }))} />
              <ParamInput label="主轴转速 (Spindle)" unit="rpm"
                value={editParams.spindle_speed}
                onChange={v => setEditParams(p => ({ ...p, spindle_speed: v }))} />
              <ParamInput label="进给率 (Feed Rate)" unit="mm/min"
                value={editParams.feed_rate}
                onChange={v => setEditParams(p => ({ ...p, feed_rate: v }))} />
            </div>
          )}

          {/* 刀具选配方案 */}
          {toolPlan && (
            <div className="bg-slate-900/60 rounded-lg border border-slate-700 p-4 space-y-3">
              <div className="flex items-center gap-2">
                <Wrench className="w-4 h-4 text-violet-400" />
                <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wide">刀具选配方案</h3>
              </div>

              <div className="rounded-lg border border-violet-500/20 bg-violet-950/20 px-3 py-2 text-xs">
                <div className="flex items-center justify-between">
                  <span className="text-slate-400">粗加工刀具</span>
                  <span className="font-mono text-violet-300 font-medium">{toolPlan.roughing_tool.name}</span>
                </div>
                <div className="flex items-center justify-between mt-1">
                  <span className="text-slate-500">直径</span>
                  <span className="font-mono text-violet-300">{toolPlan.roughing_tool.diameter} mm</span>
                </div>
              </div>

              {toolPlan.feature_tools.length > 0 && (
                <div className="space-y-2">
                  <div className="text-[11px] text-slate-500">特征精加工刀具</div>
                  {toolPlan.feature_tools.map((entry, idx) => (
                    <div key={`ft-${entry.feature_face_id ?? idx}`} className="rounded-lg border border-slate-800 bg-slate-950/40 px-3 py-2 text-xs">
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-slate-200 font-medium">{formatFeatureType(entry.feature_type)}</span>
                        {entry.tool ? (
                          <span className="font-mono text-cyan-300">D{entry.tool.diameter}</span>
                        ) : (
                          <span className="text-red-400">无匹配</span>
                        )}
                      </div>
                      <div className="mt-1 text-slate-500">{entry.reason}</div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* G-Code 结果 */}
          {gcodeResult && (
            <div className="bg-emerald-950/30 border border-emerald-700/30 rounded-lg p-4 space-y-2">
              <div className="flex items-center gap-2 text-emerald-400 text-sm font-semibold">
                <CheckCircle2 className="w-4 h-4" />
                G-Code 已生成
              </div>
              <div className="text-xs text-slate-400">
                预计加工时间: <span className="text-slate-200 font-mono">{gcodeResult.estimated_time_minutes} min</span>
              </div>
              <a
                href={`${API}${gcodeResult.gcode_url}`}
                download
                className="flex items-center justify-center gap-2 w-full py-2 mt-1 bg-emerald-600/20 hover:bg-emerald-600/30 border border-emerald-600/40 rounded-lg text-emerald-400 text-sm font-medium transition-colors"
              >
                <Download className="w-4 h-4" />
                下载 .nc 文件
              </a>
            </div>
          )}

          <div className="bg-slate-900/60 rounded-lg border border-slate-700 p-4 space-y-3">
            <div className="flex items-center justify-between gap-3">
              <div className="flex items-center gap-2">
                <FolderClock className="w-4 h-4 text-cyan-400" />
                <h3 className="text-sm font-semibold text-slate-200">最近作业</h3>
              </div>
              <button
                type="button"
                onClick={() => void loadRecentJobs()}
                className="inline-flex items-center gap-1 rounded-md border border-slate-700 px-2 py-1 text-[11px] text-slate-400 transition-colors hover:border-cyan-500/40 hover:text-cyan-300"
              >
                <RotateCw className={`w-3.5 h-3.5 ${jobsLoading ? 'animate-spin' : ''}`} />
                刷新
              </button>
            </div>

            <div className="space-y-2 max-h-56 overflow-y-auto pr-1 custom-scrollbar">
              {recentJobs.length === 0 && !jobsLoading && (
                <div className="rounded-lg border border-dashed border-slate-700 px-3 py-4 text-center text-xs text-slate-500">
                  暂无历史作业，上传一个 STEP 文件后会显示在这里。
                </div>
              )}

              {recentJobs.map((job) => (
                <button
                  key={job.job_id}
                  type="button"
                  onClick={() => void loadJobDetail(job.job_id)}
                  className={`w-full rounded-lg border px-3 py-3 text-left transition-all ${currentJob?.job_id === job.job_id ? 'border-cyan-500/50 bg-cyan-950/20' : 'border-slate-700 bg-slate-950/40 hover:border-slate-500'}`}
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="truncate text-sm font-medium text-slate-100">{job.filename}</div>
                      <div className="mt-1 text-[11px] text-slate-500">{formatJobTime(job.updated_at || job.created_at)}</div>
                    </div>
                    <StatusBadge status={job.status} compact />
                  </div>

                  <div className="mt-3 flex items-center justify-between text-[11px] text-slate-400">
                    <span>阶段: {formatStage(job.stage)}</span>
                    <span>{job.progress ?? 0}%</span>
                  </div>
                  <div className="mt-1 h-1.5 rounded-full bg-slate-800 overflow-hidden">
                    <div
                      className={`h-full rounded-full ${job.status === 'failed' ? 'bg-red-500' : job.status === 'done' ? 'bg-emerald-500' : 'bg-cyan-500'}`}
                      style={{ width: `${Math.max(4, Math.min(100, job.progress ?? 0))}%` }}
                    />
                  </div>

                  {job.error_message && (
                    <div className="mt-2 line-clamp-2 text-[11px] text-red-300">
                      {job.error_code ? `${job.error_code}: ` : ''}{job.error_message}
                    </div>
                  )}
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* 底部生成按钮 */}
        <div className="p-5 pt-3 border-t border-slate-700/60">
          <button
            onClick={handleGenerate}
            disabled={!craftsmanParams || status === 'generating'}
            className="flex items-center justify-center gap-2 w-full py-3 bg-gradient-to-r from-cyan-500 to-blue-600 hover:from-cyan-400 hover:to-blue-500 disabled:opacity-40 disabled:cursor-not-allowed rounded-lg font-semibold shadow-lg shadow-cyan-500/20 transition-all hover:scale-[1.02] active:scale-95"
          >
            {status === 'generating' ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Play className="w-4 h-4" />
            )}
            {status === 'generating' ? '正在生成...' : '生成 G-Code'}
          </button>
        </div>
      </div>

      {/* ====== 3D 预览区 ====== */}
      <div className="flex-1 relative bg-slate-900">
        {/* 顶部工具栏 */}
        {modelData && modelData.render_url && (
          <div className="absolute top-4 left-4 z-20 flex items-center gap-1 bg-slate-800/90 backdrop-blur rounded-lg border border-slate-700 p-1">
            <ToolbarBtn icon={<Move3d className="w-4 h-4" />} label="旋转/平移"
              active={viewMode === 'orbit'} onClick={() => setViewMode('orbit')} />
            <ToolbarBtn icon={<Ruler className="w-4 h-4" />} label="测量"
              active={viewMode === 'measure'} onClick={() => setViewMode('measure')} />
            <ToolbarBtn icon={<Crosshair className="w-4 h-4" />} label="选择装夹面"
              active={viewMode === 'select_face'} onClick={() => setViewMode('select_face')} />
            {toolpathSegments.length > 0 && (
              <>
                <div className="w-px h-5 bg-slate-600 mx-1" />
                <ToolbarBtn
                  icon={showToolpath ? <Eye className="w-4 h-4" /> : <EyeOff className="w-4 h-4" />}
                  label={showToolpath ? '隐藏刀路' : '显示刀路'}
                  active={showToolpath}
                  onClick={() => setShowToolpath(v => !v)}
                />
              </>
            )}
          </div>
        )}

        {/* 状态提示条 */}
        {modelData && modelData.render_url && (
          <div className="absolute bottom-4 left-4 z-20 flex items-center gap-3 text-xs">
            {viewMode === 'measure' && measureResult && (
              <div className="bg-slate-800/90 backdrop-blur rounded-lg border border-yellow-500/40 px-3 py-1.5 text-yellow-400 font-mono">
                距离: {measureResult.distance.toFixed(2)} mm
              </div>
            )}
            {viewMode === 'measure' && !measureResult && (
              <div className="bg-slate-800/90 backdrop-blur rounded-lg border border-slate-600 px-3 py-1.5 text-slate-400">
                点击模型上两点进行测量
              </div>
            )}
            {viewMode === 'select_face' && (
              <div className="bg-slate-800/90 backdrop-blur rounded-lg border border-amber-600/40 px-3 py-1.5 text-amber-400">
                {selectedFace ? '已选择装夹面 — 法向标注为黄色箭头' : '点击模型表面选择装夹底面'}
              </div>
            )}
            {toolpathSegments.length > 0 && showToolpath && (
              <div className="bg-slate-800/90 backdrop-blur rounded-lg border border-slate-600 px-3 py-1.5 flex items-center gap-3">
                <span className="flex items-center gap-1"><span className="w-3 h-0.5 bg-red-500 inline-block" /> G0 快移</span>
                <span className="flex items-center gap-1"><span className="w-3 h-0.5 bg-cyan-400 inline-block" /> G1 切削</span>
              </div>
            )}
          </div>
        )}

        {modelData && modelData.render_url ? (
          <ErrorBoundary>
            <ModelViewer
              renderUrl={`${API}${modelData.render_url}`}
              topology={modelData.topology}
              mode={viewMode}
              selectedFace={selectedFace}
              onFaceSelect={setSelectedFace}
              onMeasure={setMeasureResult}
              toolpathSegments={toolpathSegments}
              showToolpath={showToolpath}
            />
          </ErrorBoundary>
        ) : (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 text-slate-600">
            {status === 'uploading' ? (
              <>
                <Loader2 className="w-12 h-12 animate-spin text-cyan-600/40" />
                <span className="text-sm font-medium">正在解析模型...</span>
              </>
            ) : modelData ? (
              <>
                <Box className="w-12 h-12 text-slate-700" />
                <span className="text-sm font-medium">模型预览不可用</span>
                <span className="text-xs text-slate-700">Mock 模式下未生成渲染文件，工艺参数仍可正常使用</span>
              </>
            ) : (
              <>
                <Box className="w-12 h-12 text-slate-700" />
                <span className="text-sm font-medium">上传 STEP 文件以开始</span>
                <span className="text-xs text-slate-700">支持 .step / .stp 格式的 CAD 模型</span>
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function StatusBadge({ status, compact = false }: { status?: string; compact?: boolean }) {
  const classes = status === 'done'
    ? 'border-emerald-500/30 bg-emerald-950/40 text-emerald-300'
    : status === 'failed'
      ? 'border-red-500/30 bg-red-950/40 text-red-300'
      : status === 'parsed_mock'
        ? 'border-amber-500/30 bg-amber-950/40 text-amber-300'
        : 'border-cyan-500/30 bg-cyan-950/30 text-cyan-300';

  return (
    <span className={`inline-flex items-center rounded-full border py-1 text-[11px] font-medium ${compact ? 'px-2' : 'px-2.5'} ${classes}`}>
      {formatJobStatus(status)}
    </span>
  );
}

function InfoItem({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-950/40 px-3 py-2">
      <div className="text-[11px] text-slate-500">{label}</div>
      <div className={`mt-1 text-xs text-slate-100 ${mono ? 'font-mono' : ''}`}>{value}</div>
    </div>
  );
}

/* ===== 可编辑参数行组件 ===== */
function ParamInput({ label, unit, value, onChange }: {
  label: string; unit: string; value: number;
  onChange: (v: number) => void;
}) {
  return (
    <div className="flex items-center justify-between gap-3 bg-slate-900/50 rounded-lg border border-slate-700 px-3 py-2">
      <span className="text-xs text-slate-400 shrink-0">{label}</span>
      <div className="flex items-center gap-1">
        <input
          type="number"
          value={value}
          onChange={e => onChange(parseFloat(e.target.value) || 0)}
          className="w-20 bg-transparent text-right font-mono text-sm text-cyan-400 outline-none border-b border-transparent focus:border-cyan-500 transition-colors [appearance:textfield] [&::-webkit-outer-spin-button]:appearance-none [&::-webkit-inner-spin-button]:appearance-none"
        />
        <span className="text-[11px] text-slate-500 w-12 text-right">{unit}</span>
      </div>
    </div>
  );
}

/* ===== 工具栏按钮 ===== */
function ToolbarBtn({ icon, label, active, onClick }: {
  icon: React.ReactNode; label: string; active: boolean; onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      title={label}
      className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-md text-xs font-medium transition-all
        ${active
          ? 'bg-cyan-500/20 text-cyan-400 border border-cyan-500/40'
          : 'text-slate-400 hover:text-slate-200 hover:bg-slate-700/60 border border-transparent'}`}
    >
      {icon}
      <span className="hidden lg:inline">{label}</span>
    </button>
  );
}

export default App;
