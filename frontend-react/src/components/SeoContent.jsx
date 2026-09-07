/**
 * Static explanatory copy rendered beneath the tool on /with-jd and
 * /without-jd.
 *
 * Why this exists: both routes are almost entirely interactive UI — an
 * upload box and a results area that is empty until someone actually runs
 * a scan. Prerendered, they came out at roughly 280 characters of text,
 * which is a thin page by any measure. These are also the two routes
 * targeting the highest-intent searches ("resume job description match",
 * "ats resume score"), so leaving them contentless meant the pages most
 * worth ranking were the ones with nothing to rank.
 *
 * The copy is deliberately substantive and specific to each mode rather
 * than keyword padding — it describes what the tool on that page actually
 * does, which is both what a search engine rewards and what a visitor who
 * landed cold from a search result needs to read.
 */

const CONTENT = {
  "/with-jd": {
    heading: "Matching your resume to a job description",
    intro:
      "Paste any job posting and this page reports, requirement by requirement, how well your resume evidences what the job actually asks for — and what it would take to close each gap.",
    blocks: [
      {
        h: "Requirements are tiered by how the posting words them",
        p: "A job description does not weigh its own requirements equally, and neither should a match score. Phrases like \"must have\", \"required\", and \"minimum 5 years\" mark knockout requirements — the ones that filter applications out first. \"Preferred\", \"nice to have\", and \"a plus\" mark something far softer. The same skill can be a knockout in one posting and merely preferred in another, so tiering comes from the sentence it appears in, never from a fixed judgment about the skill itself.",
      },
      {
        h: "A keyword is not the same as evidence",
        p: "Listing a technology in a skills section, with no project or role that demonstrates it, is scored as weak evidence rather than a full match. That mirrors how a recruiter reads a resume: a keyword with nothing behind it does not show you can do the work. This is the single most common reason a skill you genuinely have still shows as a gap — the fix is a bullet describing what you built with it and what changed as a result.",
      },
      {
        h: "Every number comes with its reasoning",
        p: "The overall score is a weighted combination of seven dimensions, each reported separately with the weight it carries. Alongside it you get the specific requirements that failed, where in your resume each piece of supporting evidence was found, and a ranked list of changes ordered by how much each would move the score.",
      },
      {
        h: "What this cannot tell you",
        p: "This measures how well your resume evidences a specific posting's stated requirements. It does not predict whether you will get an interview, and it has no visibility into the other applicants, the hiring manager's priorities, or anything the posting left unwritten. A high score means your resume argues its case clearly for this job — which is the part you control.",
      },
    ],
  },
  "/without-jd": {
    heading: "Checking general ATS readiness",
    intro:
      "No job posting needed. This page scores how well your resume would survive an applicant tracking system and a recruiter's first pass, based on the qualities that hold up across every job you might apply to.",
    blocks: [
      {
        h: "What gets measured without a job description",
        p: "Five weighted checks: structural completeness against a standard resume schema, how many of your work bullets carry a quantified result, action-verb density, active versus passive voice, and skill coverage for the role your resume implies. Together these describe whether a resume is well built, independent of any particular posting.",
      },
      {
        h: "Quantified results carry the most weight after structure",
        p: "\"Responsible for the billing system\" and \"cut billing failures 40% by rewriting the retry logic\" describe the same job. Only the second gives a reader anything to evaluate. Bullets without a number, a percentage, or a time saved are flagged individually, so you can see exactly which lines are doing no work for you.",
      },
      {
        h: "Formatting problems that break resume parsers",
        p: "Multi-column layouts, tables, embedded images, and contact details placed in a header or footer are all common ways a visually polished resume becomes unreadable to the software that processes it first. Uploaded files are checked for each of these, and any risks found feed into the readability portion of the score.",
      },
      {
        h: "Role inference and its limits",
        p: "Skill coverage is measured against an inferred role, drawn from what your resume actually demonstrates rather than from your job title. That inference currently covers technical roles. If your resume does not overlap one of them, coverage is scored neutrally instead of penalised — an incomplete role vocabulary is not the same thing as a real gap in your skills, and scoring it as though it were would be misleading.",
      },
    ],
  },
};

export function SeoContent({ path }) {
  const content = CONTENT[path];
  if (!content) return null;

  return (
    <section className="landing-section seo-content" aria-labelledby="about-this-tool">
      <h2 id="about-this-tool">{content.heading}</h2>
      <p className="section-lede">{content.intro}</p>
      {content.blocks.map(({ h, p }) => (
        <div className="seo-content-block" key={h}>
          <h3>{h}</h3>
          <p>{p}</p>
        </div>
      ))}
    </section>
  );
}
