import { AnimatePresence, motion } from 'framer-motion';
import { useEffect, useRef, useState, type PointerEvent } from 'react';
import { Link, Navigate, useLocation } from 'react-router-dom';

import { errorMessage } from '@/api/errors';
import { useAuth } from '@/auth/AuthProvider';
import { Icon, type IconName } from '@/components/Icon';
import { Logo } from '@/components/shell/Logo';
import { ThemeToggle } from '@/components/shell/TopBar';
import { FullPageSpinner } from '@/components/Spinner';
import { useDemoMode } from '@/demo/demoMode';
import { cn } from '@/lib/cn';
import { useResolvedTheme, useTheme } from '@/theme/ThemeProvider';

import { HeroVisual } from './login/HeroVisual';
import { NetworkCanvas } from './login/NetworkCanvas';

const WORDS = ['site', 'rack', 'server', 'sensor'];

const FEATURES: { icon: IconName; title: string; text: string }[] = [
  {
    icon: 'activity',
    title: 'Live Redfish telemetry',
    text: '20 hardware parameters from every BMC, polled every 60 seconds and streamed to your screen.',
  },
  {
    icon: 'bell',
    title: 'Alerts that reach people',
    text: 'Rules with flap protection, maintenance muting, email and Teams routing, and 15-minute escalation.',
  },
  {
    icon: 'shield',
    title: 'Firmware compliance',
    text: 'Every BIOS, BMC, RAID and drive version checked daily against the approved baselines.',
  },
  {
    icon: 'chart',
    title: 'Capacity and trends',
    text: 'Thermal, power and health dashboards across sites, rooms and racks, with 13 months of history.',
  },
];
const FEATURE_MS = 5000;

/**
 * The cycling noun in "Every site / watched live." Words share one grid cell, so they sit on the text
 * baseline. Left-aligned, an invisible copy of the longest word reserves the width so nothing shifts;
 * centred, the cell takes the current word's width so the line stays centred.
 */
function RotatingWord({ align = 'left' }: { align?: 'left' | 'center' }) {
  const [i, setI] = useState(0);
  useEffect(() => {
    const t = setInterval(() => setI((n) => (n + 1) % WORDS.length), 2200);
    return () => clearInterval(t);
  }, []);
  return (
    <span
      className={cn(
        'inline-grid overflow-hidden pb-[0.08em] align-baseline',
        align === 'center' ? 'justify-items-center' : 'justify-items-start',
      )}
    >
      {align === 'left' ? (
        <span className="invisible [grid-area:1/1]">
          {WORDS.reduce((a, b) => (a.length >= b.length ? a : b))}
        </span>
      ) : null}
      <AnimatePresence initial={false}>
        <motion.span
          key={WORDS[i]}
          initial={{ y: '100%', opacity: 0 }}
          animate={{ y: '0%', opacity: 1 }}
          exit={{ y: '-100%', opacity: 0 }}
          transition={{ duration: 0.45, ease: [0.2, 0, 0, 1] }}
          className="bg-gradient-to-r from-sky-500 via-cyan-500 to-emerald-500 bg-clip-text text-transparent [grid-area:1/1]"
        >
          {WORDS[i]}
        </motion.span>
      </AnimatePresence>
    </span>
  );
}

function FeatureCarousel() {
  const [i, setI] = useState(0);
  const [paused, setPaused] = useState(false);
  useEffect(() => {
    if (paused) return;
    const t = setTimeout(() => setI((n) => (n + 1) % FEATURES.length), FEATURE_MS);
    return () => clearTimeout(t);
  }, [i, paused]);
  const f = FEATURES[i]!;
  return (
    <section
      aria-label="What Jade GCC does"
      className="glass relative w-full max-w-xl overflow-hidden rounded-2xl p-5"
      onPointerEnter={() => setPaused(true)}
      onPointerLeave={() => setPaused(false)}
      onFocus={() => setPaused(true)}
      onBlur={() => setPaused(false)}
    >
      <div className="flex min-h-[4.5rem] items-start gap-4" aria-live="polite">
        <AnimatePresence mode="wait">
          <motion.div
            key={f.title}
            initial={{ opacity: 0, x: 16 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: -16 }}
            transition={{ duration: 0.3 }}
            className="flex items-start gap-4"
          >
            <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-sky-500/25 to-emerald-500/25 text-accent ring-1 ring-inset ring-accent/30">
              <Icon name={f.icon} size={20} />
            </span>
            <span>
              <span className="block text-sm font-semibold text-text">{f.title}</span>
              <span className="mt-1 block text-sm text-text-muted">{f.text}</span>
            </span>
          </motion.div>
        </AnimatePresence>
      </div>
      <div className="mt-4 flex items-center gap-2">
        {FEATURES.map((x, k) => (
          <button
            key={x.title}
            type="button"
            aria-label={`Show: ${x.title}`}
            aria-current={k === i}
            onClick={() => setI(k)}
            className="group relative h-1.5 flex-1 overflow-hidden rounded-full bg-text/10"
          >
            {k === i ? (
              <motion.span
                key={`${k}-${paused ? 'p' : 'r'}`}
                className="absolute inset-y-0 left-0 rounded-full bg-gradient-to-r from-sky-400 to-emerald-400"
                initial={{ width: paused ? '100%' : '0%' }}
                animate={{ width: '100%' }}
                transition={{ duration: paused ? 0 : FEATURE_MS / 1000, ease: 'linear' }}
              />
            ) : (
              <span
                className={cn(
                  'absolute inset-0 rounded-full',
                  k < i ? 'bg-text/30' : 'group-hover:bg-text/20',
                )}
              />
            )}
          </button>
        ))}
      </div>
    </section>
  );
}

