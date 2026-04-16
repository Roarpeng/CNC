import { UploadCloud, Loader2 } from 'lucide-react';
import type { Status } from '../../types';

interface UploadAreaProps {
  status: Status;
  fileName?: string;
  onUpload: (e: React.ChangeEvent<HTMLInputElement>) => void;
}

export default function UploadArea({ status, fileName, onUpload }: UploadAreaProps) {
  const isDisabled = status === 'uploading' || status === 'generating';
  return (
    <div
      className={`relative border-2 border-dashed rounded-xl p-5 flex flex-col items-center justify-center gap-2 transition-all cursor-pointer group
        ${status === 'uploading'
          ? 'border-cyan-500/50 bg-cyan-500/5 pointer-events-none'
          : status === 'error'
            ? 'border-red-500/40 hover:border-red-400/60 bg-red-500/5'
            : 'border-slate-600/60 hover:border-cyan-400/60 hover:bg-cyan-500/5'}`}
    >
      <input
        type="file"
        className="absolute inset-0 opacity-0 cursor-pointer"
        accept=".step,.stp"
        onChange={onUpload}
        disabled={isDisabled}
      />
      {status === 'uploading' ? (
        <Loader2 className="w-7 h-7 text-cyan-400 animate-spin" />
      ) : (
        <UploadCloud className="w-7 h-7 text-slate-500 group-hover:text-cyan-400 transition-colors" />
      )}
      <span className="text-sm font-medium text-center leading-tight text-slate-300">
        {status === 'uploading' ? '解析处理中...' : fileName ?? '点击上传 STEP / STP 文件'}
      </span>
      {!fileName && (
        <span className="text-[11px] text-slate-500">支持 .step / .stp，最大 100 MB</span>
      )}
    </div>
  );
}
