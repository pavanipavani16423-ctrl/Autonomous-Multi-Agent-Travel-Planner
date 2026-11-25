"use client";

import { useEffect, useRef } from "react";
import { LAND_DOTS } from "@/lib/globe-dots";
import { usePrefersReducedMotion } from "@/lib/use-reduced-motion";
import { useResolvedTheme } from "@/lib/use-theme";

export interface GlobeCity {
  name: string;
  lat: number;
  lon: number;
}

const RAD = Math.PI / 180;
const TILT = -22 * RAD; // look slightly down on the northern hemisphere

type Vec = [number, number, number];
const toVec = (lat: number, lon: number): Vec => [Math.cos(lat * RAD) * Math.cos(lon * RAD), Math.cos(lat * RAD) * Math.sin(lon * RAD), Math.sin(lat * RAD)];

function slerp(a: Vec, b: Vec, t: number): Vec {
  const dot = Math.min(1, Math.max(-1, a[0] * b[0] + a[1] * b[1] + a[2] * b[2]));
  const om = Math.acos(dot);
  if (om < 1e-6) return a;
  const s = Math.sin(om);
  const ka = Math.sin((1 - t) * om) / s;
  const kb = Math.sin(t * om) / s;
  return [a[0] * ka + b[0] * kb, a[1] * ka + b[1] * kb, a[2] * ka + b[2] * kb];
}

/**
 * Hand-rolled orthographic dotted globe on canvas (no geo library): ~2.7k land dots, great-circle
 * route arcs that draw themselves, and a plane-dot riding each arc. Pauses off-screen; static when
 * the user prefers reduced motion.
 */
