<script setup lang="ts">
import { computed } from "vue";
import { RouterView, useRoute, useRouter } from "vue-router";
import { Monitor, Moon, Sun } from "@lucide/vue";

import AppSelfUpdatePanel from "./components/app/AppSelfUpdatePanel.vue";
import AppSidebar from "./components/app/AppSidebar.vue";
import AppTopbar from "./components/app/AppTopbar.vue";
import { provideRouteRefreshRegistry } from "./components/app/routeRefresh";
import { useAuthStore } from "./stores/auth";
import { themePreferenceLabels, useWebuiTheme } from "./theme";

const route = useRoute();
const router = useRouter();
const auth = useAuthStore();
const {
  preference: themePreference,
  effectiveTheme,
  nextPreference,
  naiveTheme,
  themeOverrides,
  cycleThemePreference,
} = useWebuiTheme();
const routeRefreshRegistry = provideRouteRefreshRegistry();

const showShell = computed(
  () => route.name !== "login" && route.name !== "setup" && auth.authenticated,
);
const themePreferenceIcon = computed(() => {
  if (themePreference.value === "dark") {
    return Moon;
  }
  if (themePreference.value === "light") {
    return Sun;
  }
  return Monitor;
});
const themeButtonTitle = computed(() => {
  const systemState =
    themePreference.value === "system" ? ` (${effectiveTheme.value})` : "";
  return `Theme: ${themePreferenceLabels[themePreference.value]}${systemState}`;
});
const themeButtonAriaLabel = computed(
  () =>
    `${themeButtonTitle.value}. Switch to ${themePreferenceLabels[
      nextPreference.value
    ].toLowerCase()}.`,
);

async function refreshCurrentView(): Promise<void> {
  await routeRefreshRegistry.refresh();
}

async function handleLogout(): Promise<void> {
  await auth.logout();
  await router.replace({ name: "login" });
}
</script>

<template>
  <n-config-provider :theme="naiveTheme" :theme-overrides="themeOverrides">
    <n-message-provider>
      <div class="app-shell" :class="{ centered: !showShell }">
        <AppSidebar v-if="showShell" />

        <main class="main-panel">
          <AppTopbar
            v-if="showShell"
            :title="String(route.meta.title ?? route.name ?? 'Dashboard')"
            :theme-button-title="themeButtonTitle"
            :theme-button-aria-label="themeButtonAriaLabel"
            :theme-preference-icon="themePreferenceIcon"
            @cycle-theme="cycleThemePreference"
            @refresh="refreshCurrentView"
            @logout="handleLogout"
          />

          <AppSelfUpdatePanel v-if="showShell" />

          <RouterView v-slot="routeSlot">
            <Transition name="route-shift" mode="out-in">
              <component
                v-if="routeSlot?.Component"
                :is="routeSlot.Component"
                :key="route.fullPath"
              />
            </Transition>
          </RouterView>
        </main>
      </div>
    </n-message-provider>
  </n-config-provider>
</template>

<style scoped>
.app-shell {
  display: grid;
  grid-template-columns: 248px minmax(0, 1fr);
  min-height: 100vh;
}

.app-shell.centered {
  display: block;
}

.main-panel {
  min-width: 0;
  padding: 24px;
}

@media (max-width: 920px) {
  .app-shell {
    grid-template-columns: minmax(0, 1fr);
  }

  .main-panel {
    padding: 16px;
  }
}

@media (max-width: 560px) {
  :deep(.inline-actions .n-button) {
    min-width: 44px;
    min-height: 44px;
  }

  :deep(.inline-actions .n-button--circle) {
    min-width: 44px;
  }
}
</style>
