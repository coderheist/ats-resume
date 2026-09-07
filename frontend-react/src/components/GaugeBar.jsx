import { motion, useReducedMotion } from "framer-motion";

export function GaugeBar({ value, delay = 0 }) {
  const reduceMotion = useReducedMotion();
  return (
    <div className="gauge-track">
      <motion.div
        className="gauge-fill"
        initial={{ width: "0%" }}
        animate={{ width: `${Math.max(value, value > 0 ? 1.5 : 0)}%` }}
        transition={{ duration: reduceMotion ? 0 : 0.7, delay: reduceMotion ? 0 : delay, ease: [0.2, 0.8, 0.2, 1] }}
      />
    </div>
  );
}
