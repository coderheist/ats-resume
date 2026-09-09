import { Suspense, lazy } from "react";
import { Link, Outlet, Route, Routes } from "react-router-dom";
import { Navbar } from "./components/Navbar";
import { ProtectedRoute } from "./components/ProtectedRoute";
import { SeoContent } from "./components/SeoContent";
import { useSeo } from "./lib/useSeo";
import { Hero } from "./pages/Hero";
import { PricingPage } from "./pages/PricingPage";
import { FullReportView } from "./features/report/FullReportView";
import { StandaloneReportView } from "./features/report/StandaloneReportView";

/**
 * Code-split the routes a first-time visitor never lands on.
 *
 * Every route below is marked noindex in lib/seo.js -- they are
 * authenticated surfaces and the auth pages themselves. Nobody arrives on
 * one from a search result, so their JavaScript has no business being in
 * the bundle that blocks the landing page's first render. Largest
 * Contentful Paint is a ranking signal, and this is the cheapest real
 * reduction available without restructuring how Firebase is loaded.
 *
 * The public routes (Hero, the two report views, Pricing) stay eagerly
 * imported on purpose: those are the pages people land on, and making
 * them wait on a second network round trip to become interactive would
 * trade a real usability cost for a smaller headline bundle number.
 */
const AuthPage = lazy(() => import("./pages/AuthPage").then((m) => ({ default: m.AuthPage })));
const DashboardPage = lazy(() => import("./pages/DashboardPage").then((m) => ({ default: m.DashboardPage })));
const HistoryPage = lazy(() => import("./pages/HistoryPage").then((m) => ({ default: m.HistoryPage })));
const SettingsPage = lazy(() => import("./pages/SettingsPage").then((m) => ({ default: m.SettingsPage })));

function Layout() {
  return (
    <>
      <a href="#main-content" className="skip-link">
        Skip to main content
      </a>
      <Navbar />
      <main id="main-content">
        <Outlet />
      </main>
    </>
  );
}

function ReportPage({ title, path, children }) {
  return (
    <div className="app-shell">
      <header className="app-header">
        <Link to="/" className="btn-link" style={{ marginBottom: 16, display: "inline-block" }}>
          ← Back home
        </Link>
        <h1>{title}</h1>
      </header>
      {children}
      {/* Rendered after the tool so it never pushes the actual interface
          below the fold. Both routes are otherwise almost pure UI, which
          prerendered to ~280 characters of text -- see SeoContent's
          docstring. */}
      <SeoContent path={path} />
    </div>
  );
}

export function App() {
  // One call at the root rather than per page: seo.js's PAGE_SEO already
  // maps every route, so a new route can't ship having forgotten it, and
  // the title/description actually change on client-side navigation
  // instead of every route inheriting index.html's defaults.
  useSeo();

  return (
    <Suspense fallback={<div className="route-loading" role="status" aria-live="polite">Loading…</div>}>
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={<Hero />} />
        {/* Both scoring tools require an account. They were previously
            open to anyone, which let a signed-out visitor burn analysis
            runs with no way to attribute them to a user, save the report
            to history, or enforce the plan entitlements the backend
            hands out per account. ProtectedRoute remembers the path and
            AuthPage returns the visitor here after they sign in, so the
            gate costs one login rather than the errand they came for. */}
        <Route
          path="/with-jd"
          element={
            <ProtectedRoute>
              <ReportPage title="Score against a job description" path="/with-jd">
                <FullReportView />
              </ReportPage>
            </ProtectedRoute>
          }
        />
        <Route
          path="/without-jd"
          element={
            <ProtectedRoute>
              <ReportPage title="General ATS readiness" path="/without-jd">
                <StandaloneReportView />
              </ReportPage>
            </ProtectedRoute>
          }
        />
        <Route path="/pricing" element={<PricingPage />} />
        <Route
          path="/dashboard"
          element={
            <ProtectedRoute>
              <DashboardPage />
            </ProtectedRoute>
          }
        />
        <Route
          path="/settings"
          element={
            <ProtectedRoute>
              <SettingsPage />
            </ProtectedRoute>
          }
        />
        <Route
          path="/history"
          element={
            <ProtectedRoute>
              <HistoryPage />
            </ProtectedRoute>
          }
        />
      </Route>
      {/* Auth pages render without the marketing navbar -- the split-screen
          layout is its own full-page composition, same convention as most
          real products (no site nav duplicating the "back"/toggle links
          the auth page already provides). */}
      <Route path="/login" element={<AuthPage mode="signin" />} />
      <Route path="/signup" element={<AuthPage mode="signup" />} />
    </Routes>
    </Suspense>
  );
}
