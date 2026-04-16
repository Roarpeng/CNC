import { FolderClock, RotateCw } from 'lucide-react';
import type { JobSnapshot } from '../../types';
import { formatStage, formatJobTime } from '../../types';
import StatusBadge from '../ui/StatusBadge';

interface RecentJobsProps {
  jobs: JobSnapshot[];
  loading: boolean;
  currentJobId?: string;
  onRefresh: () => void;
  onSelect: (jobId: string) => void;
}

export default function RecentJobs({ jobs, loading, currentJobId, onRefresh, onSelect }: RecentJobsProps) {
  return (
    <div className="rounded-xl border border-slate-700/60 bg-slate-900/50 backdrop-blur-sm">
      <div className="flex items-center gap-2.5 px-4 py-3 border-b border-slate-700/40">
        <FolderClock className="w-4 h-4 text-slate-400" />
        <h3 className="text-[13px] font-semibold text-slate-200 tracking-wide">最近作业</h3>
        <button
          type="button"
          onClick={onRefresh}
          className="ml-auto inline-flex items-center gap-1 rounded-md border border-slate-700/60 px-2 py-1 text-[11px] text-slate-400 transition-colors hover:border-cyan-500/40 hover:text-cyan-300"
        >
          <RotateCw className={`w-3 h-3 ${loading ? 'animate-spin' : ''}`} />
          刷新
        </button>
      </div>

      <div className="px-3 py-2 max-h-52 overflow-y-auto custom-scrollbar space-y-1.5">
        {jobs.length === 0 && !loading && (
          <div className="text-center text-xs text-slate-500 py-4">
            暂无历史作业
          </div>
        )}

        {jobs.map((job) => (
          <button
            key={job.job_id}
            type="button"
            onClick={() => onSelect(job.job_id)}
            className={`w-full rounded-lg border px-3 py-2.5 text-left transition-all ${
              currentJobId === job.job_id
                ? 'border-cyan-500/40 bg-cyan-500/5'
                : 'border-slate-700/40 bg-slate-800/20 hover:border-slate-600/60 hover:bg-slate-800/40'
            }`}
          >
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0">
                <div className="truncate text-xs font-medium text-slate-200">{job.filename}</div>
                <div className="mt-0.5 text-[10px] text-slate-500 font-mono">{formatJobTime(job.updated_at || job.created_at)}</div>
              </div>
              <StatusBadge status={job.status} compact />
            </div>

            <div className="mt-2 flex items-center justify-between text-[10px] text-slate-500">
              <span>{formatStage(job.stage)}</span>
              <span>{job.progress ?? 0}%</span>
            </div>
            <div className="mt-1 h-1 rounded-full bg-slate-800/60 overflow-hidden">
              <div
                className={`h-full rounded-full transition-all ${
                  job.status === 'failed' ? 'bg-red-500'
                    : job.status === 'done' ? 'bg-emerald-500'
                      : 'bg-cyan-500'
                }`}
                style={{ width: `${Math.max(4, Math.min(100, job.progress ?? 0))}%` }}
              />
            </div>

            {job.error_message && (
              <div className="mt-1.5 line-clamp-1 text-[10px] text-red-400">
                {job.error_code ? `${job.error_code}: ` : ''}{job.error_message}
              </div>
            )}
          </button>
        ))}
      </div>
    </div>
  );
}
