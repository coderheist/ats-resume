import { motion } from "framer-motion";

const listVariants = {
  hidden: {},
  visible: { transition: { staggerChildren: 0.08 } },
};
const itemVariants = {
  hidden: { opacity: 0, y: 8 },
  visible: { opacity: 1, y: 0, transition: { duration: 0.35, ease: "easeOut" } },
};

/**
 * kind: "strengths" | "gaps" | "warnish" | "suggestions" (suggestions
 * gets numbered badges instead of a plain marker -- matches the vanilla
 * console's bulletList() so both frontends read the same way).
 */
export function BulletList({ items, kind, emptyText }) {
  if (!items || items.length === 0) {
    return <p className="tag-empty">{emptyText}</p>;
  }
  return (
    <motion.ul
      className={`bullet-list ${kind}`}
      variants={listVariants}
      initial="hidden"
      animate="visible"
    >
      {items.map((text, i) => (
        <motion.li key={i} variants={itemVariants}>
          {kind === "suggestions" && <span className="bullet-num">{i + 1}</span>}
          {text}
        </motion.li>
      ))}
    </motion.ul>
  );
}
