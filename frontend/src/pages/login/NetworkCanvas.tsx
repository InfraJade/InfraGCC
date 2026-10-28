import { useEffect, useRef } from 'react';

import type { ThemeName } from '@/theme/tokens';

/**
 * Login backdrop: a drifting network of nodes (sites, racks, servers) with links that light up as data pulses
 * travel along them. Nodes near the pointer brighten and lean towards it; a click sends a ripple through the
 * mesh. Decorative only (aria-hidden). Draws one still frame when motion is reduced, and pauses while the tab
 * is hidden.
 */

interface Node {
  x: number;
  y: number;
  vx: number;
  vy: number;
  r: number;
  hub: boolean;
  phase: number;
}

interface Pulse {
  a: number;
  b: number;
  t: number;
  speed: number;
  color: string;
}

interface Ripple {
  x: number;
  y: number;
  age: number;
}

const PALETTE: Record<ThemeName, { node: string; hub: string; link: string; pulse: string[]; glow: string }> =
  {
    dark: {
      node: '96, 165, 250',
      hub: '56, 189, 248',
      link: '59, 130, 246',
      pulse: ['#38bdf8', '#2bc98c', '#60a5fa'],
      glow: '43, 201, 140',
    },
    light: {
      node: '37, 99, 235',
      hub: '2, 132, 199',
      link: '37, 99, 235',
      pulse: ['#0284c7', '#078e61', '#2563eb'],
      glow: '7, 142, 97',
    },
  };

const LINK_DIST = 150;
const POINTER_DIST = 190;

