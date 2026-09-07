import { useCountUp } from "./useCountUp";

export function ScoreHeadline({ score, label = "/ 100", badge }) {
  const display = useCountUp(score);
  return (
    <div className="score-headline">
      <span className="score-number">{display}</span>
      <span className="score-label">{label}</span>
      {badge}
    </div>
  );
}
