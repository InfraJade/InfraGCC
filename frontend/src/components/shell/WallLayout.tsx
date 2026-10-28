import { useEffect, useState, type ReactNode } from 'react';
import { Link } from 'react-router-dom';

import { useNow } from '@/lib/useNow';

import { IconButton } from '../Button';
import { Icon } from '../Icon';
import { Logo } from './Logo';
import { DemoBadge, LiveIndicator } from './TopBar';

/**
 * Full-screen NOC wall layout: no sidebar or search, large type, clock, live status, and a fullscreen toggle.
 * Content is the global overview at wall scale.
 */
export function WallLayout({ title = 'Global overview', children }: { title?: string; children: ReactNode }) {
  const now = useNow(1000);
  const [fullscreen, setFullscreen] = useState(
    () => typeof document !== 'undefined' && !!document.fullscreenElement,
  );

  useEffect(() => {
    const onChange = () => setFullscreen(!!document.fullscreenElement);
    document.addEventListener('fullscreenchange', onChange);
    return () => document.removeEventListener('fullscreenchange', onChange);
  }, []);

  const toggleFullscreen = () => {
    if (document.fullscreenElement) void document.exitFullscreen();
    else void document.documentElement.requestFullscreen?.().catch(() => undefined);
  };

  const time = new Date(now);
  return (
    <div className="flex min-h-screen flex-col px-6 py-5 wall:px-10 wall:py-8">
      <header className="mb-6 flex items-center gap-6">
        <Logo />
        <h1 className="text-2xl font-semibold tracking-tight text-text wall:text-4xl">{title}</h1>
        <div className="ml-auto flex items-center gap-4">
          <DemoBadge />
          <LiveIndicator />
          <time
            dateTime={time.toISOString()}
            className="tabular font-mono text-2xl font-medium text-text wall:text-4xl"
            aria-label={`Local time ${time.toLocaleTimeString()}`}
          >
            {time.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
          </time>
          <IconButton
            icon={fullscreen ? 'minimize' : 'maximize'}
            label={fullscreen ? 'Exit full screen' : 'Full screen'}
            onClick={toggleFullscreen}
            variant="secondary"
          />
          <Link
            to="/"
            className="glass-subtle inline-flex h-9 items-center gap-2 rounded-md px-3 text-sm font-medium text-text-muted hover:text-text"
          >
            <Icon name="x" size={16} />
            Exit wall mode
          </Link>
        </div>
      </header>
      <main className="flex-1 text-base wall:text-lg">{children}</main>
    </div>
  );
}
