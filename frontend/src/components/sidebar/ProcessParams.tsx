import { Settings } from 'lucide-react';
import type { EditableParams } from '../../types';
import SectionCard from '../ui/SectionCard';
import ExpertBadge from '../ui/ExpertBadge';

interface ProcessParamsProps {
  params: EditableParams;
  isGuessed: boolean;
  onChange: (params: EditableParams) => void;
}

export default function ProcessParams({ params, isGuessed, onChange }: ProcessParamsProps) {
  const update = (key: keyof EditableParams, value: number) =>
    onChange({ ...params, [key]: value });

  return (
    <SectionCard
      icon={<Settings className="w-4 h-4" />}
      title="工艺参数"
      badge={<ExpertBadge guessed={isGuessed} />}
    >
      <div className="space-y-2">
        <ParamRow
          label="背吃刀量"
          value={params.rough_step_down}
          unit="mm"
          onChange={v => update('rough_step_down', v)}
        />
        <ParamRow
          label="主轴转速"
          value={params.spindle_speed}
          unit="rpm"
          onChange={v => update('spindle_speed', v)}
        />
        <ParamRow
          label="进给率"
          value={params.feed_rate}
          unit="mm/min"
          onChange={v => update('feed_rate', v)}
        />
      </div>
    </SectionCard>
  );
}

function ParamRow({ label, value, unit, onChange }: {
  label: string;
  value: number;
  unit: string;
  onChange: (v: number) => void;
}) {
  return (
    <div className="flex items-center justify-between gap-2 rounded-lg bg-slate-800/30 border border-slate-700/30 px-3 py-2">
      <span className="text-xs text-slate-400 shrink-0">{label}</span>
      <div className="flex items-center gap-1.5">
        <input
          type="number"
          value={value}
          onChange={e => onChange(parseFloat(e.target.value) || 0)}
          className="w-20 bg-transparent text-right font-mono text-sm text-cyan-400 outline-none border-b border-transparent focus:border-cyan-500/60 transition-colors [appearance:textfield] [&::-webkit-outer-spin-button]:appearance-none [&::-webkit-inner-spin-button]:appearance-none"
        />
        <span className="text-[10px] text-slate-500 w-11 text-right">{unit}</span>
      </div>
    </div>
  );
}
