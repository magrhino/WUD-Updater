import { createApp } from "vue";
import { createPinia } from "pinia";
import {
  create,
  NAlert,
  NButton,
  NCheckbox,
  NConfigProvider,
  NDataTable,
  NForm,
  NFormItem,
  NInput,
  NInputNumber,
  NMessageProvider,
  NModal,
  NSelect,
  NSwitch,
  NTag,
} from "naive-ui";

import App from "./App.vue";
import { router } from "./router";
import "./styles.css";

const naive = create({
  components: [
    NAlert,
    NButton,
    NCheckbox,
    NConfigProvider,
    NDataTable,
    NForm,
    NFormItem,
    NInput,
    NInputNumber,
    NMessageProvider,
    NModal,
    NSelect,
    NSwitch,
    NTag,
  ],
});

const app = createApp(App);

app.use(createPinia());
app.use(router);
app.use(naive);

app.mount("#app");
