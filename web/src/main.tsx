import { createRoot } from "react-dom/client";
import App from "./app/App.tsx";
import "./styles/index.css";
import { STANDALONE } from "./app/lib/runtime";

createRoot(document.getElementById("root")!).render(<App />);

// Offline app shell (production only; the dev server must never be cached).
if (import.meta.env.PROD && !STANDALONE && location.protocol.startsWith("http") && "serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js").catch(() => undefined);
  });
}
