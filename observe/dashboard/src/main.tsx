import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./app/App.tsx";
import "./theme.css";

const host = document.getElementById("root");
if (host === null) throw new Error("missing #root");

createRoot(host).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
