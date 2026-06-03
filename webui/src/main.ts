import { createApp } from "vue";
import { createPinia } from "pinia";
import {
  create,
  NAlert,
  NButton,
  NConfigProvider,
  NMessageProvider,
  NModal,
  NTag,
  NTooltip,
} from "naive-ui";

import App from "./App.vue";
import { router } from "./router";
import { applyThemeCssVars, detectInitialEffectiveTheme } from "./theme";
import "./styles.css";

const naive = create({
  components: [
    NAlert,
    NButton,
    NConfigProvider,
    NMessageProvider,
    NModal,
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
