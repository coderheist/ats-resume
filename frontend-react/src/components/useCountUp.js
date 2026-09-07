import { animate, useReducedMotion } from "framer-motion";
import { useEffect, useState } from "react";

/**
 * Ease-out-cubic count-up, same curve as the vanilla-JS console's
 * animateScoreNumber (cubic-bezier(0.2, 0.8, 0.2, 1)) so both frontends
 * feel identical. Framer Motion's built-in useReducedMotion() reads
 * prefers-reduced-motion directly -- no need to hand-roll a matchMedia
 * check like the vanilla version had to.
 */
export function useCountUp(target, { duration = 0.7, decimals = 1 } = {}) {
  const [display, setDisplay] = useState(0);
  const reduceMotion = useReducedMotion();

  useEffect(() => {
    if (typeof target !== "number" || Number.isNaN(target)) return;

    if (reduceMotion) {
      setDisplay(target);
      return;
    }

    const controls = animate(0, target, {
      duration,
      ease: [0.2, 0.8, 0.2, 1],
      onUpdate: (v) => setDisplay(v),
    });
    return () => controls.stop();
  }, [target, duration, reduceMotion]);

  return display.toFixed(decimals);
}
