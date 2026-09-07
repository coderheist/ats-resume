# Resume Optimizer — React Report App

React rebuild covering the landing/hero page and the two report flows (JD Match's Full Report, and the Standalone/No-JD report) — see the main project `README.md`'s "React report app" and "Hero section" writeups for the full design/architecture notes, including the Figma file this was built from.

## Routes

- `/` — hero/landing page (with navbar), links into the two flows below
- `/with-jd` — score a resume against a job description
- `/without-jd` — general ATS readiness, no job description needed
- `/login`, `/signup` — auth UI preview (see main README's "Landing page, Login, Signup" section — **not connected to a real backend yet**, honestly labeled as a preview)

## Quick start

```bash
npm install
npm run dev
```

Then open http://localhost:5174. This proxies API calls straight to a FastAPI backend running on `:8000` (`cd .. && uvicorn app.main:app --reload`, from the project root, after `pip install -r requirements.txt`).

## Scripts

- `npm run dev` — dev server with hot reload, port 5174
- `npm run build` — production build to `../frontend-react-dist`
- `npm run preview` — serve the production build locally, port 5175 (calls the API directly, needs CORS — already in the project's `.env.example`)
- `npm test` — Vitest + React Testing Library, 100 tests

## Not in scope for this app (see the main console instead)

Bias Audit, Voice Editor, Gap Resolution, and Pricing — those live in `../frontend/`, unchanged.
