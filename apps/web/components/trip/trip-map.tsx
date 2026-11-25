"use client";

import "maplibre-gl/dist/maplibre-gl.css";
import type { GeoJSONSource, Map as MlMap, Marker, TransformStyleFunction } from "maplibre-gl";
import { useEffect, useRef, useState } from "react";
import { usePrefersReducedMotion } from "@/lib/use-reduced-motion";
import { useResolvedTheme } from "@/lib/use-theme";

export interface MapPin {
  id: string;
  kind: "activity" | "stay" | "food";
  lat: number;
  lon: number;
  title: string;
  subtitle?: string;
  n?: number;
  color?: string;
}

const STYLE = {
  light: "https://tiles.openfreemap.org/styles/liberty",
  dark: "https://tiles.openfreemap.org/styles/dark",
};

const BED = `<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M2 20v-8a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v8"/><path d="M4 10V6a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2v4"/><path d="M12 4v6"/><path d="M2 18h20"/></svg>`;
const FORK = `<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 2v7c0 1.1.9 2 2 2h4a2 2 0 0 0 2-2V2"/><path d="M7 2v20"/><path d="M21 15V2a5 5 0 0 0-5 5v6c0 1.1.9 2 2 2h3Zm0 0v7"/></svg>`;

/**
 * The hosted OpenFreeMap styles carry US highway-shield layers whose filters MapLibre rejects with a
 * console warning per layer; they never render outside the US, so drop them.
 */
const dropShields: TransformStyleFunction = (_prev, next) => ({ ...next, layers: next.layers.filter((l) => !/shield/.test(l.id)) });

function pinElement(p: MapPin) {
  // MapLibre owns the outer element's transform (positioning); visuals live on an inner span we can scale.
  const el = document.createElement("button");
  el.type = "button";
  el.setAttribute("aria-label", `${p.n ? `Stop ${p.n}: ` : ""}${p.title}`);
  el.style.cssText = "background:none;border:0;padding:0;cursor:pointer;";
  const inner = document.createElement("span");
  inner.className = "pin-inner";
  const size = p.kind === "activity" ? 30 : 28;
  const bg = p.kind === "activity" ? p.color ?? "#d9472b" : p.kind === "stay" ? "#0e4a5c" : "#f2b33d";
  const fg = p.kind === "food" ? "#0f2430" : "#fff";
  inner.style.cssText = `display:flex;align-items:center;justify-content:center;width:${size}px;height:${size}px;border-radius:999px;border:2.5px solid #fff;background:${bg};color:${fg};box-shadow:0 4px 14px rgba(0,0,0,.28);transition:transform .25s cubic-bezier(.2,.8,.2,1),box-shadow .25s;font:700 12px/1 var(--font-manrope),system-ui,sans-serif;`;
  if (p.kind === "activity") inner.textContent = String(p.n ?? "");
  else inner.innerHTML = p.kind === "stay" ? BED : FORK;
  el.appendChild(inner);
  return el;
}

/**
 * MapLibre over keyless OpenFreeMap tiles: numbered stops for the selected day joined by a route
 * line, optional stay/food layers, fly-to on focus. The library loads client-side only.
 */