function SignInCard({ returnTo }: { returnTo: string }) {
  const { signIn, error } = useAuth();
  const demo = useDemoMode();
  const [busy, setBusy] = useState(false);
  const cardRef = useRef<HTMLDivElement>(null);
  // Spotlight that follows the pointer across the card.
  const onMove = (e: PointerEvent<HTMLDivElement>) => {
    const el = cardRef.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    el.style.setProperty('--mx', `${e.clientX - r.left}px`);
    el.style.setProperty('--my', `${e.clientY - r.top}px`);
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: 20, scale: 0.98 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      transition={{ duration: 0.5, ease: [0.2, 0, 0, 1], delay: 0.1 }}
      className="relative w-full max-w-md"
    >
      {/* Animated gradient rim: a spinning conic gradient behind the card, visible only in the 1.5px gap. */}
      <div aria-hidden="true" className="absolute inset-0 overflow-hidden rounded-[1.6rem]">
        <div className="absolute -inset-[60%] animate-spin-slow bg-[conic-gradient(from_0deg,transparent_0deg,rgba(56,189,248,0.9)_60deg,transparent_120deg,transparent_200deg,rgba(43,201,140,0.9)_260deg,transparent_320deg)] [animation-duration:9s]" />
      </div>
      <div aria-hidden="true" className="absolute -inset-6 -z-10 rounded-[2rem] bg-sky-500/10 blur-3xl" />
      <div
        ref={cardRef}
        onPointerMove={onMove}
        className="relative m-[1.5px] overflow-hidden rounded-[1.5rem] bg-[rgb(var(--c-surface)/0.94)] p-7 shadow-xl backdrop-blur-xl sm:p-9"
        style={{
          backgroundImage:
            'radial-gradient(420px circle at var(--mx, 50%) var(--my, 0%), rgba(56,189,248,0.10), transparent 60%)',
        }}
      >
        <div className="flex flex-col items-center text-center">
          <motion.div
            initial={{ opacity: 0, scale: 0.9 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{ duration: 0.5, delay: 0.25 }}
            className="relative"
          >
            <div aria-hidden="true" className="absolute -inset-4 rounded-[2rem] bg-sky-400/25 blur-2xl" />
            <Logo variant="full" className="relative h-36 w-36 sm:h-40 sm:w-40" />
          </motion.div>
          <h1 className="mt-7 text-2xl font-semibold tracking-tight text-text">Sign in</h1>
          <p className="mt-1.5 text-sm text-text-muted">Data center monitoring for Jade Global GCC</p>
        </div>

        {error ? (
          <p
            role="alert"
            className="mt-6 flex items-start gap-2 rounded-lg bg-health-critical/10 p-3 text-sm text-health-critical"
          >
            <Icon name="triangle-alert" size={16} className="mt-0.5 shrink-0" />
            <span>Sign-in failed: {errorMessage(error)}</span>
          </p>
        ) : null}

        <button
          type="button"
          disabled={busy}
          onClick={() => {
            setBusy(true);
            void signIn(returnTo).finally(() => setBusy(false));
          }}
          className="group relative mt-7 flex h-12 w-full items-center justify-center gap-2.5 overflow-hidden rounded-xl bg-gradient-to-r from-sky-500 via-cyan-500 to-emerald-500 text-sm font-semibold text-white shadow-[0_10px_30px_-10px_rgba(56,189,248,0.7)] transition-transform duration-fast hover:-translate-y-0.5 hover:shadow-[0_14px_36px_-10px_rgba(43,201,140,0.75)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-canvas active:translate-y-0 disabled:opacity-80"
        >
          <span
            aria-hidden="true"
            className="absolute inset-y-0 left-0 w-1/3 animate-sheen bg-gradient-to-r from-transparent via-white/35 to-transparent"
          />
          <Icon name={busy ? 'loader' : 'shield'} size={18} className={busy ? 'animate-spin' : undefined} />
          <span className="relative">Sign in with company SSO</span>
          <Icon
            name="chevron-right"
            size={16}
            className="relative transition-transform duration-fast group-hover:translate-x-0.5"
          />
        </button>

        <div className="mt-6 grid grid-cols-3 gap-2 text-center text-[11px] text-text-subtle">
          {[
            ['shield', 'SSO / OIDC'],
            ['user', 'Role-based'],
            ['globe', 'Site-scoped'],
          ].map(([icon, label]) => (
            <span
              key={label}
              className="flex flex-col items-center gap-1 rounded-lg bg-text/[0.04] px-2 py-2 ring-1 ring-inset ring-text/5"
            >
              <Icon name={icon as IconName} size={14} className="text-accent" />
              {label}
            </span>
          ))}
        </div>

        {demo ? (
          <p className="mt-4 flex items-center justify-center gap-1.5 text-xs font-medium text-health-warning">
            <Icon name="flask" size={13} /> Demo mode is on: you&apos;ll see sample data after signing in.
          </p>
        ) : null}

        <p className="mt-5 text-center text-xs text-text-subtle">
          Access and roles come from your company SSO groups. Can&apos;t sign in? Contact the platform team.
        </p>
      </div>
    </motion.div>
  );
}

export default function LoginPage() {
  const { status } = useAuth();
  const location = useLocation();
  const theme = useResolvedTheme();
  const { reducedMotion } = useTheme();
  const returnTo = (location.state as { returnTo?: string } | null)?.returnTo ?? '/';

  if (status === 'loading') return <FullPageSpinner label="Checking your session…" />;
  if (status === 'authenticated') return <Navigate to={returnTo} replace />;

  return (
    <div className="relative min-h-screen overflow-hidden">
      {/* Backdrop: aurora glows + live network */}
      <div aria-hidden="true" className="pointer-events-none absolute inset-0">
        <div className="absolute -left-[10%] -top-[20%] h-[70vh] w-[60vw] animate-aurora rounded-full bg-sky-500/20 blur-[120px]" />
        <div className="absolute -bottom-[25%] right-[-10%] h-[70vh] w-[55vw] animate-aurora rounded-full bg-emerald-500/15 blur-[120px] [animation-delay:-9s]" />
        <div className="absolute left-[30%] top-[40%] h-[40vh] w-[30vw] animate-aurora rounded-full bg-indigo-500/10 blur-[100px] [animation-delay:-4s]" />
      </div>
      <NetworkCanvas theme={theme} reducedMotion={reducedMotion} />
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-0 bg-[radial-gradient(ellipse_at_center,transparent_40%,rgb(var(--c-canvas)/0.7))]"
      />

      <header className="relative z-10 flex items-center justify-between px-5 py-4 sm:px-8">
        <Logo />
        <ThemeToggle />
      </header>

      <main className="relative z-10 mx-auto grid w-full max-w-7xl items-center gap-10 px-5 pb-12 pt-2 sm:px-8 lg:min-h-[calc(100vh-4.5rem)] lg:grid-cols-[1.15fr_1fr] lg:gap-16 lg:pb-16">
        <section aria-label="About Jade GCC" className="hidden flex-col gap-8 lg:flex">
          <motion.div
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5 }}
          >
            <span className="glass-subtle inline-flex items-center gap-2 rounded-full px-3 py-1 text-xs font-medium text-text-muted">
              <span className="relative flex h-2 w-2">
                <span className="absolute inline-flex h-full w-full animate-pulse-ring rounded-full bg-accent" />
                <span className="relative inline-flex h-2 w-2 rounded-full bg-accent" />
              </span>
              GCC data centers · real-time monitoring
            </span>
            <h2 className="mt-5 text-4xl font-semibold leading-[1.1] tracking-tight text-text xl:text-5xl">
              Every <RotatingWord />
              <br />
              watched live.
            </h2>
            <p className="mt-4 max-w-lg text-base text-text-muted">
              Health, sensors, alerts and firmware for every Dell, HPE and Lenovo server across the GCC sites,
              in one place.
            </p>
          </motion.div>
          <motion.div
            initial={{ opacity: 0, scale: 0.96 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{ duration: 0.7, delay: 0.15 }}
          >
            <HeroVisual className="mx-auto w-full max-w-xl" />
          </motion.div>
          <FeatureCarousel />
        </section>

        <div className="flex flex-col items-center gap-6">
          <div className="text-center lg:hidden">
            <h2 className="text-2xl font-semibold tracking-tight text-text">
              Every <RotatingWord align="center" />
              <br />
              watched live.
            </h2>
          </div>
          <SignInCard returnTo={returnTo} />
          <p className="text-center text-xs text-text-subtle">
            © {new Date().getFullYear()} Jade Global · GCC ·{' '}
            <Link to="/login" className="hover:text-text">
              Data Center Monitoring
            </Link>
          </p>
        </div>
      </main>
    </div>
  );
}
