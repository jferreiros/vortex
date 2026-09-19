import "./ui.css";

// padding: "sm" | "md" | "lg"
export default function Card({ padding = "md", className = "", children, ...rest }) {
  return (
    <div className={`ui-card ui-card-pad-${padding} ${className}`} {...rest}>
      {children}
    </div>
  );
}
