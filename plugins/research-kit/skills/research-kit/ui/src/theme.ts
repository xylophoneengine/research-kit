export type Theme = "light" | "dark";

const KEY = "rk-ui-theme";

// the stored choice, else the system preference
export function initialTheme(): Theme {
  try {
    const v = localStorage.getItem(KEY);
    if (v === "light" || v === "dark") return v;
  } catch {
    // storage blocked: fall through to the system preference
  }
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

// sets or removes the `dark` class that index.css keys its variables on
export function applyTheme(t: Theme): void {
  document.documentElement.classList.toggle("dark", t === "dark");
}

export function storeTheme(t: Theme): void {
  try {
    localStorage.setItem(KEY, t);
  } catch {
    // storage blocked: the choice just does not persist
  }
}
