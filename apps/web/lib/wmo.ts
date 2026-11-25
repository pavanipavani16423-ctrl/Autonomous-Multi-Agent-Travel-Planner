import {
  Cloud,
  CloudDrizzle,
  CloudFog,
  CloudLightning,
  CloudRain,
  CloudSnow,
  CloudSun,
  Sun,
  type LucideIcon,
} from "lucide-react";

/** WMO weather interpretation codes (as used by Open-Meteo) → label + icon. */
export function wmo(code: number): { label: string; Icon: LucideIcon; tone: "sun" | "cloud" | "rain" | "snow" | "storm" } {
  if (code === 0) return { label: "Clear", Icon: Sun, tone: "sun" };
  if (code === 1 || code === 2) return { label: code === 1 ? "Mostly clear" : "Partly cloudy", Icon: CloudSun, tone: "sun" };
  if (code === 3) return { label: "Overcast", Icon: Cloud, tone: "cloud" };
  if (code === 45 || code === 48) return { label: "Fog", Icon: CloudFog, tone: "cloud" };
  if (code >= 51 && code <= 57) return { label: "Drizzle", Icon: CloudDrizzle, tone: "rain" };
  if ((code >= 61 && code <= 67) || (code >= 80 && code <= 82)) return { label: "Rain", Icon: CloudRain, tone: "rain" };
  if ((code >= 71 && code <= 77) || code === 85 || code === 86) return { label: "Snow", Icon: CloudSnow, tone: "snow" };
  if (code >= 95) return { label: "Thunderstorm", Icon: CloudLightning, tone: "storm" };
  return { label: "Mixed", Icon: CloudSun, tone: "cloud" };
}
