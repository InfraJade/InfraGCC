import { useEffect, useRef, type ReactNode, type RefObject } from 'react';
import { createPortal } from 'react-dom';

const FOCUSABLE =
  'a[href], area[href], button:not([disabled]), input:not([disabled]):not([type="hidden"]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"]), [contenteditable="true"]';

export function focusableIn(root: HTMLElement): HTMLElement[] {
  return Array.from(root.querySelectorAll<HTMLElement>(FOCUSABLE)).filter((el) => !el.hasAttribute('inert'));
}

export function Portal({ children }: { children: ReactNode }) {
  if (typeof document === 'undefined') return null;
  return createPortal(children, document.body);
}

/**
 * Modal focus management: moves focus into `ref` when active (to `initialFocus` or the first focusable),
 * keeps Tab inside it, closes on Escape, and restores focus to the previously focused element.
 */
export function useFocusTrap(
  ref: RefObject<HTMLElement | null>,
  active: boolean,
  onEscape?: () => void,
  initialFocus?: RefObject<HTMLElement | null>,
) {
  const onEscapeRef = useRef(onEscape);
  onEscapeRef.current = onEscape;

  useEffect(() => {
    if (!active) return;
    const root = ref.current;
    if (!root) return;
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const first = initialFocus?.current ?? focusableIn(root)[0] ?? root;
    first.focus();

    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.stopPropagation();
        onEscapeRef.current?.();
        return;
      }
      if (e.key !== 'Tab') return;
      const items = focusableIn(root);
      if (items.length === 0) {
        e.preventDefault();
        return;
      }
      const firstEl = items[0];
      const lastEl = items[items.length - 1];
      if (e.shiftKey && document.activeElement === firstEl) {
        e.preventDefault();
        lastEl?.focus();
      } else if (!e.shiftKey && document.activeElement === lastEl) {
        e.preventDefault();
        firstEl?.focus();
      }
    };
    root.addEventListener('keydown', onKey);
    return () => {
      root.removeEventListener('keydown', onKey);
      previous?.focus();
    };
  }, [active, ref, initialFocus]);
}

/** Close a non-modal popup on outside pointer-down or Escape. */
export function useDismiss(refs: RefObject<HTMLElement | null>[], open: boolean, onDismiss: () => void) {
  const cb = useRef(onDismiss);
  cb.current = onDismiss;
  useEffect(() => {
    if (!open) return;
    const onPointer = (e: PointerEvent | MouseEvent) => {
      const target = e.target as Node | null;
      if (target && refs.some((r) => r.current?.contains(target))) return;
      cb.current();
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') cb.current();
    };
    document.addEventListener('mousedown', onPointer);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onPointer);
      document.removeEventListener('keydown', onKey);
    };
    // refs are stable ref objects
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);
}
