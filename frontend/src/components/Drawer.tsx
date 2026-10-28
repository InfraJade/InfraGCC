import { AnimatePresence, motion } from 'framer-motion';
import { useId, useRef, type ReactNode } from 'react';

import { cn } from '@/lib/cn';
import { motion as motionTokens } from '@/theme/tokens';

import { IconButton } from './Button';
import { Portal, useFocusTrap } from './overlay';

const ease = motionTokens.easing.emphasized as unknown as [number, number, number, number];

export interface DrawerProps {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  description?: ReactNode;
  side?: 'right' | 'left';
  /** Tailwind max-width class, default max-w-md. */
  widthClassName?: string;
  footer?: ReactNode;
  children?: ReactNode;
}

/** Side panel (details, edit forms). Modal: traps focus, Esc and backdrop close it. */
export function Drawer({
  open,
  onClose,
  title,
  description,
  side = 'right',
  widthClassName = 'max-w-md',
  footer,
  children,
}: DrawerProps) {
  return (
    <Portal>
      <AnimatePresence>
        {open ? (
          <DrawerInner
            onClose={onClose}
            title={title}
            description={description}
            side={side}
            widthClassName={widthClassName}
            footer={footer}
          >
            {children}
          </DrawerInner>
        ) : null}
      </AnimatePresence>
    </Portal>
  );
}

function DrawerInner({
  onClose,
  title,
  description,
  side,
  widthClassName,
  footer,
  children,
}: Omit<DrawerProps, 'open'>) {
  const ref = useRef<HTMLDivElement>(null);
  const titleId = useId();
  useFocusTrap(ref, true, onClose);
  const offset = side === 'left' ? '-100%' : '100%';
  return (
    <div className="fixed inset-0 z-drawer">
      <motion.div
        className="absolute inset-0 bg-scrim/45"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        onClick={onClose}
        aria-hidden="true"
      />
      <motion.div
        ref={ref}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        className={cn(
          'glass-strong absolute top-0 flex h-full w-full flex-col outline-none',
          side === 'left' ? 'left-0 rounded-r-2xl' : 'right-0 rounded-l-2xl',
          widthClassName,
        )}
        initial={{ x: offset }}
        animate={{ x: 0 }}
        exit={{ x: offset }}
        transition={{ duration: motionTokens.duration.slow / 1000, ease }}
      >
        <header className="flex items-start justify-between gap-4 border-b hairline px-5 py-4">
          <div>
            <h2 id={titleId} className="text-base font-semibold text-text">
              {title}
            </h2>
            {description ? <p className="mt-0.5 text-sm text-text-muted">{description}</p> : null}
          </div>
          <IconButton icon="x" label="Close" size="sm" onClick={onClose} />
        </header>
        <div className="flex-1 overflow-y-auto px-5 py-4">{children}</div>
        {footer ? (
          <footer className="flex justify-end gap-2 border-t hairline px-5 py-3">{footer}</footer>
        ) : null}
      </motion.div>
    </div>
  );
}
