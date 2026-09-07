export function KnockoutBanner({ risk }) {
  const isHigh = risk === "HIGH";
  return (
    <div className={`knockout-banner ${isHigh ? "high" : "low"}`}>
      Knockout Risk: {risk}
    </div>
  );
}
