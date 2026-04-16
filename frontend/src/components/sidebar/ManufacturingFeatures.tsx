import { Scan } from 'lucide-react';
import type { ManufacturingFeature } from '../../types';
import { formatFeatureType } from '../../types';
import SectionCard from '../ui/SectionCard';
import ExpertBadge from '../ui/ExpertBadge';

interface ManufacturingFeaturesProps {
  features: ManufacturingFeature[];
  featureSummary: Record<string, number>;
}

export default function ManufacturingFeatures({ features, featureSummary }: ManufacturingFeaturesProps) {
  return (
    <SectionCard
      icon={<Scan className="w-4 h-4" />}
      title="加工特征识别"
      badge={<ExpertBadge />}
      trailing={<span className="text-[11px] text-slate-500">{features.length} 项</span>}
    >
      <div className="space-y-3">
        {Object.keys(featureSummary).length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {Object.entries(featureSummary).map(([key, value]) => (
              <span
                key={key}
                className="inline-flex items-center gap-1 rounded-md border border-cyan-500/20 bg-cyan-500/5 px-2 py-1 text-[11px] font-medium text-cyan-300"
              >
                {formatFeatureType(key)}
                <span className="text-cyan-500/60">×{value}</span>
              </span>
            ))}
          </div>
        )}

        {features.length === 0 ? (
          <div className="text-xs text-slate-500 leading-relaxed">
            暂未识别到典型孔/型腔/凸台特征，当前仍可按外形粗加工生成刀路。
          </div>
        ) : (
          <div className="space-y-1.5">
            {features.slice(0, 6).map((f, i) => (
              <FeatureRow key={`${f.type}-${f.face_id ?? i}`} feature={f} />
            ))}
            {features.length > 6 && (
              <div className="text-[11px] text-slate-500 pt-1">
                其余 {features.length - 6} 项已省略显示
              </div>
            )}
          </div>
        )}
      </div>
    </SectionCard>
  );
}

function FeatureRow({ feature }: { feature: ManufacturingFeature }) {
  return (
    <div className="rounded-lg bg-slate-800/30 border border-slate-700/30 px-3 py-2 text-xs">
      <div className="flex items-center justify-between">
        <span className="font-medium text-slate-200">{formatFeatureType(feature.type)}</span>
        <span className="text-slate-600 font-mono text-[10px]">#{feature.face_id ?? '-'}</span>
      </div>
      <div className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-slate-400">
        {feature.diameter !== undefined && (
          <span>∅ <span className="font-mono text-cyan-300">{feature.diameter.toFixed(2)}</span></span>
        )}
        {feature.depth !== undefined && (
          <span>深 <span className="font-mono text-cyan-300">{feature.depth.toFixed(2)}</span></span>
        )}
        {feature.height !== undefined && (
          <span>高 <span className="font-mono text-cyan-300">{feature.height.toFixed(2)}</span></span>
        )}
        {feature.bounds?.x !== undefined && feature.bounds?.y !== undefined && (
          <span>范围 <span className="font-mono text-cyan-300">{feature.bounds.x.toFixed(1)}×{feature.bounds.y.toFixed(1)}</span></span>
        )}
      </div>
    </div>
  );
}
