<script setup lang="ts">
import { computed, onMounted, watch } from "vue";
import { useMediaQuery } from "@vueuse/core";
import { useRoute } from "vue-router";
import { NAlert } from "naive-ui";

import { useSettingsStore } from "../stores/settings";
import SettingsActionsSection from "./settings/SettingsActionsSection.vue";
import SettingsDiagnosticsSection from "./settings/SettingsDiagnosticsSection.vue";
import SettingsDocsSection from "./settings/SettingsDocsSection.vue";
import SettingsJumpNav from "./settings/SettingsJumpNav.vue";
import SettingsPreferencesSection from "./settings/SettingsPreferencesSection.vue";
import SettingsRuntimeSections from "./settings/SettingsRuntimeSections.vue";
import SettingsSafetyStrip from "./settings/SettingsSafetyStrip.vue";
import { focusOnboardingChecklist } from "./settings/settingsDom";

const settings = useSettingsStore();
const route = useRoute();
const settingsData = computed(() => settings.settings);
const compactSettingsLayout = useMediaQuery("(max-width: 560px)");
const shouldFocusOnboardingChecklist = computed(
  () =>
    route?.query.onboarding === "1" &&
    settingsData.value !== null &&
    settings.onboarding?.visible === true,
);

watch(
  shouldFocusOnboardingChecklist,
  (shouldFocus) => {
    if (shouldFocus) {
      void focusOnboardingChecklist();
    }
  },
  { immediate: true, flush: "post" },
);

onMounted(() => {
  void (async () => {
    await settings.loadSettings();
    if (settings.coreUpdateTour === null) {
      await settings.loadCoreUpdateTour();
    }
  })().catch(() => undefined);
});
</script>

<template>
  <section class="content-stack">
    <n-alert v-if="settings.error" type="error" :show-icon="false">
      {{ settings.error }}
    </n-alert>

    <SettingsSafetyStrip v-if="settingsData" />
    <SettingsJumpNav v-if="settingsData" />
    <SettingsActionsSection
      v-if="settingsData"
      :compact="compactSettingsLayout"
    />
    <SettingsPreferencesSection
      v-if="settingsData"
      :compact="compactSettingsLayout"
    />
    <SettingsRuntimeSections :compact="compactSettingsLayout" />
    <SettingsDiagnosticsSection />
    <SettingsDocsSection />
  </section>
</template>
