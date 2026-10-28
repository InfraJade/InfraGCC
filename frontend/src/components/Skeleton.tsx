import { cn } from '@/lib/cn';

export interface SkeletonProps {
  className?: string;
  /** Render N text lines (last one shorter). */
  lines?: number;
  /** Visually hidden loading label for screen readers (only on the outermost skeleton). */
  label?: string;
}

/** Shimmering placeholder. Purely visual; pass `label` once per loading region. */
export function Skeleton({ className, lines, label }: SkeletonProps) {
  if (lines && lines > 1) {
    return (
      <div className={cn('flex flex-col gap-2', className)} aria-busy="true">
        {label ? <span className="sr-only">{label}</span> : null}
        {Array.from({ length: lines }, (_, i) => (
          <div key={i} className={cn('skeleton h-3 rounded', i === lines - 1 ? 'w-2/3' : 'w-full')} />
        ))}
      </div>
    );
  }
  return (
    <div className={cn('skeleton h-4 rounded', className)} aria-busy={label ? true : undefined}>
      {label ? <span className="sr-only">{label}</span> : null}
    </div>
  );
}

export function SkeletonCard({ className }: { className?: string }) {
  return (
    <div className={cn('glass rounded-xl p-5', className)}>
      <Skeleton className="mb-4 h-3 w-1/3" />
      <Skeleton className="mb-2 h-8 w-1/2" />
      <Skeleton className="h-3 w-1/4" />
    </div>
  );
}
