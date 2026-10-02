import { createRoot } from "react-dom/client";
import App from "./App.tsx";
import "./index.css";
import "./i18n";
import { installGoogleTranslateReactFix } from "./lib/googleTranslateReactFix";

// Guard React against Google Translate mutating the DOM (prevents removeChild
// crashes on Radix portals). Must run before the first render.
installGoogleTranslateReactFix();

createRoot(document.getElementById("root")!).render(<App />);
