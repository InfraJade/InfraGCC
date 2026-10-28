/*
 * Jade GCC login theme behaviour (plain JS, no build step):
 *  - live network backdrop on #gcc-network (same behaviour as the web app's NetworkCanvas)
 *  - rack scene: LEDs, tilt towards the pointer, parallax sensor chips
 *  - rotating headline word, card spotlight, theme toggle, Caps Lock hint
 * Everything is decorative and honours prefers-reduced-motion.
 */
(function () {
  'use strict';

  var reduced = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var root = document.documentElement;
  var theme = function () {
    return root.getAttribute('data-theme') === 'light' ? 'light' : 'dark';
  };

  function ready(fn) {
    if (document.readyState !== 'loading') fn();
    else document.addEventListener('DOMContentLoaded', fn);
  }

  // ------------------------------------------------------------------ theme toggle
  function initTheme(onChange) {
    var btn = document.getElementById('gcc-theme-toggle');
    if (!btn) return;
    btn.addEventListener('click', function () {
      var next = theme() === 'dark' ? 'light' : 'dark';
      root.setAttribute('data-theme', next);
      try {
        localStorage.setItem('gcc.kc.theme', next);
      } catch (e) {
        /* storage unavailable: theme just isn't remembered */
      }
      onChange();
    });
  }

  // ------------------------------------------------------------------ rotating word
  function initRotator() {
    var el = document.querySelector('.gcc-rotator');
    if (!el || reduced) return;
    var words = (el.getAttribute('data-words') || '').split(',');
    var i = 0;
    setInterval(function () {
      var current = el.querySelector('.gcc-rotator-word:not(.gcc-out)');
      i = (i + 1) % words.length;
      var next = document.createElement('span');
      next.className = 'gcc-rotator-word gcc-in';
      next.textContent = words[i];
      el.appendChild(next);
      // next frame: slide the new word in and the old one out
      requestAnimationFrame(function () {
        requestAnimationFrame(function () {
          next.classList.remove('gcc-in');
          if (current) current.classList.add('gcc-out');
        });
      });
      setTimeout(function () {
        if (current && current.parentNode) current.parentNode.removeChild(current);
      }, 500);
    }, 2200);
  }

  // ------------------------------------------------------------------ rack scene
  var SVG_NS = 'http://www.w3.org/2000/svg';
  function svg(tag, attrs, parent) {
    var n = document.createElementNS(SVG_NS, tag);
    for (var k in attrs) n.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(n);
    return n;
  }
  var rnd = function (i) {
    var x = Math.sin(i * 12.9898) * 43758.5453;
    return x - Math.floor(x);
  };

  function initRacks() {
    var g = document.getElementById('gcc-racks');
    if (!g) return;
    var racks = [
      { x: 70, y: 112, w: 112, h: 210, units: 7 },
      { x: 196, y: 58, w: 128, h: 264, units: 9 },
      { x: 338, y: 112, w: 112, h: 210, units: 7 },
    ];
    var leds = ['#34d399', '#38bdf8', '#60a5fa', '#34d399', '#22d3ee', '#fbbf24'];
    racks.forEach(function (r, ri) {
      var d = 18;
      svg('path', { d: 'M' + r.x + ' ' + r.y + ' L' + (r.x + d) + ' ' + (r.y - d * 0.6) + ' L' + (r.x + r.w + d) + ' ' + (r.y - d * 0.6) + ' L' + (r.x + r.w) + ' ' + r.y + ' Z', fill: 'url(#g-top)' }, g);
      svg('path', { d: 'M' + (r.x + r.w) + ' ' + r.y + ' L' + (r.x + r.w + d) + ' ' + (r.y - d * 0.6) + ' L' + (r.x + r.w + d) + ' ' + (r.y + r.h - d * 0.6) + ' L' + (r.x + r.w) + ' ' + (r.y + r.h) + ' Z', fill: 'url(#g-side)' }, g);
      svg('rect', { x: r.x, y: r.y, width: r.w, height: r.h, rx: 6, fill: 'url(#g-front)', stroke: 'rgba(96,165,250,0.45)', 'stroke-width': 1.2 }, g);
      var unitH = (r.h - 24) / r.units;
      for (var u = 0; u < r.units; u++) {
        var uy = r.y + 12 + u * unitH;
        svg('rect', { x: r.x + 10, y: uy, width: r.w - 20, height: unitH - 6, rx: 3, fill: 'rgba(15,30,55,0.9)', stroke: 'rgba(59,130,246,0.28)' }, g);
        for (var b = 0; b < 4; b++)
          svg('rect', { x: r.x + 18 + b * 9, y: uy + (unitH - 6) / 2 - 2, width: 6, height: 4, rx: 1, fill: 'rgba(148,163,184,0.35)' }, g);
        for (var l = 0; l < 3; l++) {
          var i = ri * 40 + u * 5 + l;
          var color = leds[Math.floor(rnd(i) * leds.length)];
          var led = svg('circle', { cx: r.x + r.w - 18 - l * 9, cy: uy + (unitH - 6) / 2, r: 2.2, fill: color, class: 'gcc-led' }, g);
          led.style.animationDelay = (rnd(i + 99) * 2.4).toFixed(2) + 's';
          led.style.animationDuration = (1.4 + rnd(i + 7) * 2.2).toFixed(2) + 's';
          led.style.filter = 'drop-shadow(0 0 3px ' + color + ')';
        }
      }
    });
  }

  function initTilt() {
    var scene = document.getElementById('gcc-scene');
    if (!scene || reduced) return;
    var art = scene.querySelector('.gcc-scene-svg');
    var chips = scene.querySelectorAll('.gcc-chip');
    scene.addEventListener('pointermove', function (e) {
      var r = scene.getBoundingClientRect();
      var px = (e.clientX - r.left) / r.width - 0.5;
      var py = (e.clientY - r.top) / r.height - 0.5;
      art.style.transform = 'rotateY(' + (px * 24).toFixed(2) + 'deg) rotateX(' + (-py * 16).toFixed(2) + 'deg)';
      for (var i = 0; i < chips.length; i++) chips[i].style.translate = (px * 28).toFixed(1) + 'px ' + (py * 20).toFixed(1) + 'px';
    });
    scene.addEventListener('pointerleave', function () {
      art.style.transform = '';
      for (var i = 0; i < chips.length; i++) chips[i].style.translate = '';
    });
  }

  // ------------------------------------------------------------------ card spotlight, caps lock
  function initCard() {
    var card = document.getElementById('gcc-card');
    if (card && !reduced)
      card.addEventListener('pointermove', function (e) {
        var r = card.getBoundingClientRect();
        card.style.setProperty('--mx', e.clientX - r.left + 'px');
        card.style.setProperty('--my', e.clientY - r.top + 'px');
      });
    var pw = document.getElementById('password');
    var hint = document.getElementById('gcc-capslock');
    if (pw && hint) {
      var check = function (e) {
        if (e.getModifierState) hint.hidden = !e.getModifierState('CapsLock');
      };
      pw.addEventListener('keydown', check);
      pw.addEventListener('keyup', check);
      pw.addEventListener('blur', function () {
        hint.hidden = true;
      });
    }
  }

  // ------------------------------------------------------------------ network backdrop
  var PALETTE = {
    dark: { node: '96, 165, 250', hub: '56, 189, 248', link: '59, 130, 246', pulse: ['#38bdf8', '#2bc98c', '#60a5fa'], glow: '43, 201, 140' },
    light: { node: '37, 99, 235', hub: '2, 132, 199', link: '37, 99, 235', pulse: ['#0284c7', '#078e61', '#2563eb'], glow: '7, 142, 97' },
  };
  var LINK = 150;
  var NEAR = 190;

  function initNetwork() {
    var canvas = document.getElementById('gcc-network');
    var ctx = canvas && canvas.getContext('2d');
    if (!ctx) return function () {};
    var colors = PALETTE[theme()];
    var w = 0;
    var h = 0;
    var nodes = [];
    var pulses = [];
    var ripples = [];
    var ptr = { x: -9999, y: -9999, on: false };
    var frame = 0;
    var last = performance.now();
    var clock = 0;

    function seed() {
      var count = Math.round(Math.min(120, Math.max(36, (w * h) / 14000)));
      nodes = [];
      for (var i = 0; i < count; i++)
        nodes.push({ x: Math.random() * w, y: Math.random() * h, vx: (Math.random() - 0.5) * 0.25, vy: (Math.random() - 0.5) * 0.25, r: i % 9 === 0 ? 2.8 : 1.2 + Math.random() * 1.2, hub: i % 9 === 0, ph: Math.random() * 6.28 });
    }
    function resize() {
      var dpr = Math.min(window.devicePixelRatio || 1, 2);
      w = canvas.clientWidth;
      h = canvas.clientHeight;
      canvas.width = Math.floor(w * dpr);
      canvas.height = Math.floor(h * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      seed();
    }
    function spawn() {
      var a = Math.floor(Math.random() * nodes.length);
      var na = nodes[a];
      if (!na) return;
      var best = -1;
      var bestD = Infinity;
      for (var j = 0; j < nodes.length; j++) {
        if (j === a) continue;
        var d = Math.hypot(na.x - nodes[j].x, na.y - nodes[j].y);
        if (d < LINK && d > 30 && d < bestD && Math.random() > 0.35) {
          best = j;
          bestD = d;
        }
      }
      if (best >= 0) pulses.push({ a: a, b: best, t: 0, s: 0.5 + Math.random() * 0.7, c: colors.pulse[Math.floor(Math.random() * colors.pulse.length)] });
    }
    function draw(dt, time) {
      ctx.clearRect(0, 0, w, h);
      var step = dt / 16.67;
      var i, j, n, d;
      for (i = 0; i < nodes.length; i++) {
        n = nodes[i];
        if (reduced) continue;
        if (ptr.on) {
          var dx = ptr.x - n.x;
          var dy = ptr.y - n.y;
          d = Math.hypot(dx, dy);
          if (d < NEAR && d > 1) {
            var f = (1 - d / NEAR) * 0.0006;
            n.vx += dx * f;
            n.vy += dy * f;
          }
        }
        for (j = 0; j < ripples.length; j++) {
          var rx = n.x - ripples[j].x;
          var ry = n.y - ripples[j].y;
          d = Math.hypot(rx, ry);
          if (Math.abs(d - ripples[j].age * 0.45) < 24 && d > 1) {
            n.vx += (rx / d) * 0.35;
            n.vy += (ry / d) * 0.35;
          }
        }
        n.vx *= 0.985;
        n.vy *= 0.985;
        if (Math.hypot(n.vx, n.vy) < 0.08) {
          n.vx += (Math.random() - 0.5) * 0.02;
          n.vy += (Math.random() - 0.5) * 0.02;
        }
        n.x += n.vx * step;
        n.y += n.vy * step;
        if (n.x < -20) n.x = w + 20;
        if (n.x > w + 20) n.x = -20;
        if (n.y < -20) n.y = h + 20;
        if (n.y > h + 20) n.y = -20;
      }
      ctx.lineWidth = 1;
      for (i = 0; i < nodes.length; i++) {
        var a = nodes[i];
        for (j = i + 1; j < nodes.length; j++) {
          var b = nodes[j];
          d = Math.hypot(a.x - b.x, a.y - b.y);
          if (d > LINK) continue;
          var alpha = (1 - d / LINK) * 0.28;
          if (ptr.on) {
            var pd = Math.hypot((a.x + b.x) / 2 - ptr.x, (a.y + b.y) / 2 - ptr.y);
            if (pd < NEAR) alpha += (1 - pd / NEAR) * 0.4;
          }
          ctx.strokeStyle = 'rgba(' + colors.link + ',' + alpha + ')';
          ctx.beginPath();
          ctx.moveTo(a.x, a.y);
          ctx.lineTo(b.x, b.y);
          ctx.stroke();
        }
      }
      for (i = pulses.length - 1; i >= 0; i--) {
        var p = pulses[i];
        var pa = nodes[p.a];
        var pb = nodes[p.b];
        p.t += 0.012 * p.s * step;
        if (!pa || !pb || p.t >= 1 || Math.hypot(pa.x - pb.x, pa.y - pb.y) > LINK * 1.2) {
          pulses.splice(i, 1);
          continue;
        }
        var x = pa.x + (pb.x - pa.x) * p.t;
        var y = pa.y + (pb.y - pa.y) * p.t;
        var tail = Math.max(0, p.t - 0.18);
        var tx = pa.x + (pb.x - pa.x) * tail;
        var ty = pa.y + (pb.y - pa.y) * tail;
        var grad = ctx.createLinearGradient(tx, ty, x, y);
        grad.addColorStop(0, 'rgba(0,0,0,0)');
        grad.addColorStop(1, p.c);
        ctx.strokeStyle = grad;
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.moveTo(tx, ty);
        ctx.lineTo(x, y);
        ctx.stroke();
        ctx.fillStyle = p.c;
        ctx.shadowColor = p.c;
        ctx.shadowBlur = 12;
        ctx.beginPath();
        ctx.arc(x, y, 2.2, 0, 6.283);
        ctx.fill();
        ctx.shadowBlur = 0;
      }
      for (i = 0; i < nodes.length; i++) {
        n = nodes[i];
        var tw = reduced ? 1 : 0.75 + 0.25 * Math.sin(time / 900 + n.ph);
        var boost = 0;
        if (ptr.on) {
          d = Math.hypot(n.x - ptr.x, n.y - ptr.y);
          if (d < NEAR) boost = 1 - d / NEAR;
        }
        var r = n.r * (1 + boost * 0.9);
        if (n.hub || boost > 0.2) {
          var gl = ctx.createRadialGradient(n.x, n.y, 0, n.x, n.y, r * 7);
          gl.addColorStop(0, 'rgba(' + (n.hub ? colors.hub : colors.glow) + ',' + (0.28 * tw + boost * 0.3) + ')');
          gl.addColorStop(1, 'rgba(0,0,0,0)');
          ctx.fillStyle = gl;
          ctx.beginPath();
          ctx.arc(n.x, n.y, r * 7, 0, 6.283);
          ctx.fill();
        }
        ctx.fillStyle = 'rgba(' + (n.hub ? colors.hub : colors.node) + ',' + (0.55 * tw + boost * 0.45) + ')';
        ctx.beginPath();
        ctx.arc(n.x, n.y, r, 0, 6.283);
        ctx.fill();
      }
      for (i = ripples.length - 1; i >= 0; i--) {
        var rp = ripples[i];
        rp.age += dt;
        var ra = Math.max(0, 1 - rp.age / 1400);
        if (ra <= 0) {
          ripples.splice(i, 1);
          continue;
        }
        ctx.strokeStyle = 'rgba(' + colors.glow + ',' + ra * 0.6 + ')';
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        ctx.arc(rp.x, rp.y, rp.age * 0.45, 0, 6.283);
        ctx.stroke();
      }
    }
    function loop(now) {
      var dt = Math.min(64, now - last);
      last = now;
      clock += dt;
      if (clock > 140 && pulses.length < 26) {
        clock = 0;
        spawn();
      }
      draw(dt, now);
      frame = requestAnimationFrame(loop);
    }

    resize();
    window.addEventListener('resize', function () {
      resize();
      if (reduced) draw(16, 0);
    });
    window.addEventListener('pointermove', function (e) {
      ptr.x = e.clientX;
      ptr.y = e.clientY;
      ptr.on = true;
    }, { passive: true });
    document.addEventListener('pointerleave', function () {
      ptr.on = false;
    });
    window.addEventListener('pointerdown', function (e) {
      if (reduced || (e.target && e.target.closest && e.target.closest('input, button, a, label'))) return;
      ripples.push({ x: e.clientX, y: e.clientY, age: 0 });
      for (var k = 0; k < 6; k++) spawn();
    }, { passive: true });
    document.addEventListener('visibilitychange', function () {
      cancelAnimationFrame(frame);
      if (!document.hidden && !reduced) {
        last = performance.now();
        frame = requestAnimationFrame(loop);
      }
    });
    if (reduced) draw(16, 0);
    else frame = requestAnimationFrame(loop);

    // Theme change: recolour without reseeding.
    return function () {
      colors = PALETTE[theme()];
      if (reduced) draw(16, 0);
    };
  }

  ready(function () {
    var recolor = initNetwork();
    initTheme(recolor);
    initRotator();
    initRacks();
    initTilt();
    initCard();
  });
})();
