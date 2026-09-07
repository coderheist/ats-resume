import { motion } from "framer-motion";

/**
 * Fade + translate-up reveal for a report section, delayed so the
 * headline score settles first before secondary content competes for
 * attention -- same intent as the vanilla console's revealStagger().
 * `order` controls the stagger position (0-indexed).
 */
export function FadeUpSection({ children, order = 0, baseDelay = 0.55, stagger = 0.09, className = "" }) {
  return (
    <motion.div
      className={`report-section ${className}`.trim()}
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, delay: baseDelay + order * stagger, ease: "easeOut" }}
    >
      {children}
    </motion.div>
  );
}
