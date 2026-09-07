import { motion, useReducedMotion } from "framer-motion";

/**
 * One shimmering placeholder block. Matches the Figma skeleton frames'
 * shimmer spec: linear-gradient sweep, 1.4s linear loop, infinite.
 * Reduced-motion freezes to a flat mid-tone instead of looping, rather
 * than just running the animation at 0 duration (a frozen *mid-gradient*
 * frame would look like a rendering glitch, not a static placeholder).
 */
export function SkeletonBlock({ width = "100%", height = 14, radius = 4, style }) {
  const reduceMotion = useReducedMotion();

  if (reduceMotion) {
    return (
      <div
        style={{ width, height, borderRadius: radius, background: "var(--skeleton-base)", ...style }}
      />
    );
  }

  return (
    <motion.div
      style={{
        width,
        height,
        borderRadius: radius,
        backgroundImage:
          "linear-gradient(90deg, var(--skeleton-base) 25%, var(--skeleton-shimmer) 50%, var(--skeleton-base) 75%)",
        backgroundSize: "200% 100%",
        ...style,
      }}
      animate={{ backgroundPosition: ["200% 0%", "-200% 0%"] }}
      transition={{ duration: 1.4, repeat: Infinity, ease: "linear" }}
    />
  );
}
