export default function ExpertBadge({ guessed = false }: { guessed?: boolean }) {
  if (guessed) {
    return (
      <span className="ml-auto inline-flex items-center gap-1 rounded-full border border-amber-600/30 bg-amber-500/10 px-2 py-0.5 text-[10px] font-medium text-amber-400">
        <span className="w-1 h-1 rounded-full bg-amber-400" />
        默认值
      </span>
    );
  }
  return (
    <span className="ml-auto inline-flex items-center gap-1 rounded-full border border-emerald-600/30 bg-emerald-500/10 px-2 py-0.5 text-[10px] font-medium text-emerald-400">
      <span className="w-1 h-1 rounded-full bg-emerald-400" />
      专家推荐
    </span>
  );
}
