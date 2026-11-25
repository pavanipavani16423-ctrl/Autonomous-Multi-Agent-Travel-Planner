import type { TripPlan } from "../types";
import sample from "./sample-plan.json";

/**
 * The plan the offline demo replays: a real run produced by the backend
 * (copied from docs/sample-plan.json). The scripted event stream (script.ts)
 * is derived from whatever plan is exported here.
 */
export const DEMO_PLAN: TripPlan = { ...(sample as unknown as TripPlan), trip_id: "demo" };
export const DEMO_ID = "demo";
