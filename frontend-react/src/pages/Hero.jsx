import { useCallback, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { motion, useReducedMotion } from "framer-motion";
import { ScoreHeadline } from "../components/ScoreHeadline";
import { GaugeBar } from "../components/GaugeBar";
import { DimensionTile } from "../components/DimensionTile";

/**
 * Adapted from a supplied 21st.dev-style "scroll-locked video hero"
 * component (a music-streaming hero: video background, track carousel,
 * synthesized scroll-click audio). That content has nothing to do with
 * a resume tool, so it wasn't ported as-is. What WAS kept, because it
 * genuinely generalizes:
 *   - the cursor-tilt floating "screen" effect (pointermove -> rotateX/
 *     rotateY transform)
 *   - an immersive, drifting gradient background instead of flat color
 *   - glass-morphic chrome (blur + translucent panels)
 *   - the "shadcn-style CSS variable with a fallback" theming pattern,
 *     adapted to this app's actual hex tokens instead of the source's
 *     HSL-triplet convention
 * What was dropped entirely: the video, the track-list carousel and its
 * flick physics, and the synthesized mechanical scroll-click sound --
 * all specific to a music-player product, none of it appropriate here.
 * What replaced the video: a live, animated miniature of the actual
 * report UI (real ScoreHeadline/GaugeBar/DimensionTile components,
 * reused directly, not a mockup image) tilting in the same 3D space --
 * showing the real product is more honest and more effective than a
 * stock asset.
 */
export function Hero() {
  const cardRef = useRef(null);
  const reduceMotion = useReducedMotion();
  const [tiltStyle, setTiltStyle] = useState({});

  const onPointerMove = useCallback(
    (e) => {
      if (reduceMotion) return;
      const rect = cardRef.current?.getBoundingClientRect();
      if (!rect) return;
      const px = (e.clientX - rect.left) / rect.width - 0.5;
      const py = (e.clientY - rect.top) / rect.height - 0.5;
      setTiltStyle({
        transform: `rotateY(${px * 14}deg) rotateX(${-py * 10}deg) scale(1.01)`,
        transition: "transform 0.05s linear",
      });
    },
    [reduceMotion]
  );

  const onPointerLeave = useCallback(() => {
    setTiltStyle({
      transform: "rotateY(0deg) rotateX(0deg) scale(1)",
      transition: "transform 0.5s cubic-bezier(0.2,0.8,0.2,1)",
    });
  }, []);

  return (
    <section className="hero">
      <div className="hero-bg" aria-hidden="true">
        <motion.div
          className="hero-bg-glow hero-bg-glow-a"
          animate={reduceMotion ? {} : { transform: ["translate(0%,0%) scale(1)", "translate(4%,3%) scale(1.08)", "translate(0%,0%) scale(1)"] }}
          transition={{ duration: 14, repeat: Infinity, ease: "easeInOut" }}
        />
        <motion.div
          className="hero-bg-glow hero-bg-glow-b"
          animate={reduceMotion ? {} : { transform: ["translate(0%,0%) scale(1)", "translate(-5%,-3%) scale(1.1)", "translate(0%,0%) scale(1)"] }}
          transition={{ duration: 18, repeat: Infinity, ease: "easeInOut", delay: 1 }}
        />
      </div>

      <div className="hero-content">
        <div className="hero-copy">
          <p className="eyebrow">AI-ASSISTED RESUME ANALYSIS</p>
          <h1>Know exactly where your resume stands — before a recruiter does.</h1>
          <p className="hero-lede">
            Upload a resume, optionally add a job description, and get a real, evidence-based breakdown of what's
            working, what's missing, and what to fix first. Not a black-box score — an explanation.
          </p>
          <div className="hero-actions">
            <Link className="btn-primary" to="/with-jd">
              Analyze against a job description
            </Link>
            <Link className="btn-link" to="/without-jd">
              Or check general ATS readiness →
            </Link>
          </div>
        </div>

        <div className="hero-preview-wrap">
          <div
            ref={cardRef}
            className="hero-preview-card"
            style={tiltStyle}
            onPointerMove={onPointerMove}
            onPointerLeave={onPointerLeave}
          >
            <div className="hero-preview-inner">
              <p className="hero-preview-label">Live preview</p>
              <ScoreHeadline score={82} label="/ 100 match" badge={<span className="classification-pill">Strong Match</span>} />
              <GaugeBar value={82} />
              <div className="hero-preview-tiles">
                <DimensionTile label="Technical Skills" value={88} accent delay={0.1} />
                <DimensionTile label="Experience" value={74} accent delay={0.2} />
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
