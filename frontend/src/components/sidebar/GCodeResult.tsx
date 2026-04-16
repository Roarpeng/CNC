import { CheckCircle2, Download } from 'lucide-react';

interface GCodeResultProps {
  gcodeUrl: string;
  estimatedTime?: number;
  apiBase: string;
}

export default function GCodeResult({ gcodeUrl, estimatedTime, apiBase }: GCodeResultProps) {
  return (
    <div className="rounded-xl border border-emerald-500/20 bg-emerald-500/5 backdrop-blur-sm">
      <div className="flex items-center gap-2.5 px-4 py-3 border-b border-emerald-500/10">
        <CheckCircle2 className="w-4 h-4 text-emerald-400" />
        <h3 className="text-[13px] font-semibold text-emerald-400">G-Code 已生成</h3>
      </div>
      <div className="px-4 py-3 space-y-3">
        {estimatedTime !== undefined && (
          <div className="text-xs text-slate-400">
            预计加工时间: <span className="font-mono text-slate-200">{estimatedTime} min</span>
          </div>
        )}
        <a
          href={`${apiBase}${gcodeUrl}`}
          download
          className="flex items-center justify-center gap-2 w-full py-2.5 rounded-lg border border-emerald-500/30 bg-emerald-500/10 text-emerald-400 text-sm font-medium transition-all hover:bg-emerald-500/20 active:scale-[0.98]"
        >
          <Download className="w-4 h-4" />
          下载 .nc 文件
        </a>
      </div>
    </div>
  );
}
