import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App.jsx";
import { purgeLegacyStorageIfNeeded } from "./utils/purgeLegacyStorage.js";
import "./index.css";

purgeLegacyStorageIfNeeded();

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
