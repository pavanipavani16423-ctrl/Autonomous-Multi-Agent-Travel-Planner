import {
  BookOpen,
  Bus,
  CloudSun,
  Coins,
  Landmark,
  MapPin,
  Moon,
  Network,
  ShoppingBag,
  Sparkles,
  Theater,
  Trees,
  UtensilsCrossed,
  type LucideIcon,
} from "lucide-react";
import type { ActivityCategory, BudgetCategory, CitationSource } from "./types";

export const CATEGORY: Record<ActivityCategory, { label: string; Icon: LucideIcon; color: string }> = {
  sight: { label: "Sight", Icon: Landmark, color: "#2f6f9f" },
  culture: { label: "Culture", Icon: Theater, color: "#8a4fb3" },
  food: { label: "Food", Icon: UtensilsCrossed, color: "#d07a12" },
  activity: { label: "Activity", Icon: Sparkles, color: "#d9472b" },
  transit: { label: "Transit", Icon: Bus, color: "#5b6b78" },
  shopping: { label: "Shopping", Icon: ShoppingBag, color: "#c2457a" },
  nature: { label: "Nature", Icon: Trees, color: "#2f8a5b" },
  nightlife: { label: "Nightlife", Icon: Moon, color: "#4b4fb8" },
};

export const SOURCE: Record<CitationSource, { label: string; Icon: LucideIcon }> = {
  wikivoyage: { label: "Wikivoyage guidebook", Icon: BookOpen },
  openstreetmap: { label: "OpenStreetMap", Icon: MapPin },
  "open-meteo": { label: "Open-Meteo", Icon: CloudSun },
  frankfurter: { label: "Frankfurter FX", Icon: Coins },
  "budget-analyst": { label: "Budget Analyst (A2A)", Icon: Network },
};

export const BUDGET_CATEGORY: Record<BudgetCategory, { label: string; color: string }> = {
  travel: { label: "Getting there", color: "#0e4a5c" },
  stay: { label: "Stays", color: "#d9472b" },
  food: { label: "Food", color: "#f2b33d" },
  activities: { label: "Activities", color: "#0f7f74" },
  transport: { label: "Local transport", color: "#7c8fa0" },
  misc: { label: "Other", color: "#b9a58a" },
};
