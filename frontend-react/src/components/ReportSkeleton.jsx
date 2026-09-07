import { SkeletonBlock } from "./SkeletonBlock";

/**
 * Matches the layout grid of the real report (header / score card /
 * tile row / list section) block-for-block, per the Figma skeleton
 * frames -- so swapping skeleton -> real content causes no layout
 * shift, and the shape of what's coming is legible before it arrives.
 */
export function ReportSkeleton({ tileCount = 3, listRows = 3 }) {
  return (
    <div className="score-card" role="status" aria-busy="true" aria-label="Loading report">
      <div style={{ display: "flex", flexDirection: "column", gap: 10, marginBottom: 8 }}>
        <SkeletonBlock width={280} height={12} />
        <SkeletonBlock width={420} height={26} />
        <SkeletonBlock width="90%" height={14} />
      </div>

      <div style={{ display: "flex", alignItems: "center", gap: 16, marginBottom: 12 }}>
        <SkeletonBlock width={110} height={44} radius={6} />
        <SkeletonBlock width={90} height={14} />
      </div>
      <SkeletonBlock width="100%" height={10} radius={999} style={{ marginBottom: 20 }} />

      <div className="tile-row" data-testid="tile-row">
        {Array.from({ length: tileCount }).map((_, i) => (
          <div
            key={i}
            style={{
              flex: 1,
              padding: 18,
              background: "var(--paper-raised)",
              border: "1px solid var(--rule)",
              borderRadius: "var(--radius-md)",
              display: "flex",
              flexDirection: "column",
              gap: 10,
            }}
          >
            <SkeletonBlock width={60} height={24} />
            <SkeletonBlock width={140} height={12} />
            <SkeletonBlock width="100%" height={6} radius={999} />
          </div>
        ))}
      </div>

      <SkeletonBlock width={260} height={14} style={{ marginBottom: 14 }} />
      <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
        {Array.from({ length: listRows }).map((_, i) => (
          <div key={i} style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <SkeletonBlock width={20} height={20} radius={999} />
            <SkeletonBlock width={`${90 - i * 12}%`} height={14} />
          </div>
        ))}
      </div>
    </div>
  );
}