export default function TripMap({
  center,
  pins,
  route,
  focusId,
  onPinClick,
  className,
}: {
  center: { lat: number; lon: number };
  pins: MapPin[];
  route: [number, number][]; // [lon, lat]
  focusId?: string | null;
  onPinClick?: (id: string) => void;
  className?: string;
}) {
  const container = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MlMap | null>(null);
  const markers = useRef<Map<string, Marker>>(new Map());
  const libRef = useRef<typeof import("maplibre-gl") | null>(null);
  const routeRef = useRef(route);
  const [ready, setReady] = useState(0);
  const [failed, setFailed] = useState(false);
  const theme = useResolvedTheme();
  const reduce = usePrefersReducedMotion();
  const onClickRef = useRef(onPinClick);
  useEffect(() => {
    onClickRef.current = onPinClick;
    routeRef.current = route;
  });

  // create the map once
  useEffect(() => {
    let cancelled = false;
    let map: MlMap | null = null;
    let ro: ResizeObserver | null = null;
    const markerMap = markers.current;
    import("maplibre-gl")
      .then((lib) => {
        if (cancelled || !container.current) return;
        libRef.current = lib;
        lib.setWorkerUrl("/maplibre/maplibre-gl-worker.mjs");
        map = new lib.Map({
          container: container.current,
          style: STYLE[document.documentElement.classList.contains("dark") ? "dark" : "light"],
          center: [center.lon, center.lat],
          zoom: 12,
          attributionControl: { compact: true },
          cooperativeGestures: false,
          validateStyle: false,
          transformStyle: dropShields,
        });
        map.addControl(new lib.NavigationControl({ showCompass: false }), "top-right");
        // The free OpenFreeMap styles reference a few sprite images they don't ship; fill them with a
        // transparent pixel instead of letting MapLibre warn on every tile.
        map.setMissingStyleImageResolver((id) => {
          if (map && !map.hasImage(id)) map.addImage(id, { width: 1, height: 1, data: new Uint8Array(4) });
        });
        map.on("style.load", () => {
          if (!map) return;
          if (!map.getSource("route")) {
            map.addSource("route", { type: "geojson", data: { type: "Feature", properties: {}, geometry: { type: "LineString", coordinates: routeRef.current } } });
            map.addLayer({ id: "route-casing", type: "line", source: "route", paint: { "line-color": "#ffffff", "line-width": 7, "line-opacity": 0.85 }, layout: { "line-cap": "round", "line-join": "round" } });
            map.addLayer({ id: "route", type: "line", source: "route", paint: { "line-color": "#d9472b", "line-width": 3.5, "line-dasharray": [1.5, 1.2] }, layout: { "line-cap": "round", "line-join": "round" } });
          }
          setReady((n) => n + 1);
        });
        map.on("error", (e) => {
          // Tile hiccups are non-fatal; only a style failure leaves us with nothing to show.
          if (String(e?.error?.message ?? "").toLowerCase().includes("style")) setFailed(true);
        });
        mapRef.current = map;
        // Keep the canvas matched to its box (sheet open/close, layout shifts).
        ro = new ResizeObserver(() => map?.resize());
        ro.observe(container.current);
      })
      .catch(() => setFailed(true));
    return () => {
      cancelled = true;
      ro?.disconnect();
      markerMap.forEach((m) => m.remove());
      markerMap.clear();
      map?.remove();
      mapRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- the map is created once; later centre changes go through fitBounds
  }, []);

  // theme → swap basemap style (the route layer is re-added on style.load)
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    map.setStyle(STYLE[theme], { transformStyle: dropShields });
  }, [theme]);

  // markers
  useEffect(() => {
    const map = mapRef.current;
    const lib = libRef.current;
    if (!map || !lib || !ready) return;
    const existing = markers.current;
    const wanted = new Set(pins.map((p) => p.id));
    existing.forEach((m, id) => {
      if (!wanted.has(id)) {
        m.remove();
        existing.delete(id);
      }
    });
    pins.forEach((p) => {
      const prev = existing.get(p.id);
      if (prev) {
        prev.setLngLat([p.lon, p.lat]);
        const inner = prev.getElement().querySelector<HTMLElement>(".pin-inner");
        if (inner && p.kind === "activity") inner.textContent = String(p.n ?? "");
        return;
      }
      const el = pinElement(p);
      el.addEventListener("click", (e) => {
        e.stopPropagation();
        onClickRef.current?.(p.id);
      });
      const popup = new lib.Popup({ offset: 18, closeButton: false, closeOnClick: true }).setHTML(
        `<strong style="font-size:13px">${p.title.replace(/</g, "&lt;")}</strong>${p.subtitle ? `<div style="font-size:12px;opacity:.7;margin-top:2px">${p.subtitle.replace(/</g, "&lt;")}</div>` : ""}`,
      );
      const marker = new lib.Marker({ element: el }).setLngLat([p.lon, p.lat]).setPopup(popup).addTo(map);
      existing.set(p.id, marker);
    });
  }, [pins, ready]);

  // route line + fit to the visible pins
  const pinKey = pins.map((p) => `${p.id}:${p.lat.toFixed(4)},${p.lon.toFixed(4)}`).join("|");
  useEffect(() => {
    const map = mapRef.current;
    const lib = libRef.current;
    if (!map || !lib || !ready) return;
    const src = map.getSource("route") as GeoJSONSource | undefined;
    src?.setData({ type: "Feature", properties: {}, geometry: { type: "LineString", coordinates: route } });
    if (!pins.length) return;
    const bounds = new lib.LngLatBounds();
    pins.forEach((p) => bounds.extend([p.lon, p.lat]));
    map.fitBounds(bounds, { padding: { top: 70, bottom: 120, left: 60, right: 60 }, maxZoom: 14.5, duration: reduce ? 0 : 900 });
    // eslint-disable-next-line react-hooks/exhaustive-deps -- pinKey captures pins; route follows pins
  }, [pinKey, ready, reduce]);

  // focus: highlight + fly
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    markers.current.forEach((m, id) => {
      const on = id === focusId;
      m.getElement().style.zIndex = on ? "10" : "";
      const inner = m.getElement().querySelector<HTMLElement>(".pin-inner");
      if (!inner) return;
      inner.style.transform = on ? "scale(1.3)" : "";
      inner.style.boxShadow = on ? "0 0 0 5px rgba(217,71,43,.3), 0 6px 18px rgba(0,0,0,.35)" : "0 4px 14px rgba(0,0,0,.28)";
    });
    const target = focusId ? markers.current.get(focusId) : undefined;
    if (target) {
      const ll = target.getLngLat();
      if (reduce) map.jumpTo({ center: ll });
      else map.easeTo({ center: ll, zoom: Math.max(map.getZoom(), 14), duration: 700 });
    }
  }, [focusId, ready, reduce]);

  return (
    <div className={className}>
      <div ref={container} className="h-full w-full" aria-label="Trip map" role="region" />
      {failed && (
        <div className="absolute inset-0 flex items-center justify-center bg-bg-2 p-6 text-center text-sm text-ink-2">
          The map couldn&apos;t load right now. Every place still has its coordinates in the list.
        </div>
      )}
    </div>
  );
}
