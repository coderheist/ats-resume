import { Link, Outlet, Route, Routes } from "react-router-dom";
import { Navbar } from "./components/Navbar";
import { ProtectedRoute } from "./components/ProtectedRoute";
import { Hero } from "./pages/Hero";
import { AuthPage } from "./pages/AuthPage";
import { DashboardPage } from "./pages/DashboardPage";
import { HistoryPage } from "./pages/HistoryPage";
import { PricingPage } from "./pages/PricingPage";
import { SettingsPage } from "./pages/SettingsPage";
import { FullReportView } from "./features/report/FullReportView";
import { StandaloneReportView } from "./features/report/StandaloneReportView";

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

function ReportPage({ title, children }) {
  return (
    <div className="app-shell">
      <header className="app-header">
        <Link to="/" className="btn-link" style={{ marginBottom: 16, display: "inline-block" }}>
          ← Back home
        </Link>
        <h1>{title}</h1>
      </header>
      {children}
    </div>
  );
}

export function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={<Hero />} />
        <Route
          path="/with-jd"
          element={
            <ReportPage title="Score against a job description">
              <FullReportView />
            </ReportPage>
          }
        />
        <Route
          path="/without-jd"
          element={
            <ReportPage title="General ATS readiness">
              <StandaloneReportView />
            </ReportPage>
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
  );
}
