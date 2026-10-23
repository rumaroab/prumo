import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "leaflet/dist/leaflet.css";
import "./styles.css";
import "./leaflet-locale";
import "./interface.css";
import "./design-tokens.css";
import App from "./App";
import { LoadingProvider } from "./loading";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <LoadingProvider>
      <App />
    </LoadingProvider>
  </StrictMode>,
);
