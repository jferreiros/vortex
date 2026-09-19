import "./ui.css";

export default function SectionHeader({ eyebrow, title, subtitle, action }) {
  return (
    <div className="ui-section-header">
      <div>
        {eyebrow && <span className="ui-section-eyebrow">{eyebrow}</span>}
        {title && <h2 className="ui-section-title">{title}</h2>}
        {subtitle && <p className="ui-section-subtitle">{subtitle}</p>}
      </div>
      {action && <div className="ui-section-action">{action}</div>}
    </div>
  );
}
