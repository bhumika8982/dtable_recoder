import { useEffect, useState } from "react";

// Persisted light/dark theme switch. Applies `data-theme` on <html> so the
// CSS variables in styles.css can swap the whole palette. Defaults to the
// user's OS preference on first visit, then remembers their choice.
function initialTheme() {
  const saved = localStorage.getItem("mb-theme");
  if (saved === "light" || saved === "dark") return saved;
  return window.matchMedia?.("(prefers-color-scheme: light)").matches ? "light" : "dark";
}

export default function ThemeToggle() {
  const [theme, setTheme] = useState(initialTheme);

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem("mb-theme", theme);
  }, [theme]);

  const isLight = theme === "light";
  return (
    <button
      type="button"
      className="theme-toggle"
      onClick={() => setTheme(isLight ? "dark" : "light")}
      title={isLight ? "Switch to dark mode" : "Switch to light mode"}
      aria-label={isLight ? "Switch to dark mode" : "Switch to light mode"}
    >
      <span className="theme-toggle-icon">{isLight ? "🌙" : "☀️"}</span>
      <span className="theme-toggle-label">{isLight ? "Dark" : "Light"}</span>
    </button>
  );
}
