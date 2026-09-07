export function RoleBadge({ label, pulsing = false }) {
  return (
    <span className="role-badge-v2">
      {pulsing && <span className="pulse-dot" />}
      {label}
    </span>
  );
}
