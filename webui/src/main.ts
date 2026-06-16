import { createApp } from "vue";
import { createPinia } from "pinia";
import {
  create,
  NAlert,
  NButton,
  NConfigProvider,
  NMessageProvider,
  NModal,
  NTabPane,
  NTabs,
  NTag,
  NTooltip,
} from "naive-ui";

import App from "./App.vue";
import { router } from "./router";
import { applyThemeCssVars, detectInitialEffectiveTheme } from "./theme";
import "./assets/styles/foundation.css";
import "./assets/styles/base.css";
import "./assets/styles/transitions.css";
import "./assets/styles/utilities.css";
import "./assets/styles/surfaces.css";
import "./assets/styles/preflight.css";
import "./assets/styles/data-tables.css";

const naive = create({
  components: [
    NAlert,
    NButton,
    NConfigProvider,
    NMessageProvider,
    NModal,
    NTabPane,
    NTabs,
    NTag,
    NTooltip,
  ],
});

const app = createApp(App);

applyThemeCssVars(detectInitialEffectiveTheme());

app.use(createPinia());
app.use(router);
app.use(naive);

app.mount("#app");
