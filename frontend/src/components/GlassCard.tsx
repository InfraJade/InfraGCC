import { forwardRef, type HTMLAttributes, type ReactNode } from 'react';

import { cn } from '@/lib/cn';

export interface GlassCardProps extends Omit<HTMLAttributes<HTMLDivElement>, 'title'> {
  /** Glass strength: subtle (nested), base (default), strong (popovers, dialogs). */
  tone?: 'subtle' | 'base' | 'strong';
  padding?: 'none' | 'sm' | 'md' | 'lg';
  /** Hover lift + pointer for clickable cards (still wrap in a link/button for semantics). */
  interactive?: boolean;
  /** Optional header row. */
  title?: ReactNode;
  actions?: ReactNode;
  as?: 'div' | 'section' | 'article' | 'aside';
}

const pad = { none: '', sm: 'p-3', md: 'p-4 sm:p-5', lg: 'p-6 sm:p-7' } as const;
const toneClass = { subtle: 'glass-subtle', base: 'glass', strong: 'glass-strong' } as const;

export const GlassCard = forwardRef<HTMLDivElement, GlassCardProps>(function GlassCard(
  {
    tone = 'base',
    padding = 'md',
    interactive,
    title,
    actions,
    as: Tag = 'div',
    className,
    children,
    ...rest
  },
  ref,
) {
  return (
    <Tag
      ref={ref}
      className={cn(
        'relative rounded-xl',
        toneClass[tone],
        pad[padding],
        interactive &&
          'cursor-pointer transition duration-base ease-standard hover:-translate-y-0.5 hover:shadow-lg focus-within:shadow-lg',
        className,
      )}
      {...rest}
    >
      {title || actions ? (
        <div className="mb-3 flex items-center justify-between gap-3">
          {title ? <h2 className="text-sm font-semibold tracking-wide text-text">{title}</h2> : <span />}
          {actions ? <div className="flex items-center gap-2">{actions}</div> : null}
        </div>
      ) : null}
      {children}
    </Tag>
  );
});
