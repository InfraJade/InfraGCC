import { AnimatePresence, motion } from 'framer-motion';
import { createContext, useCallback, useContext, useMemo, useRef, useState, type ReactNode } from 'react';

import { cn } from '@/lib/cn';

import { Icon, type IconName } from './Icon';

export type ToastTone = 'info' | 'success' | 'warning' | 'error';

export interface ToastInput {
  title: string;
  description?: ReactNode;
  tone?: ToastTone;
  /** ms; 0 = sticky. Default 5000 (errors 8000). */
  duration?: number;
  action?: { label: string; onClick: () => void };
}

interface ToastItem extends ToastInput {
  id: number;
  tone: ToastTone;
}

interface ToastApi {
  toast: (t: ToastInput) => number;
  dismiss: (id: number) => void;
}

const ToastContext = createContext<ToastApi | null>(null);

const toneStyle: Record<ToastTone, { icon: IconName; cls: string; word: string }> = {
  info: { icon: 'info', cls: 'text-info', word: 'Info' },
  success: { icon: 'circle-check', cls: 'text-health-ok', word: 'Success' },
  warning: { icon: 'triangle-alert', cls: 'text-health-warning', word: 'Warning' },
  error: { icon: 'octagon-x', cls: 'text-health-critical', word: 'Error' },
};

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const nextId = useRef(1);
  const timers = useRef(new Map<number, ReturnType<typeof setTimeout>>());

  const dismiss = useCallback((id: number) => {
    setItems((list) => list.filter((t) => t.id !== id));
    const timer = timers.current.get(id);
    if (timer) clearTimeout(timer);
    timers.current.delete(id);
  }, []);

  const toast = useCallback(
    (input: ToastInput) => {
      const id = nextId.current++;
      const tone = input.tone ?? 'info';
      setItems((list) => [...list.slice(-4), { ...input, id, tone }]);
      const duration = input.duration ?? (tone === 'error' ? 8000 : 5000);
      if (duration > 0)
        timers.current.set(
          id,
          setTimeout(() => dismiss(id), duration),
        );
      return id;
    },
    [dismiss],
  );

  const api = useMemo(() => ({ toast, dismiss }), [toast, dismiss]);

  return (
    <ToastContext.Provider value={api}>
      {children}
      <section
        aria-label="Notifications"
        className="pointer-events-none fixed bottom-4 right-4 z-toast flex w-[min(24rem,calc(100vw-2rem))] flex-col gap-2"
      >
        {/* Polite region for info/success, assertive for errors. */}
        <div aria-live="polite" className="flex flex-col gap-2">
          <AnimatePresence initial={false}>
            {items.map((t) => (
              <motion.div
                key={t.id}
                layout
                initial={{ opacity: 0, y: 16, scale: 0.98 }}
                animate={{ opacity: 1, y: 0, scale: 1 }}
                exit={{ opacity: 0, x: 40 }}
                transition={{ duration: 0.22 }}
                role={t.tone === 'error' ? 'alert' : 'status'}
                className="glass-strong pointer-events-auto flex items-start gap-3 rounded-xl p-3.5"
              >
                <span className={cn('mt-0.5', toneStyle[t.tone].cls)}>
                  <Icon name={toneStyle[t.tone].icon} size={18} title={toneStyle[t.tone].word} />
                </span>
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-semibold text-text">{t.title}</p>
                  {t.description ? (
                    <div className="mt-0.5 text-sm text-text-muted">{t.description}</div>
                  ) : null}
                  {t.action ? (
                    <button
                      type="button"
                      className="mt-1.5 text-sm font-medium text-accent hover:underline"
                      onClick={() => {
                        t.action?.onClick();
                        dismiss(t.id);
                      }}
                    >
                      {t.action.label}
                    </button>
                  ) : null}
                </div>
                <button
                  type="button"
                  aria-label="Dismiss notification"
                  onClick={() => dismiss(t.id)}
                  className="rounded p-0.5 text-text-subtle hover:text-text"
                >
                  <Icon name="x" size={14} />
                </button>
              </motion.div>
            ))}
          </AnimatePresence>
        </div>
      </section>
    </ToastContext.Provider>
  );
}

export function useToast(): ToastApi {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error('useToast must be used inside <ToastProvider>');
  return ctx;
}
