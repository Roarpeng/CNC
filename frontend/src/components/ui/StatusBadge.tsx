import { formatJobStatus } from '../../types';

const VARIANTS: Record<string, string> = {
  done: 'border-emerald-500/30 bg-emerald-500/10 text-emerald-400',
  failed: 'border-red-500/30 bg-red-500/10 text-red-400',
  parsed_mock: 'border-amber-500/30 bg-amber-500/10 text-amber-400',
  _default: 'border-cyan-500/30 bg-cyan-500/10 text-cyan-400',
};

export default function StatusBadge({ status, compact = false }: { status?: string; compact?: boolean }) {
  const cls = VARIANTS[status ?? ''] ?? VARIANTS._default;
  return (
    <span className={`inline-flex items-center rounded-full border text-[11px] font-medium leading-none ${compact ? 'px-2 py-1' : 'px-2.5 py-1'} ${cls}`}>
      {formatJobStatus(status)}
    </span>
  );
}
