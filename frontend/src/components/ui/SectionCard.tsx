import type { ReactNode } from 'react';

interface SectionCardProps {
  icon?: ReactNode;
  title: string;
  badge?: ReactNode;
  trailing?: ReactNode;
  children: ReactNode;
  className?: string;
}

export default function SectionCard({ icon, title, badge, trailing, children, className = '' }: SectionCardProps) {
  return (
    <div className={`rounded-xl border border-slate-700/60 bg-slate-900/50 backdrop-blur-sm ${className}`}>
      <div className="flex items-center gap-2.5 px-4 py-3 border-b border-slate-700/40">
        {icon && <span className="text-slate-400">{icon}</span>}
        <h3 className="text-[13px] font-semibold text-slate-200 tracking-wide">{title}</h3>
        {badge}
        {trailing && <div className="ml-auto">{trailing}</div>}
      </div>
      <div className="px-4 py-3">
        {children}
      </div>
    </div>
  );
}
