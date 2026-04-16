import { FileText } from 'lucide-react';
import type { JobSnapshot } from '../../types';
import { formatStage, formatJobTime } from '../../types';
import StatusBadge from '../ui/StatusBadge';

interface CurrentJobCardProps {
  job: JobSnapshot;
  progress: number;
}

export default function CurrentJobCard({ job, progress }: CurrentJobCardProps) {
  const barColor =
    job.status === 'failed' ? 'bg-red-500'
      : job.status === 'done' ? 'bg-emerald-500'
        : 'bg-cyan-500';

  return (
    <div className="rounded-xl border border-slate-700/60 bg-slate-900/50 backdrop-blur-sm">
      <div className="flex items-center gap-2.5 px-4 py-3 border-b border-slate-700/40">
        <FileText className="w-4 h-4 text-slate-400" />
        <h3 className="text-[13px] font-semibold text-slate-200 tracking-wide">当前作业</h3>
        <div className="ml-auto"><StatusBadge status={job.status} /></div>
      </div>

      <div className="px-4 py-3 space-y-3">
        <div className="text-sm font-medium text-slate-100 truncate">{job.filename}</div>

        <div className="grid grid-cols-2 gap-2">
          <MetaCell label="阶段" value={formatStage(job.stage)} />
          <MetaCell label="进度" value={`${progress}%`} />
          <MetaCell label="作业 ID" value={job.job_id.slice(0, 8)} mono />
          <MetaCell label="更新时间" value={formatJobTime(job.updated_at)} />
        </div>

        <div className="h-1.5 rounded-full bg-slate-800/80 overflow-hidden">
          <div
            className={`h-full rounded-full transition-all duration-500 ${barColor}`}
            style={{ width: `${Math.max(4, Math.min(100, progress))}%` }}
          />
        </div>

        {job.status === 'parsed_mock' && (
          <div className="rounded-lg border border-amber-500/20 bg-amber-500/5 px-3 py-2 text-[11px] text-amber-300/90 leading-relaxed">
            当前模型使用了降级解析结果，适合内部联调和流程验证。
          </div>
        )}
      </div>
    </div>
  );
}

function MetaCell({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="rounded-lg bg-slate-800/40 px-2.5 py-1.5">
      <div className="text-[10px] text-slate-500 uppercase tracking-wider">{label}</div>
      <div className={`mt-0.5 text-xs text-slate-200 ${mono ? 'font-mono' : ''}`}>{value}</div>
    </div>
  );
}
