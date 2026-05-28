import { createApp } from "vue";
import { createPinia } from "pinia";
import {
  create,
  NAlert,
  NButton,
  NConfigProvider,
  NDataTable,
  NForm,
  NFormItem,
  NInput,
  NMessageProvider,
  NTag,
} from "naive-ui";

import App from "./App.vue";
import { router } from "./router";
import "./styles.css";

const naive = create({
  components: [
    NAlert,
    NButton,
    NConfigProvider,
    NDataTable,
    NForm,
    NFormItem,
    NInput,
    NMessageProvider,
    NTag,
  ],
});

const app = createApp(App);

app.use(createPinia());
app.use(router);
app.use(naive);

app.mount("#app");
