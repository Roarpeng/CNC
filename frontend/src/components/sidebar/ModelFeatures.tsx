import { Box, Ruler, Layers } from 'lucide-react';
import SectionCard from '../ui/SectionCard';

interface ModelFeaturesProps {
  volume: number;
  bboxX: number;
  bboxY: number;
  zDepth: number;
}

export default function ModelFeatures({ volume, bboxX, bboxY, zDepth }: ModelFeaturesProps) {
  return (
    <SectionCard
      icon={<Box className="w-4 h-4" />}
      title="模型特征"
    >
      <div className="space-y-2">
        <Row icon={<Box className="w-3.5 h-3.5 text-cyan-500/70" />} label="体积" value={`${volume.toFixed(1)}`} unit="mm³" />
        <Row icon={<Ruler className="w-3.5 h-3.5 text-cyan-500/70" />} label="尺寸 (X×Y)" value={`${bboxX.toFixed(1)} × ${bboxY.toFixed(1)}`} unit="mm" />
        <Row icon={<Layers className="w-3.5 h-3.5 text-cyan-500/70" />} label="最大深度 (Z)" value={`${zDepth.toFixed(1)}`} unit="mm" />
      </div>
    </SectionCard>
  );
}

function Row({ icon, label, value, unit }: { icon: React.ReactNode; label: string; value: string; unit: string }) {
  return (
    <div className="flex items-center justify-between gap-2">
      <div className="flex items-center gap-2">
        {icon}
        <span className="text-xs text-slate-400">{label}</span>
      </div>
      <span className="font-mono text-xs text-cyan-400">
        {value} <span className="text-cyan-600 text-[10px]">{unit}</span>
      </span>
    </div>
  );
}
