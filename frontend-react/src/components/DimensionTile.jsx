import { motion, useReducedMotion } from "framer-motion";

export function DimensionTile({ label, value, accent = false, delay = 0 }) {
  const reduceMotion = useReducedMotion();
  return (
    <div className="readiness-tile-v2">
      <div className="tile-value-v2">{value.toFixed(0)}%</div>
      <div className="tile-label-v2">{label}</div>
      <div className="tile-track">
        <motion.div
          className={`tile-fill${accent ? "" : " match-fill"}`}
          initial={{ width: "0%" }}
          animate={{ width: `${Math.max(value, value > 0 ? 2 : 0)}%` }}
          transition={{ duration: reduceMotion ? 0 : 0.5, delay: reduceMotion ? 0 : delay, ease: [0.2, 0.8, 0.2, 1] }}
        />
      </div>
    </div>
  );
}
