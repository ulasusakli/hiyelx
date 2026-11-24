import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";
import { StudioApp } from "./app/StudioApp.tsx";

const rootEl = document.getElementById("root");
if (rootEl !== null) {
  createRoot(rootEl).render(
    <StrictMode>
      <StudioApp />
    </StrictMode>,
  );
}
