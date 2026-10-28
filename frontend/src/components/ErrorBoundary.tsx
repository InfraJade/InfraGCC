import { Component, type ErrorInfo, type ReactNode } from 'react';

import { errorMessage } from '@/api/errors';

import { Button } from './Button';
import { EmptyState } from './EmptyState';

export interface ErrorBoundaryProps {
  children: ReactNode;
  /** Custom fallback; receives the error and a reset function. */
  fallback?: (error: unknown, reset: () => void) => ReactNode;
  /** Reset automatically when any of these change (e.g. the route path). */
  resetKeys?: unknown[];
  onError?: (error: unknown, info: ErrorInfo) => void;
}

interface State {
  error: unknown;
  hasError: boolean;
}

/** Catches render errors in a subtree so one broken widget doesn't blank the page. */
export class ErrorBoundary extends Component<ErrorBoundaryProps, State> {
  override state: State = { error: null, hasError: false };

  static getDerivedStateFromError(error: unknown): State {
    return { error, hasError: true };
  }

  override componentDidCatch(error: unknown, info: ErrorInfo) {
    this.props.onError?.(error, info);
    if (import.meta.env.DEV) console.error('ErrorBoundary caught', error, info.componentStack);
  }

  override componentDidUpdate(prev: ErrorBoundaryProps) {
    if (!this.state.hasError) return;
    const a = prev.resetKeys ?? [];
    const b = this.props.resetKeys ?? [];
    if (a.length !== b.length || a.some((v, i) => !Object.is(v, b[i]))) this.reset();
  }

  reset = () => this.setState({ error: null, hasError: false });

  override render() {
    if (!this.state.hasError) return this.props.children;
    if (this.props.fallback) return this.props.fallback(this.state.error, this.reset);
    return (
      <div className="glass rounded-xl">
        <EmptyState
          tone="error"
          title="Something went wrong on this page"
          description={errorMessage(this.state.error)}
          action={
            <Button icon="refresh" onClick={this.reset}>
              Try again
            </Button>
          }
        />
      </div>
    );
  }
}
