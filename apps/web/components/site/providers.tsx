"use client";

import { MotionConfig } from "motion/react";

/** One place for client-wide context: motion honours the OS "reduce motion" setting everywhere. */
export function Providers({ children }: { children: React.ReactNode }) {
  return <MotionConfig reducedMotion="user">{children}</MotionConfig>;
}
