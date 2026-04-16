import { Wrench } from 'lucide-react';
import type { ToolPlan } from '../../types';
import { formatFeatureType } from '../../types';
import SectionCard from '../ui/SectionCard';

interface ToolPlanCardProps {
  plan: ToolPlan;
}

export default function ToolPlanCard({ plan }: ToolPlanCardProps) {
  return (
    <SectionCard
      icon={<Wrench className="w-4 h-4" />}
      title="刀具选配方案"
    >
      <div className="space-y-2.5">
        <div className="rounded-lg border border-violet-500/20 bg-violet-500/5 px-3 py-2.5">
          <div className="flex items-center justify-between text-xs">
            <span className="text-slate-400">粗加工刀具</span>
            <span className="font-mono font-medium text-violet-300">{plan.roughing_tool.name}</span>
          </div>
          <div className="flex items-center justify-between text-[11px] mt-1">
            <span className="text-slate-500">直径</span>
            <span className="font-mono text-violet-300/80">{plan.roughing_tool.diameter} mm</span>
          </div>
        </div>

        {plan.feature_tools.length > 0 && (
          <div className="space-y-1.5">
            <div className="text-[11px] text-slate-500 font-medium">特征精加工刀具</div>
            {plan.feature_tools.map((entry, idx) => (
              <div
                key={`ft-${entry.feature_face_id ?? idx}`}
                className="rounded-lg bg-slate-800/30 border border-slate-700/30 px-3 py-2 text-xs"
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="text-slate-200 font-medium">{formatFeatureType(entry.feature_type)}</span>
                  {entry.tool ? (
                    <span className="font-mono text-cyan-300">D{entry.tool.diameter}</span>
                  ) : (
                    <span className="text-red-400 text-[11px]">无匹配</span>
                  )}
                </div>
                <div className="mt-1 text-[11px] text-slate-500">{entry.reason}</div>
              </div>
            ))}
          </div>
        )}
      </div>
    </SectionCard>
  );
}
