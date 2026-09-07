import { useId, useState } from "react";
import { Eye, EyeOff } from "lucide-react";

/**
 * The supplied auth-ui.tsx built this via @radix-ui/react-label +
 * class-variance-authority + tailwind-merge -- all Tailwind/shadcn
 * ecosystem utilities for composing className strings and Radix's
 * accessible label primitive. This app doesn't use Tailwind, and a
 * labeled input with a visibility-toggle button doesn't need Radix's
 * primitive to be accessible -- a real <label htmlFor> plus a real
 * <button aria-label> gets the same accessibility properties without
 * three extra dependencies for markup this simple.
 */
export function PasswordField({ label, id: providedId, ...inputProps }) {
  const autoId = useId();
  const id = providedId || autoId;
  const [visible, setVisible] = useState(false);

  return (
    <div className="form-field">
      {label && <label htmlFor={id}>{label}</label>}
      <div className="password-field-wrap">
        <input id={id} type={visible ? "text" : "password"} {...inputProps} />
        <button
          type="button"
          className="password-toggle"
          onClick={() => setVisible((v) => !v)}
          aria-label={visible ? "Hide password" : "Show password"}
        >
          {visible ? <EyeOff size={16} /> : <Eye size={16} />}
        </button>
      </div>
    </div>
  );
}
