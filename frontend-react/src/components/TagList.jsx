export function TagList({ items, kind, emptyText }) {
  if (!items || items.length === 0) {
    return <span className="tag-empty">{emptyText}</span>;
  }
  return (
    <div className="tag-list">
      {items.map((item) => (
        <span key={item} className={`tag ${kind}`}>
          {item}
        </span>
      ))}
    </div>
  );
}
