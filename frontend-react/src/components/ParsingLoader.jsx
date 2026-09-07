import { motion } from "framer-motion";

/**
 * Adapted from a supplied "ai-loader" component (a full-screen rotating
 * glow ring + letter-pulse text, styled via Next.js `<style jsx>`).
 * Three real departures from the source, not oversights:
 *
 * 1. Rebuilt with Framer Motion instead of raw CSS `@keyframes` +
 *    `<style jsx>` -- the latter is a Next.js-specific mechanism that
 *    doesn't exist in this plain Vite/React app, and Framer Motion was
 *    the explicit ask for this round of work anyway.
 * 2. Reskinned entirely to this app's own tokens (--ink, --accent,
 *    --match) rather than the source's navy-blue/sky palette --
 *    "same theme as the application" was explicit. The technique (a
 *    dark backdrop so the glow actually reads, per how box-shadow glow
 *    effects behave against light vs. dark) is kept; the color scheme
 *    coming from the rest of this app's own gradient/glow language
 *    (see Hero.jsx's background glows, AuthPage's side panel) is not.
 * 3. Genuinely full-screen (fixed inset-0) as in the source, used as a
 *    real takeover during resume parsing specifically -- a brief,
 *    focused moment where a deliberate visual break from the light
 *    paper theme reads as intentional emphasis, not an inconsistency.
 */
const LETTER_VARIANTS = {
  animate: (i) => ({
    opacity: [0.4, 1, 0.7, 0.4],
    scale: [1, 1.15, 1, 1],
    transition: { duration: 3, repeat: Infinity, delay: i * 0.1, ease: "easeInOut" },
  }),
};

export function ParsingLoader({ text = "Analyzing" }) {
  const letters = text.split("");

  return (
    <div className="parsing-loader-overlay" role="status" aria-live="polite" aria-label={`${text}…`}>
      <div className="parsing-loader-stage">
        <motion.div
          className="parsing-loader-ring"
          animate={{ rotate: 360 }}
          transition={{ duration: 5, repeat: Infinity, ease: "linear" }}
        />
        <div className="parsing-loader-text">
          {letters.map((letter, i) => (
            <motion.span key={i} custom={i} variants={LETTER_VARIANTS} animate="animate">
              {letter === " " ? "\u00A0" : letter}
            </motion.span>
          ))}
        </div>
      </div>
    </div>
  );
}
