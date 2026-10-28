import logoFullUrl from '@/assets/logo.jpeg';
import logoMarkUrl from '@/assets/logo-mark.png';
import { cn } from '@/lib/cn';

/**
 * The Jade GCC brand (DECISIONS D25). `mark` (default): the logo's illustration on a small white tile plus the
 * wordmark, for the sidebar and headers. `full`: the whole lockup (illustration + "JADE GLOBAL | GCC") on its
 * white plate, where there is room. The asset has a white background, hence the plates on dark surfaces.
 */
export function Logo({
  compact,
  variant = 'mark',
  className,
}: {
  compact?: boolean;
  variant?: 'mark' | 'full';
  className?: string;
}) {
  if (variant === 'full') {
    return (
      <span
        className={cn(
          'inline-flex overflow-hidden rounded-2xl bg-white shadow-lg ring-1 ring-black/5',
          className,
        )}
      >
        <img
          src={logoFullUrl}
          alt="Jade Global GCC"
          width={512}
          height={512}
          className="h-full w-full object-contain"
        />
      </span>
    );
  }
  return (
    <span className={cn('inline-flex items-center gap-2.5', className)}>
      <span className="inline-flex h-9 w-9 shrink-0 items-center justify-center overflow-hidden rounded-lg bg-white shadow-sm ring-1 ring-black/5">
        <img src={logoMarkUrl} alt="" width={36} height={36} className="h-9 w-9 object-contain" />
      </span>
      {!compact ? (
        <span className="flex flex-col leading-none">
          <span className="text-sm font-semibold tracking-tight text-text">Jade GCC</span>
          <span className="mt-0.5 text-[10px] font-medium uppercase tracking-[0.14em] text-text-subtle">
            DC Monitoring
          </span>
        </span>
      ) : (
        <span className="sr-only">Jade GCC</span>
      )}
    </span>
  );
}
