import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App";
import { CatalogProvider } from "./state/catalog";
import { DialogProvider } from "./ui/Dialogs";
import { MenuProvider } from "./ui/Menu";
import { ToastProvider } from "./ui/Toasts";
import "./styles.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ToastProvider>
      <CatalogProvider>
        <DialogProvider>
          <MenuProvider>
            <App />
          </MenuProvider>
        </DialogProvider>
      </CatalogProvider>
    </ToastProvider>
  </StrictMode>,
);
