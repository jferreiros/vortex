import "./ui.css";

// variant: "primary" | "secondary" | "ghost"
export default function Button({ variant = "primary", as: As = "button", className = "", ...rest }) {
  return <As className={`ui-button ui-button-${variant} ${className}`} {...rest} />;
}
