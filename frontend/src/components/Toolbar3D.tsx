import { Move3d, Ruler, Crosshair, Eye, EyeOff } from 'lucide-react';
import type { InteractionMode } from './ModelViewer';

interface Toolbar3DProps {
  mode: InteractionMode;
  onModeChange: (mode: InteractionMode) => void;
  hasToolpath: boolean;
  showToolpath: boolean;
  onToggleToolpath: () => void;
}

export default function Toolbar3D({ mode, onModeChange, hasToolpath, showToolpath, onToggleToolpath }: Toolbar3DProps) {
  return (
    <div className="flex items-center gap-0.5 bg-slate-800/80 backdrop-blur-md rounded-xl border border-slate-700/50 p-1 shadow-xl">
      <Btn
        icon={<Move3d className="w-4 h-4" />}
        label="旋转/平移"
        active={mode === 'orbit'}
        onClick={() => onModeChange('orbit')}
      />
      <Btn
        icon={<Ruler className="w-4 h-4" />}
        label="测量"
        active={mode === 'measure'}
        onClick={() => onModeChange('measure')}
      />
      <Btn
        icon={<Crosshair className="w-4 h-4" />}
        label="选择装夹面"
        active={mode === 'select_face'}
        onClick={() => onModeChange('select_face')}
      />

      {hasToolpath && (
        <>
          <div className="w-px h-5 bg-slate-600/50 mx-1" />
          <Btn
            icon={showToolpath ? <Eye className="w-4 h-4" /> : <EyeOff className="w-4 h-4" />}
            label={showToolpath ? '显示/隐藏刀路' : '显示/隐藏刀路'}
            active={showToolpath}
            onClick={onToggleToolpath}
          />
        </>
      )}
    </div>
  );
}

function Btn({ icon, label, active, onClick }: {
  icon: React.ReactNode;
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      title={label}
      className={`flex items-center gap-1.5 px-3 py-2 rounded-lg text-xs font-medium transition-all
        ${active
          ? 'bg-cyan-500/15 text-cyan-400 shadow-inner'
          : 'text-slate-400 hover:text-slate-200 hover:bg-slate-700/40'}`}
    >
      {icon}
      <span className="hidden lg:inline">{label}</span>
    </button>
  );
}
