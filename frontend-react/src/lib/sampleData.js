// Matches frontend/app.js's SAMPLE_RESUME/SAMPLE_JD exactly -- both
// frontends should demo against the same data so results are comparable.
export const SAMPLE_RESUME = {
  schema_version: "v1.0.0",
  basics: {
    name: "Jordan Alvarez",
    label: "Backend Engineer",
    email: "jordan.alvarez@example.com",
    summary: "Backend engineer focused on scalable systems and developer tooling.",
    location: "Denver, CO",
  },
  work: [
    {
      name: "Northwind Data",
      position: "Software Engineer",
      start_date: "2021-03",
      end_date: null,
      highlights: [
        { text: "Led migration of the ingestion pipeline to a queue-based architecture, cutting processing latency 42%." },
        { text: "Scaled the primary Postgres cluster to handle 12,000 concurrent connections during peak load." },
        { text: "Built an internal React dashboard for on-call engineers to trace failed jobs." },
      ],
    },
    {
      name: "Fieldstone Labs",
      position: "Junior Software Engineer",
      start_date: "2019-06",
      end_date: "2021-02",
      highlights: [
        { text: "Implemented automated test coverage for the billing service, catching 15 regressions pre-release." },
      ],
    },
  ],
  education: [
    { institution: "Colorado State University", area: "Computer Science", study_type: "Bachelor", end_date: "2019-05" },
  ],
  skills: [
    { name: "Backend", keywords: ["software engineering", "python", "postgresql", "react"] },
    { name: "Infrastructure", keywords: ["docker", "aws"] },
  ],
  projects: [],
};

export const SAMPLE_JD = `We're hiring a Senior Software Engineer to join our backend platform team.

Requirements:
- 5+ years of professional software development experience
- Strong experience with React and PostgreSQL
- Experience scaling backend systems under real production load
- Familiarity with AWS and containerized deployments

You'll work closely with our data and infrastructure teams to build reliable, well-tested services.`;
