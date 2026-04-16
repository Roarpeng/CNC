import { useEffect, useState, useCallback } from 'react';
import axios from 'axios';
import { AlertTriangle, Box, Loader2, Play } from 'lucide-react';

import type { InteractionMode, SelectedFace, MeasureResult } from './components/ModelViewer';
import type { ToolpathSegment } from './components/ToolpathViewer';
import type { Status, JobSnapshot, ManufacturingFeature, ToolPlan, EditableParams } from './types';
import { mapJobStatus } from './types';

import ModelViewer from './components/ModelViewer';
import ErrorBoundary from './components/ErrorBoundary';
import Toolbar3D from './components/Toolbar3D';
import UploadArea from './components/sidebar/UploadArea';
import CurrentJobCard from './components/sidebar/CurrentJobCard';
import ModelFeatures from './components/sidebar/ModelFeatures';
import ManufacturingFeaturesCard from './components/sidebar/ManufacturingFeatures';
import ProcessParams from './components/sidebar/ProcessParams';
import ToolPlanCard from './components/sidebar/ToolPlanCard';
import GCodeResult from './components/sidebar/GCodeResult';
import RecentJobs from './components/sidebar/RecentJobs';

import './App.css';

const API = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';

export default function App() {
  const [file, setFile] = useState<File | null>(null);
  const [status, setStatus] = useState<Status>('idle');
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [modelData, setModelData] = useState<any>(null);
  const [currentJob, setCurrentJob] = useState<JobSnapshot | null>(null);
  const [recentJobs, setRecentJobs] = useState<JobSnapshot[]>([]);
  const [jobsLoading, setJobsLoading] = useState(false);
  const [craftsmanParams, setCraftsmanParams] = useState<any>(null);
  const [gcodeResult, setGcodeResult] = useState<any>(null);

  const [viewMode, setViewMode] = useState<InteractionMode>('orbit');
  const [selectedFace, setSelectedFace] = useState<SelectedFace | null>(null);
  const [measureResult, setMeasureResult] = useState<MeasureResult | null>(null);
  const [showToolpath, setShowToolpath] = useState(true);
  const [toolpathSegments, setToolpathSegments] = useState<ToolpathSegment[]>([]);
  const [toolPlan, setToolPlan] = useState<ToolPlan | null>(null);

  const [editParams, setEditParams] = useState<EditableParams>({
    rough_step_down: 2.0,
    spindle_speed: 4000,
    feed_rate: 800.0,
    rough_tool_id: 1,
  });

  useEffect(() => { void loadRecentJobs(); }, []);

  const syncJobToUi = useCallback((job: JobSnapshot) => {
    setCurrentJob(job);
    setStatus(mapJobStatus(job.status));
    setErrorMsg(job.error_message ? `${job.error_code ? `[${job.error_code}] ` : ''}${job.error_message}` : null);

    if (job.render_url || job.topology) {
      setModelData({ job_id: job.job_id, render_url: job.render_url, topology: job.topology });
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
  }, []);

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
      setErrorMsg(err?.response?.data?.detail || err?.message || '读取作业失败');
      setStatus('error');
    }
  };

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    if (!e.target.files || e.target.files.length === 0) return;
    const selectedFile = e.target.files[0];

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
      setErrorMsg(err?.response?.data?.detail || err?.message || '上传失败');
      setStatus('error');
    }
  };

  const fetchCraftsmanAdvice = async (features: any) => {
    try {
      const res = await axios.get(`${API}/api/v1/craftsman/recommend/`, {
        params: { volume: features.volume, max_depth: features.z_depth },
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
      if (res.data.toolpath_segments) setToolpathSegments(res.data.toolpath_segments);
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
      setErrorMsg(err?.response?.data?.detail || err?.message || 'G-Code 生成失败');
      setStatus('error');
    }
  };

  const features = modelData?.topology?.features;
  const manufacturingFeatures = (modelData?.topology?.manufacturing_features ?? []) as ManufacturingFeature[];
  const featureSummary = (modelData?.topology?.feature_summary ?? {}) as Record<string, number>;
  const currentProgress = currentJob?.progress ?? (status === 'done' ? 100 : status === 'uploaded' ? 100 : 0);
  const hasRenderUrl = modelData?.render_url;

  return (
    <div className="flex h-screen w-screen text-slate-200 overflow-hidden">
      {/* ═══════ LEFT SIDEBAR ═══════ */}
      <aside className="w-[360px] min-w-[320px] flex flex-col border-r border-slate-700/40 bg-slate-900/60 backdrop-blur-xl z-10">
        {/* Brand */}
        <header className="px-5 pt-5 pb-4 border-b border-slate-700/30">
          <h1 className="text-[22px] font-bold tracking-tight">
            <span className="bg-gradient-to-r from-cyan-400 to-blue-500 bg-clip-text text-transparent">
              Cloud CAM
            </span>
          </h1>
          <p className="text-[11px] text-slate-500 mt-0.5 tracking-wide">
            Intelligent CNC Path Generation
          </p>
        </header>

        {/* Scrollable cards */}
        <div className="flex-1 overflow-y-auto px-4 py-4 space-y-3 custom-scrollbar">
          <UploadArea
            status={status}
            fileName={file?.name}
            onUpload={handleUpload}
          />

          {errorMsg && (
            <div className="flex items-start gap-2 rounded-xl border border-red-500/20 bg-red-500/5 px-3 py-2.5 text-xs text-red-300/90">
              <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0 text-red-400" />
              <span className="leading-relaxed">{errorMsg}</span>
            </div>
          )}

          {currentJob && (
            <CurrentJobCard job={currentJob} progress={currentProgress} />
          )}

          {features && (
            <ManufacturingFeaturesCard
              features={manufacturingFeatures}
              featureSummary={featureSummary}
            />
          )}

          {features && (
            <ModelFeatures
              volume={features.volume}
              bboxX={features.bbox_x}
              bboxY={features.bbox_y}
              zDepth={features.z_depth}
            />
          )}

          {craftsmanParams && (
            <ProcessParams
              params={editParams}
              isGuessed={craftsmanParams.is_guessed}
              onChange={setEditParams}
            />
          )}

          {toolPlan && <ToolPlanCard plan={toolPlan} />}

          {gcodeResult && (
            <GCodeResult
              gcodeUrl={gcodeResult.gcode_url}
              estimatedTime={gcodeResult.estimated_time_minutes}
              apiBase={API}
            />
          )}

          <RecentJobs
            jobs={recentJobs}
            loading={jobsLoading}
            currentJobId={currentJob?.job_id}
            onRefresh={() => void loadRecentJobs()}
            onSelect={(id) => void loadJobDetail(id)}
          />
        </div>

        {/* Generate button */}
        <div className="px-4 py-3 border-t border-slate-700/30">
          <button
            onClick={handleGenerate}
            disabled={!craftsmanParams || status === 'generating'}
            className="flex items-center justify-center gap-2 w-full py-3 rounded-xl font-semibold text-white
              bg-gradient-to-r from-cyan-500 to-blue-600 hover:from-cyan-400 hover:to-blue-500
              disabled:opacity-30 disabled:cursor-not-allowed
              shadow-lg shadow-cyan-500/15 transition-all hover:shadow-cyan-500/25
              hover:scale-[1.01] active:scale-[0.98]"
          >
            {status === 'generating' ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Play className="w-4 h-4" />
            )}
            {status === 'generating' ? '正在生成...' : '生成 G-Code ▶'}
          </button>
        </div>
      </aside>

      {/* ═══════ RIGHT MAIN AREA — 3D VIEWER ═══════ */}
      <main className="flex-1 relative bg-[#0c1222]">
        {/* Toolbar */}
        {hasRenderUrl && (
          <div className="absolute top-4 left-4 z-20">
            <Toolbar3D
              mode={viewMode}
              onModeChange={setViewMode}
              hasToolpath={toolpathSegments.length > 0}
              showToolpath={showToolpath}
              onToggleToolpath={() => setShowToolpath(v => !v)}
            />
          </div>
        )}

        {/* Status hints */}
        {hasRenderUrl && (
          <div className="absolute bottom-4 left-4 z-20 flex items-center gap-2">
            {viewMode === 'measure' && measureResult && (
              <HintPill color="yellow">
                距离: <span className="font-mono">{measureResult.distance.toFixed(2)} mm</span>
              </HintPill>
            )}
            {viewMode === 'measure' && !measureResult && (
              <HintPill>点击模型上两点进行测量</HintPill>
            )}
            {viewMode === 'select_face' && (
              <HintPill color="amber">
                {selectedFace ? '已选择装夹面 — 箭头指示加工 Z 轴方向' : '点击模型表面选择装夹底面'}
              </HintPill>
            )}
            {toolpathSegments.length > 0 && showToolpath && (
              <HintPill>
                <span className="flex items-center gap-3">
                  <span className="flex items-center gap-1">
                    <span className="inline-block w-4 h-[2px] rounded bg-red-500" /> G0 快移
                  </span>
                  <span className="flex items-center gap-1">
                    <span className="inline-block w-4 h-[2px] rounded bg-cyan-400" /> G1 切削
                  </span>
                </span>
              </HintPill>
            )}
          </div>
        )}

        {/* 3D Canvas or placeholder */}
        {hasRenderUrl ? (
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
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-3">
            {status === 'uploading' ? (
              <>
                <Loader2 className="w-12 h-12 animate-spin text-cyan-500/30" />
                <span className="text-sm font-medium text-slate-500">正在解析模型...</span>
              </>
            ) : modelData ? (
              <>
                <Box className="w-12 h-12 text-slate-700" />
                <span className="text-sm font-medium text-slate-500">模型预览不可用</span>
                <span className="text-xs text-slate-600">Mock 模式下未生成渲染文件</span>
              </>
            ) : (
              <>
                <div className="w-20 h-20 rounded-2xl border-2 border-dashed border-slate-700/50 flex items-center justify-center">
                  <Box className="w-8 h-8 text-slate-700" />
                </div>
                <span className="text-sm font-medium text-slate-500 mt-2">上传 STEP 文件以开始</span>
                <span className="text-xs text-slate-600">支持 .step / .stp 格式的 CAD 模型</span>
              </>
            )}
          </div>
        )}
      </main>
    </div>
  );
}

function HintPill({ children, color }: { children: React.ReactNode; color?: 'yellow' | 'amber' }) {
  const border =
    color === 'yellow' ? 'border-yellow-500/30'
      : color === 'amber' ? 'border-amber-500/30'
        : 'border-slate-600/50';
  const text =
    color === 'yellow' ? 'text-yellow-400'
      : color === 'amber' ? 'text-amber-400'
        : 'text-slate-400';

  return (
    <div className={`bg-slate-800/80 backdrop-blur-md rounded-lg border ${border} px-3 py-1.5 text-xs ${text}`}>
      {children}
    </div>
  );
}
