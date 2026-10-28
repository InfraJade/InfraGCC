import { AnimatePresence, motion } from 'framer-motion';
import { useId, useRef, useState, type ReactNode } from 'react';

import { cn } from '@/lib/cn';

import { useDismiss } from './overlay';

export interface PopoverProps {
  /** Render the trigger; spread `props` on a button. */
  trigger: (props: {
    ref: React.RefObject<HTMLButtonElement>;
    onClick: () => void;
    'aria-expanded': boolean;
    'aria-controls': string;
    'aria-haspopup': 'dialog' | 'menu' | 'true';
  }) => ReactNode;
  children: ReactNode | ((close: () => void) => ReactNode);
  align?: 'start' | 'end';
  /** ARIA popup kind on the trigger. */
  kind?: 'dialog' | 'menu';
  className?: string;
  label?: string;
}

/** Anchored non-modal popup (column picker, user menu, alerts preview). Esc / outside click close it. */
export function Popover({
  trigger,
  children,
  align = 'end',
  kind = 'dialog',
  className,
  label,
}: PopoverProps) {
  const [open, setOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const id = useId();
  const close = () => {
    setOpen(false);
    triggerRef.current?.focus();
  };
  useDismiss([triggerRef, panelRef], open, () => setOpen(false));

  return (
    <div className="relative inline-block">
      {trigger({
        ref: triggerRef,
        onClick: () => setOpen((o) => !o),
        'aria-expanded': open,
        'aria-controls': id,
        'aria-haspopup': kind,
      })}
      <AnimatePresence>
        {open ? (
          <motion.div
            ref={panelRef}
            id={id}
            role={kind}
            onKeyDown={kind === 'menu' ? onMenuKeyDown : undefined}
            aria-label={label}
            initial={{ opacity: 0, y: -4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -4 }}
            transition={{ duration: 0.14 }}
            className={cn(
              'glass-strong absolute top-full z-dropdown mt-2 min-w-[12rem] rounded-lg p-1.5',
              align === 'end' ? 'right-0' : 'left-0',
              className,
            )}
          >
            {typeof children === 'function' ? children(close) : children}
          </motion.div>
        ) : null}
      </AnimatePresence>
    </div>
  );
}

/** Arrow-key movement between menu items. */
function onMenuKeyDown(e: React.KeyboardEvent<HTMLDivElement>) {
  if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp' && e.key !== 'Home' && e.key !== 'End') return;
  const items = Array.from(e.currentTarget.querySelectorAll<HTMLElement>('[role="menuitem"]'));
  if (items.length === 0) return;
  e.preventDefault();
  const i = items.indexOf(document.activeElement as HTMLElement);
  let next = 0;
  if (e.key === 'ArrowDown') next = i < 0 ? 0 : (i + 1) % items.length;
  else if (e.key === 'ArrowUp') next = i <= 0 ? items.length - 1 : i - 1;
  else if (e.key === 'End') next = items.length - 1;
  items[next]?.focus();
}

export function MenuItem({
  children,
  onSelect,
  icon,
  danger,
}: {
  children: ReactNode;
  onSelect: () => void;
  icon?: ReactNode;
  danger?: boolean;
}) {
  return (
    <button
      type="button"
      role="menuitem"
      onClick={onSelect}
      className={cn(
        'flex w-full items-center gap-2 rounded-md px-2.5 py-2 text-left text-sm hover:bg-text/5 focus-visible:bg-text/5',
        danger ? 'text-health-critical' : 'text-text',
      )}
    >
      {icon}
      {children}
    </button>
  );
}
