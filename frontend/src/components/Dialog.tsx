import { AnimatePresence, motion } from 'framer-motion';
import { useId, useRef, type ReactNode } from 'react';

import { cn } from '@/lib/cn';
import { motion as motionTokens } from '@/theme/tokens';

import { Button } from './Button';
import { Icon } from './Icon';
import { Portal, useFocusTrap } from './overlay';

const ease = motionTokens.easing.standard as unknown as [number, number, number, number];
const dur = motionTokens.duration.base / 1000;

export interface DialogProps {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  description?: ReactNode;
  children?: ReactNode;
  footer?: ReactNode;
  size?: 'sm' | 'md' | 'lg';
  /** Role "alertdialog" for confirmations. */
  role?: 'dialog' | 'alertdialog';
  /** Clicking the backdrop closes (default true; false for destructive confirmations in progress). */
  dismissible?: boolean;
  initialFocus?: React.RefObject<HTMLElement | null>;
}

const widths = { sm: 'max-w-sm', md: 'max-w-lg', lg: 'max-w-2xl' } as const;

export function Dialog({
  open,
  onClose,
  title,
  description,
  children,
  footer,
  size = 'md',
  role = 'dialog',
  dismissible = true,
  initialFocus,
}: DialogProps) {
  return (
    <Portal>
      <AnimatePresence>
        {open ? (
          <DialogInner
            onClose={onClose}
            title={title}
            description={description}
            footer={footer}
            size={size}
            role={role}
            dismissible={dismissible}
            initialFocus={initialFocus}
          >
            {children}
          </DialogInner>
        ) : null}
      </AnimatePresence>
    </Portal>
  );
}

function DialogInner({
  onClose,
  title,
  description,
  children,
  footer,
  size = 'md',
  role,
  dismissible,
  initialFocus,
}: Omit<DialogProps, 'open'>) {
  const ref = useRef<HTMLDivElement>(null);
  const titleId = useId();
  const descId = useId();
  useFocusTrap(ref, true, dismissible ? onClose : undefined, initialFocus);

  return (
    <div className="fixed inset-0 z-modal flex items-center justify-center p-4">
      <motion.div
        className="absolute inset-0 bg-scrim/55 backdrop-blur-sm"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        transition={{ duration: dur, ease }}
        onClick={dismissible ? onClose : undefined}
        aria-hidden="true"
      />
      <motion.div
        ref={ref}
        role={role}
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={description ? descId : undefined}
        tabIndex={-1}
        className={cn('glass-strong relative w-full rounded-2xl p-6 outline-none', widths[size])}
        initial={{ opacity: 0, y: 12, scale: 0.98 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        exit={{ opacity: 0, y: 8, scale: 0.98 }}
        transition={{ duration: dur, ease }}
      >
        <div className="mb-4 flex items-start justify-between gap-4">
          <div>
            <h2 id={titleId} className="text-base font-semibold text-text">
              {title}
            </h2>
            {description ? (
              <div id={descId} className="mt-1 text-sm text-text-muted">
                {description}
              </div>
            ) : null}
          </div>
          {dismissible ? (
            <button
              type="button"
              onClick={onClose}
              aria-label="Close"
              className="-m-1 rounded-md p-1 text-text-subtle hover:bg-text/5 hover:text-text"
            >
              <Icon name="x" size={18} />
            </button>
          ) : null}
        </div>
        {children}
        {footer ? <div className="mt-6 flex justify-end gap-2">{footer}</div> : null}
      </motion.div>
    </div>
  );
}

export interface ConfirmDialogProps {
  open: boolean;
  title: string;
  description?: ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  tone?: 'default' | 'danger';
  busy?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
  children?: ReactNode;
}

/** Confirmation for consequential actions. Focus starts on Cancel so Enter never confirms by accident. */
export function ConfirmDialog({
  open,
  title,
  description,
  confirmLabel = 'Confirm',
  cancelLabel = 'Cancel',
  tone = 'default',
  busy,
  onConfirm,
  onCancel,
  children,
}: ConfirmDialogProps) {
  const cancelRef = useRef<HTMLButtonElement>(null);
  return (
    <Dialog
      open={open}
      onClose={onCancel}
      title={title}
      description={description}
      role="alertdialog"
      size="sm"
      dismissible={!busy}
      initialFocus={cancelRef}
      footer={
        <>
          <Button ref={cancelRef} variant="ghost" onClick={onCancel} disabled={busy}>
            {cancelLabel}
          </Button>
          <Button variant={tone === 'danger' ? 'danger' : 'primary'} onClick={onConfirm} loading={busy}>
            {confirmLabel}
          </Button>
        </>
      }
    >
      {children}
    </Dialog>
  );
}
