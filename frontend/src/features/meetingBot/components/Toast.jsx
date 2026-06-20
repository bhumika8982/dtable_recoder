import { useEffect } from "react";

// Minimal auto-dismissing toast (dark theme). type: "success" | "error".
export default function Toast({ message, type = "success", onClose, duration = 3500 }) {
  useEffect(() => {
    if (!message) return;
    const t = setTimeout(onClose, duration);
    return () => clearTimeout(t);
  }, [message, duration, onClose]);

  if (!message) return null;
  return (
    <div className={`mb-toast mb-toast-${type}`} role="status">
      {message}
    </div>
  );
}