export function NetworkCanvas({ theme, reducedMotion }: { theme: ThemeName; reducedMotion: boolean }) {
  const ref = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = ref.current;
    const ctx = canvas?.getContext('2d');
    if (!canvas || !ctx) return;
    const colors = PALETTE[theme];
    let width = 0;
    let height = 0;
    let nodes: Node[] = [];
    const pulses: Pulse[] = [];
    const ripples: Ripple[] = [];
    const pointer = { x: -9999, y: -9999, active: false };
    let frame = 0;
    let last = performance.now();
    let spawnClock = 0;

    const seedNodes = () => {
      const count = Math.round(Math.min(120, Math.max(36, (width * height) / 14000)));
      nodes = Array.from({ length: count }, (_, i) => ({
        x: Math.random() * width,
        y: Math.random() * height,
        vx: (Math.random() - 0.5) * 0.25,
        vy: (Math.random() - 0.5) * 0.25,
        r: i % 9 === 0 ? 2.8 : 1.2 + Math.random() * 1.2,
        hub: i % 9 === 0,
        phase: Math.random() * Math.PI * 2,
      }));
    };

    const resize = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      width = canvas.clientWidth;
      height = canvas.clientHeight;
      canvas.width = Math.floor(width * dpr);
      canvas.height = Math.floor(height * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      seedNodes();
    };

    const spawnPulse = () => {
      const a = Math.floor(Math.random() * nodes.length);
      const na = nodes[a];
      if (!na) return;
      let best = -1;
      let bestD = Infinity;
      for (let j = 0; j < nodes.length; j++) {
        if (j === a) continue;
        const nb = nodes[j]!;
        const d = Math.hypot(na.x - nb.x, na.y - nb.y);
        if (d < LINK_DIST && d > 30 && d < bestD && Math.random() > 0.35) {
          best = j;
          bestD = d;
        }
      }
      if (best < 0) return;
      pulses.push({
        a,
        b: best,
        t: 0,
        speed: 0.5 + Math.random() * 0.7,
        color: colors.pulse[Math.floor(Math.random() * colors.pulse.length)]!,
      });
    };

    const draw = (dt: number, time: number) => {
      ctx.clearRect(0, 0, width, height);
      const step = dt / 16.67;

      for (const n of nodes) {
        if (!reducedMotion) {
          // Lean towards the pointer, then drift.
          if (pointer.active) {
            const dx = pointer.x - n.x;
            const dy = pointer.y - n.y;
            const d = Math.hypot(dx, dy);
            if (d < POINTER_DIST && d > 1) {
              const f = (1 - d / POINTER_DIST) * 0.012;
              n.vx += dx * f * 0.05;
              n.vy += dy * f * 0.05;
            }
          }
          for (const rp of ripples) {
            const dx = n.x - rp.x;
            const dy = n.y - rp.y;
            const d = Math.hypot(dx, dy);
            const front = rp.age * 0.45;
            if (Math.abs(d - front) < 24 && d > 1) {
              n.vx += (dx / d) * 0.35;
              n.vy += (dy / d) * 0.35;
            }
          }
          n.vx *= 0.985;
          n.vy *= 0.985;
          const speed = Math.hypot(n.vx, n.vy);
          if (speed < 0.08) {
            n.vx += (Math.random() - 0.5) * 0.02;
            n.vy += (Math.random() - 0.5) * 0.02;
          }
          n.x += n.vx * step;
          n.y += n.vy * step;
          if (n.x < -20) n.x = width + 20;
          if (n.x > width + 20) n.x = -20;
          if (n.y < -20) n.y = height + 20;
          if (n.y > height + 20) n.y = -20;
        }
      }

      // Links.
      ctx.lineWidth = 1;
      for (let i = 0; i < nodes.length; i++) {
        const a = nodes[i]!;
        for (let j = i + 1; j < nodes.length; j++) {
          const b = nodes[j]!;
          const d = Math.hypot(a.x - b.x, a.y - b.y);
          if (d > LINK_DIST) continue;
          let alpha = (1 - d / LINK_DIST) * 0.28;
          if (pointer.active) {
            const pd = Math.hypot((a.x + b.x) / 2 - pointer.x, (a.y + b.y) / 2 - pointer.y);
            if (pd < POINTER_DIST) alpha += (1 - pd / POINTER_DIST) * 0.4;
          }
          ctx.strokeStyle = `rgba(${colors.link}, ${alpha})`;
          ctx.beginPath();
          ctx.moveTo(a.x, a.y);
          ctx.lineTo(b.x, b.y);
          ctx.stroke();
        }
      }

      // Pulses travelling along links.
      for (let k = pulses.length - 1; k >= 0; k--) {
        const p = pulses[k]!;
        const a = nodes[p.a];
        const b = nodes[p.b];
        if (!a || !b || Math.hypot(a.x - b.x, a.y - b.y) > LINK_DIST * 1.2) {
          pulses.splice(k, 1);
          continue;
        }
        p.t += 0.012 * p.speed * step;
        if (p.t >= 1) {
          pulses.splice(k, 1);
          continue;
        }
        const x = a.x + (b.x - a.x) * p.t;
        const y = a.y + (b.y - a.y) * p.t;
        const tail = Math.max(0, p.t - 0.18);
        const grad = ctx.createLinearGradient(a.x + (b.x - a.x) * tail, a.y + (b.y - a.y) * tail, x, y);
        grad.addColorStop(0, 'rgba(0,0,0,0)');
        grad.addColorStop(1, p.color);
        ctx.strokeStyle = grad;
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.moveTo(a.x + (b.x - a.x) * tail, a.y + (b.y - a.y) * tail);
        ctx.lineTo(x, y);
        ctx.stroke();
        ctx.fillStyle = p.color;
        ctx.shadowColor = p.color;
        ctx.shadowBlur = 12;
        ctx.beginPath();
        ctx.arc(x, y, 2.2, 0, Math.PI * 2);
        ctx.fill();
        ctx.shadowBlur = 0;
      }

      // Nodes.
      for (const n of nodes) {
        const twinkle = reducedMotion ? 1 : 0.75 + 0.25 * Math.sin(time / 900 + n.phase);
        let boost = 0;
        if (pointer.active) {
          const d = Math.hypot(n.x - pointer.x, n.y - pointer.y);
          if (d < POINTER_DIST) boost = 1 - d / POINTER_DIST;
        }
        const r = n.r * (1 + boost * 0.9);
        if (n.hub || boost > 0.2) {
          const g = ctx.createRadialGradient(n.x, n.y, 0, n.x, n.y, r * 7);
          g.addColorStop(0, `rgba(${n.hub ? colors.hub : colors.glow}, ${0.28 * twinkle + boost * 0.3})`);
          g.addColorStop(1, 'rgba(0,0,0,0)');
          ctx.fillStyle = g;
          ctx.beginPath();
          ctx.arc(n.x, n.y, r * 7, 0, Math.PI * 2);
          ctx.fill();
        }
        ctx.fillStyle = `rgba(${n.hub ? colors.hub : colors.node}, ${0.55 * twinkle + boost * 0.45})`;
        ctx.beginPath();
        ctx.arc(n.x, n.y, r, 0, Math.PI * 2);
        ctx.fill();
      }

      // Click ripples.
      for (let k = ripples.length - 1; k >= 0; k--) {
        const rp = ripples[k]!;
        rp.age += dt;
        const radius = rp.age * 0.45;
        const alpha = Math.max(0, 1 - rp.age / 1400);
        if (alpha <= 0) {
          ripples.splice(k, 1);
          continue;
        }
        ctx.strokeStyle = `rgba(${colors.glow}, ${alpha * 0.6})`;
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        ctx.arc(rp.x, rp.y, radius, 0, Math.PI * 2);
        ctx.stroke();
      }
    };

    const loop = (now: number) => {
      const dt = Math.min(64, now - last);
      last = now;
      spawnClock += dt;
      if (spawnClock > 140 && pulses.length < 26) {
        spawnClock = 0;
        spawnPulse();
      }
      draw(dt, now);
      frame = requestAnimationFrame(loop);
    };

    const toLocal = (e: PointerEvent) => {
      const rect = canvas.getBoundingClientRect();
      return { x: e.clientX - rect.left, y: e.clientY - rect.top };
    };
    const onMove = (e: PointerEvent) => {
      const p = toLocal(e);
      pointer.x = p.x;
      pointer.y = p.y;
      pointer.active = true;
    };
    const onLeave = () => {
      pointer.active = false;
    };
    const onDown = (e: PointerEvent) => {
      if (reducedMotion) return;
      const p = toLocal(e);
      ripples.push({ x: p.x, y: p.y, age: 0 });
      for (let i = 0; i < 6; i++) spawnPulse();
    };
    const onVisibility = () => {
      cancelAnimationFrame(frame);
      if (!document.hidden && !reducedMotion) {
        last = performance.now();
        frame = requestAnimationFrame(loop);
      }
    };

    resize();
    const ro = new ResizeObserver(() => {
      resize();
      if (reducedMotion) draw(16, 0);
    });
    ro.observe(canvas);
    if (reducedMotion) draw(16, 0);
    else frame = requestAnimationFrame(loop);
    window.addEventListener('pointermove', onMove, { passive: true });
    window.addEventListener('pointerdown', onDown, { passive: true });
    document.addEventListener('pointerleave', onLeave);
    document.addEventListener('visibilitychange', onVisibility);
    return () => {
      cancelAnimationFrame(frame);
      ro.disconnect();
      window.removeEventListener('pointermove', onMove);
      window.removeEventListener('pointerdown', onDown);
      document.removeEventListener('pointerleave', onLeave);
      document.removeEventListener('visibilitychange', onVisibility);
    };
  }, [theme, reducedMotion]);

  return (
    <canvas ref={ref} aria-hidden="true" className="pointer-events-none absolute inset-0 h-full w-full" />
  );
}
