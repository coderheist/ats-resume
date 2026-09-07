import { useCallback, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { motion, useReducedMotion } from "framer-motion";
import { ScoreHeadline } from "../components/ScoreHeadline";
import { GaugeBar } from "../components/GaugeBar";
import { DimensionTile } from "../components/DimensionTile";
import { FAQ } from "../lib/seo";

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
    <>
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

      {/* Everything below is real, indexable page content. A landing page
          that is nothing but a hero and two buttons gives a search engine
          almost no text to rank, and gives a first-time visitor no answer
          to "what does this actually do". These sections serve both. */}
      <section className="landing-section" aria-labelledby="how-it-works">
        <h2 id="how-it-works">How the resume checker works</h2>
        <ol className="steps-list">
          <li>
            <h3>Upload your resume</h3>
            <p>
              PDF or DOCX, up to 10 MB — or paste it as plain text. Your resume is parsed into
              structured sections and checked for layout problems that break applicant tracking
              systems, like multi-column text and tables.
            </p>
          </li>
          <li>
            <h3>Add a job description — or don't</h3>
            <p>
              Paste a job posting to get a requirement-by-requirement match report. Skip it and
              you'll get a general ATS readiness score instead, based on structure, quantified
              achievements, action verbs, and skill coverage for your inferred role.
            </p>
          </li>
          <li>
            <h3>Fix what actually costs you points</h3>
            <p>
              Every requirement comes back with its match status, how strongly it's evidenced, and
              where that evidence was found. Suggestions are ranked by estimated score impact, so
              you start with the change that moves the number most.
            </p>
          </li>
        </ol>
      </section>

      <section className="landing-section" aria-labelledby="what-we-check">
        <h2 id="what-we-check">What gets scored</h2>
        <p className="section-lede">
          A job-description match is scored across seven weighted dimensions. No dimension is a
          black box — each reports its own score and the weight it carries.
        </p>
        <ul className="dimension-grid">
          <li>
            <h3>Knockout requirements</h3>
            <p>Mandatory requirements the posting words as "must have" or "required" — the ones that filter you out first.</p>
          </li>
          <li>
            <h3>Technical skills</h3>
            <p>Coverage of the skills the job asks for, weighted by how important the posting itself treats each one.</p>
          </li>
          <li>
            <h3>Semantic fit</h3>
            <p>How closely your resume's overall narrative mirrors the job's core responsibilities.</p>
          </li>
          <li>
            <h3>Experience match</h3>
            <p>Years of relevant experience against what the posting asks for, including stated ranges.</p>
          </li>
          <li>
            <h3>Project relevance</h3>
            <p>Whether your projects demonstrate the technologies this specific job cares about.</p>
          </li>
          <li>
            <h3>Education match</h3>
            <p>Degree level and field against any stated education requirement.</p>
          </li>
          <li>
            <h3>ATS readability</h3>
            <p>Structural completeness and formatting risks that can cause a parser to misread your resume.</p>
          </li>
        </ul>
      </section>

      <section className="landing-section" aria-labelledby="faq-heading">
        <h2 id="faq-heading">Frequently asked questions</h2>
        {/* Rendered from the same FAQ array that generates the FAQPage
            structured data in seo.js, so the markup can never advertise
            an answer this page doesn't actually show. <details> gives
            keyboard and screen-reader support with no JavaScript, and
            keeps the answer text in the DOM for crawlers even when
            visually collapsed. */}
        <div className="faq-list">
          {FAQ.map(({ q, a }) => (
            <details key={q} className="faq-item">
              <summary>
                <h3>{q}</h3>
              </summary>
              <p>{a}</p>
            </details>
          ))}
        </div>
      </section>

      <section className="landing-section landing-cta" aria-labelledby="cta-heading">
        <h2 id="cta-heading">Check your resume now</h2>
        <p className="section-lede">Free, and no account needed to run your first scan.</p>
        {/* Wording deliberately differs from the hero's two CTAs above.
            Repeating identical link text on one page is ambiguous for
            screen-reader users navigating by link list, and varied,
            descriptive anchor text is what search engines read as a
            signal of what the destination page is about. */}
        <div className="hero-actions">
          <Link className="btn-primary" to="/with-jd">
            Start a job description match
          </Link>
          <Link className="btn-link" to="/without-jd">
            Score my resume without a job posting →
          </Link>
        </div>
      </section>
    </>
  );
}
