export function SectionHeader({ icon: Icon, title, tone }) {
  return (
    <div className={`section-header ${tone || ""}`.trim()}>
      {Icon && <Icon size={15} />}
      <p>{title}</p>
    </div>
  );
}
