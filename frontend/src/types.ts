import type { ToolpathSegment } from './components/ToolpathViewer';

export type Status = 'idle' | 'uploading' | 'uploaded' | 'generating' | 'done' | 'error';

export type JobSnapshot = {
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

export type ManufacturingFeature = {
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

export type ToolInfo = {
  id: number;
  diameter: number;
  name: string;
  type: string;
  flutes?: number;
};

export type FeatureToolEntry = {
  feature_type: string;
  feature_face_id?: number;
  diameter?: number;
  depth?: number;
  bounds?: { x?: number; y?: number };
  tool: ToolInfo | null;
  reason: string;
};

export type ToolPlan = {
  roughing_tool: ToolInfo;
  feature_tools: FeatureToolEntry[];
};

export type EditableParams = {
  rough_step_down: number;
  spindle_speed: number;
  feed_rate: number;
  rough_tool_id: number;
};

export function mapJobStatus(status?: string): Status {
  if (status === 'done') return 'done';
  if (status === 'failed') return 'error';
  if (status === 'generating') return 'generating';
  if (status === 'parsed' || status === 'parsed_mock' || status === 'uploaded') return 'uploaded';
  return 'idle';
}

export function formatJobStatus(status?: string) {
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

export function formatStage(stage?: string | null) {
  switch (stage) {
    case 'queued': return '等待';
    case 'parsing': return '解析';
    case 'meshing': return '网格化';
    case 'cam': return '刀路';
    case 'completed': return '完成';
    default: return '未开始';
  }
}

export function formatJobTime(value?: string) {
  if (!value) return '未知';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '未知';
  return date.toLocaleString('zh-CN', { hour12: false });
}

export function formatFeatureType(type: string) {
  switch (type) {
    case 'hole': return '孔';
    case 'pocket': return '型腔';
    case 'boss': return '凸台';
    default: return type;
  }
}