export function Globe({ cities, routes, className }: { cities: GlobeCity[]; routes: [string, string][]; className?: string }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const theme = useResolvedTheme();
  const reduce = usePrefersReducedMotion();

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const css = getComputedStyle(document.documentElement);
    const ink = css.getPropertyValue("--ink").trim() || "#0f2430";
    const coral = css.getPropertyValue("--coral").trim() || "#d9472b";
    const sun = css.getPropertyValue("--sun").trim() || "#f2b33d";
    const dark = theme === "dark";

    // Precompute dot trig once.
    const n = LAND_DOTS.length / 2;
    const cosLat = new Float32Array(n);
    const sinLat = new Float32Array(n);
    const lon = new Float32Array(n);
    for (let i = 0; i < n; i++) {
      const lo = (LAND_DOTS[i * 2] / 10) * RAD;
      const la = (LAND_DOTS[i * 2 + 1] / 10) * RAD;
      lon[i] = lo;
      cosLat[i] = Math.cos(la);
      sinLat[i] = Math.sin(la);
    }
    const byName = new Map(cities.map((c) => [c.name, c]));
    const arcs = routes
      .map(([a, b]) => [byName.get(a), byName.get(b)] as const)
      .filter((p): p is readonly [GlobeCity, GlobeCity] => !!p[0] && !!p[1])
      .map(([a, b]) => ({ a: toVec(a.lat, a.lon), b: toVec(b.lat, b.lon) }));

    let w = 0;
    let h = 0;
    let dpr = 1;
    const resize = () => {
      const rect = canvas.getBoundingClientRect();
      dpr = Math.min(window.devicePixelRatio || 1, 2);
      w = rect.width;
      h = rect.height;
      canvas.width = Math.round(w * dpr);
      canvas.height = Math.round(h * dpr);
    };
    resize();
    const ro = new ResizeObserver(resize);
    ro.observe(canvas);

    const cosT = Math.cos(TILT);
    const sinT = Math.sin(TILT);
    // Project a unit vector (x toward lon 0, z north) for view longitude `l0`; returns screen + depth.
    const project = (v: Vec, l0: number, R: number, cx: number, cy: number, k = 1) => {
      const cl = Math.cos(-l0);
      const sl = Math.sin(-l0);
      const x1 = v[0] * cl - v[1] * sl;
      const y1 = v[0] * sl + v[1] * cl;
      const z1 = v[2];
      // after rotation, the viewer looks along +x; screen-x = y1, screen-y = z1 (tilted)
      const depth = x1 * cosT - z1 * sinT;
      const sy = x1 * sinT + z1 * cosT;
      return { x: cx + R * k * y1, y: cy - R * k * sy, z: depth };
    };

    let raf = 0;
    let running = true;
    const t0 = performance.now();

    const draw = (now: number) => {
      const t = reduce ? 9000 : now - t0;
      const R = Math.min(w, h) * 0.41;
      const cx = w / 2;
      const cy = h / 2;
      // Sway between the Atlantic and Japan so every route arc stays on the visible face.
      const l0 = (62 + Math.sin(t / 9000) * 62) * RAD;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, w, h);

      // atmosphere + ocean disc
      const halo = ctx.createRadialGradient(cx, cy, R * 0.92, cx, cy, R * 1.2);
      halo.addColorStop(0, dark ? "rgba(69,199,181,0.18)" : "rgba(14,74,92,0.12)");
      halo.addColorStop(1, "rgba(0,0,0,0)");
      ctx.fillStyle = halo;
      ctx.beginPath();
      ctx.arc(cx, cy, R * 1.2, 0, Math.PI * 2);
      ctx.fill();
      const disc = ctx.createRadialGradient(cx - R * 0.35, cy - R * 0.4, R * 0.1, cx, cy, R);
      disc.addColorStop(0, dark ? "#123642" : "#fffaf0");
      disc.addColorStop(1, dark ? "#081d25" : "#e9e0cf");
      ctx.fillStyle = disc;
      ctx.beginPath();
      ctx.arc(cx, cy, R, 0, Math.PI * 2);
      ctx.fill();

      // land dots
      ctx.fillStyle = ink;
      const cl = Math.cos(-l0);
      const sl = Math.sin(-l0);
      const ds = Math.max(1, R / 210);
      for (let i = 0; i < n; i++) {
        const cLo = Math.cos(lon[i]);
        const sLo = Math.sin(lon[i]);
        const vx = cosLat[i] * cLo;
        const vy = cosLat[i] * sLo;
        const x1 = vx * cl - vy * sl;
        const y1 = vx * sl + vy * cl;
        const depth = x1 * cosT - sinLat[i] * sinT;
        if (depth <= 0.02) continue;
        const sy = x1 * sinT + sinLat[i] * cosT;
        ctx.globalAlpha = (dark ? 0.3 : 0.28) + depth * (dark ? 0.6 : 0.62);
        ctx.fillRect(cx + R * y1 - ds / 2, cy - R * sy - ds / 2, ds * 1.15, ds * 1.15);
      }
      ctx.globalAlpha = 1;

      // route arcs
      const cycle = 5200;
      arcs.forEach((arc, idx) => {
        const local = ((t + idx * 1700) % cycle) / cycle; // 0..1
        const grow = reduce ? 1 : Math.min(1, local / 0.55);
        const fade = reduce ? 1 : local < 0.8 ? 1 : 1 - (local - 0.8) / 0.2;
        const steps = 48;
        const pts: { x: number; y: number; z: number }[] = [];
        for (let s = 0; s <= steps * grow; s++) {
          const u = s / steps;
          const v = slerp(arc.a, arc.b, u);
          pts.push(project(v, l0, R, cx, cy, 1 + 0.16 * Math.sin(Math.PI * u)));
        }
        if (pts.length < 2) return;
        ctx.lineWidth = 1.6;
        ctx.lineCap = "round";
        for (let s = 1; s < pts.length; s++) {
          const p = pts[s];
          const q = pts[s - 1];
          const vis = Math.max(0, Math.min(1, (Math.min(p.z, q.z) + 0.25) * 2));
          if (vis <= 0) continue;
          ctx.strokeStyle = coral;
          ctx.globalAlpha = vis * fade * (0.35 + 0.65 * (s / pts.length));
          ctx.beginPath();
          ctx.moveTo(q.x, q.y);
          ctx.lineTo(p.x, p.y);
          ctx.stroke();
        }
        const head = pts[pts.length - 1];
        if (head.z > -0.2 && grow < 1) {
          ctx.globalAlpha = fade;
          ctx.fillStyle = coral;
          ctx.shadowColor = coral;
          ctx.shadowBlur = 12;
          ctx.beginPath();
          ctx.arc(head.x, head.y, 3.2, 0, Math.PI * 2);
          ctx.fill();
          ctx.shadowBlur = 0;
        }
        ctx.globalAlpha = 1;
      });

      // city markers
      ctx.font = `600 ${Math.max(10, R / 28)}px ${css.getPropertyValue("--font-manrope") || "sans-serif"}`;
      for (const c of cities) {
        const p = project(toVec(c.lat, c.lon), l0, R, cx, cy);
        if (p.z <= 0.05) continue;
        const pulse = reduce ? 0 : (Math.sin(t / 600 + c.lon) + 1) / 2;
        ctx.globalAlpha = Math.min(1, p.z * 1.6);
        ctx.fillStyle = sun;
        ctx.beginPath();
        ctx.arc(p.x, p.y, 3 + pulse * 1.2, 0, Math.PI * 2);
        ctx.fill();
        ctx.strokeStyle = dark ? "#061217" : "#fffdf9";
        ctx.lineWidth = 1.5;
        ctx.stroke();
        ctx.fillStyle = ink;
        ctx.globalAlpha = Math.min(0.85, p.z * 1.4);
        ctx.fillText(c.name, p.x + 7, p.y + 4);
      }
      ctx.globalAlpha = 1;

      if (running && !reduce) raf = requestAnimationFrame(draw);
    };

    const start = () => {
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(draw);
    };
    const io = new IntersectionObserver(([entry]) => {
      running = entry.isIntersecting && !document.hidden;
      if (running) start();
    });
    io.observe(canvas);
    const onVis = () => {
      running = !document.hidden;
      if (running) start();
    };
    document.addEventListener("visibilitychange", onVis);
    start();

    return () => {
      running = false;
      cancelAnimationFrame(raf);
      ro.disconnect();
      io.disconnect();
      document.removeEventListener("visibilitychange", onVis);
    };
  }, [cities, routes, theme, reduce]);

  return <canvas ref={canvasRef} className={className} role="img" aria-label="A rotating globe with flight routes between destinations" />;
}
