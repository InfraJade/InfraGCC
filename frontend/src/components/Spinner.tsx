import { cn } from '@/lib/cn';

export function Spinner({
  size = 16,
  label,
  className,
}: {
  size?: number;
  label?: string;
  className?: string;
}) {
  return (
    <span role={label ? 'status' : undefined} className={cn('inline-flex items-center gap-2', className)}>
      <svg
        width={size}
        height={size}
        viewBox="0 0 24 24"
        fill="none"
        aria-hidden="true"
        className="animate-spin motion-reduce:animate-none"
      >
        <circle cx="12" cy="12" r="9" stroke="currentColor" strokeOpacity="0.2" strokeWidth="3" />
        <path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
      </svg>
      {label ? <span className="text-sm text-text-muted">{label}</span> : null}
    </span>
  );
}

export function FullPageSpinner({ label = 'Loading…' }: { label?: string }) {
  return (
    <div className="flex min-h-screen items-center justify-center text-accent">
      <Spinner size={28} label={label} />
    </div>
  );
}
