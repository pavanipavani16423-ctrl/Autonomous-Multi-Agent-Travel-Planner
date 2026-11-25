import { daysBetweenInclusive, parseISODate, toISODate } from "./format";
import type { TripRequest } from "./types";

export const MAX_DAYS = 14;
const ISO = /^\d{4}-\d{2}-\d{2}$/;

/** Client-side mirror of the SPEC's request rules; the API re-validates. */
export function validateRequest(r: Partial<TripRequest>): Partial<Record<keyof TripRequest, string>> {
  const e: Partial<Record<keyof TripRequest, string>> = {};
  if (!r.destination?.trim()) e.destination = "Where are you going?";
  const today = toISODate(new Date());
  if (!r.start_date || !ISO.test(r.start_date) || !r.end_date || !ISO.test(r.end_date)) {
    e.start_date = "Pick your travel dates.";
  } else if (parseISODate(r.end_date) < parseISODate(r.start_date)) {
    e.start_date = "The trip has to end after it starts.";
  } else if (daysBetweenInclusive(r.start_date, r.end_date) > MAX_DAYS) {
    e.start_date = `Trips can be up to ${MAX_DAYS} days.`;
  } else if (r.start_date < today) {
    e.start_date = "Dates must be in the future.";
  }
  if (!r.adults || r.adults < 1) e.adults = "At least one adult travels.";
  if ((r.children ?? 0) < 0) e.children = "Children can't be negative.";
  if (!r.budget || !(r.budget > 0)) e.budget = "Set a total budget for the group.";
  if (!r.currency || r.currency.length !== 3) e.currency = "Choose a currency.";
  return e;
}

export function defaultRequest(partial: Partial<TripRequest> = {}): TripRequest {
  const start = new Date();
  start.setDate(start.getDate() + 30);
  const end = new Date(start);
  end.setDate(end.getDate() + 3);
  return {
    destination: "",
    origin: "",
    start_date: toISODate(start),
    end_date: toISODate(end),
    adults: 2,
    children: 0,
    budget: 150000,
    currency: "INR",
    interests: [],
    pace: "balanced",
    diet: [],
    stay_style: "mid",
    notes: "",
    ...Object.fromEntries(Object.entries(partial).filter(([, v]) => v !== null && v !== undefined)),
  };
}
