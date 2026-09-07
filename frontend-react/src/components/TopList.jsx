import { motion } from "framer-motion";
import { useState } from "react";
import { ChevronDown } from "lucide-react";

/**
 * Caps a list to its top N items (already-ranked data in, e.g.
 * suggestions sorted by estimated impact -- this component doesn't
 * re-rank anything itself) with a "Show N more" toggle rather than
 * either dumping the whole list at once or permanently hiding the rest.
 * Nothing is truly lost, just collapsed by default -- a report that
 * hides data outright would be worse than one that's just busy.
 *
 * Generic over how each item actually renders (a render prop) so the
 * same expand/collapse behavior works for BulletList-style text,
 * TagList-style pills, or requirement rows -- one implementation of
 * "top N, expandable" instead of three copies of the same toggle logic.
 */
export function TopList({ items, limit = 5, emptyText, children }) {
  const [expanded, setExpanded] = useState(false);

  if (!items || items.length === 0) {
    return <p className="tag-empty">{emptyText}</p>;
  }

  const visible = expanded ? items : items.slice(0, limit);
  const remaining = items.length - limit;

  return (
    <div>
      {children(visible)}
      {remaining > 0 && (
        <button className="top-list-toggle" onClick={() => setExpanded((e) => !e)}>
          <motion.span animate={{ rotate: expanded ? 180 : 0 }} transition={{ duration: 0.2 }}>
            <ChevronDown size={14} />
          </motion.span>
          {expanded ? "Show less" : `Show ${remaining} more`}
        </button>
      )}
    </div>
  );
}
