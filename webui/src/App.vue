<script setup lang="ts">
import { computed } from "vue";
import { RouterLink, RouterView, useRoute, useRouter } from "vue-router";
import type { GlobalThemeOverrides } from "naive-ui";
import {
  Activity,
  BellOff,
  Clock3,
  LayoutDashboard,
  ListChecks,
  LogOut,
  RefreshCw,
  Settings2,
  ShieldCheck,
  Tags,
} from "@lucide/vue";

import { useAuthStore } from "./stores/auth";
import { useWebuiStore } from "./stores/webui";

const route = useRoute();
const router = useRouter();
const auth = useAuthStore();
const webui = useWebuiStore();
const fontFamily =
  'Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif';

const themeOverrides: GlobalThemeOverrides = {
  common: {
    baseColor: "#ffffff",
    bodyColor: "#f5f7f8",
    cardColor: "#ffffff",
    modalColor: "#ffffff",
    tableColor: "#ffffff",
    tableHeaderColor: "#f0f5f6",
    hoverColor: "#f9fbfc",
    inputColor: "#ffffff",
    inputColorDisabled: "#f9fbfc",
    borderColor: "#dbe3e6",
    dividerColor: "#e6ecef",
    primaryColor: "#137a63",
    primaryColorHover: "#106a58",
    primaryColorPressed: "#0c5748",
    primaryColorSuppl: "#137a63",
    infoColor: "#0f6fbd",
    infoColorHover: "#0d5f9f",
    infoColorPressed: "#0b4e84",
    infoColorSuppl: "#0f6fbd",
    successColor: "#137a63",
    successColorHover: "#106a58",
    successColorPressed: "#0c5748",
    successColorSuppl: "#137a63",
    warningColor: "#9a5b00",
    warningColorHover: "#824d00",
    warningColorPressed: "#663c00",
    warningColorSuppl: "#9a5b00",
    errorColor: "#b42318",
    errorColorHover: "#961b12",
    errorColorPressed: "#7a160f",
    errorColorSuppl: "#b42318",
    textColorBase: "#172026",
    textColor1: "#172026",
    textColor2: "#43525a",
    textColor3: "#65747a",
    textColorDisabled: "#65747a",
    placeholderColor: "#65747a",
    placeholderColorDisabled: "#65747a",
    iconColor: "#65747a",
    fontFamily,
    fontFamilyMono: '"SFMono-Regular", Consolas, "Liberation Mono", monospace',
    fontSize: "16px",
    borderRadius: "7px",
    borderRadiusSmall: "7px",
  },
};

const showShell = computed(
  () => route.name !== "login" && route.name !== "setup" && auth.authenticated,
);
const navItems = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard },
  { to: "/pending", label: "Pending", icon: ListChecks },
  { to: "/runs", label: "History", icon: Clock3 },
  { to: "/policies", label: "Policies", icon: Settings2 },
  { to: "/snoozes", label: "Snoozes", icon: BellOff },
  { to: "/tag-exclusions", label: "Exclusions", icon: Tags },
];

async function refreshCurrentView(): Promise<void> {
  if (route.name === "dashboard") {
    await webui.loadDashboard();
  } else if (route.name === "pending") {
    await webui.loadPending();
  } else if (route.name === "runs") {
    await webui.loadRuns();
  } else if (route.name === "policies") {
    await webui.loadServicePolicies();
  } else if (route.name === "snoozes") {
    await webui.loadSnoozes(webui.snoozeStateFilter);
  } else if (route.name === "tag-exclusions") {
    await webui.loadTagExclusions(webui.tagExclusionStatusFilter);
  } else if (route.name === "run-detail") {
    await webui.loadRunDetail(Number(route.params.id));
  } else if (route.name === "run-log") {
    await webui.loadRunLog(Number(route.params.id));
  }
}

async function handleLogout(): Promise<void> {
  await auth.logout();
  await router.replace({ name: "login" });
}
</script>

<template>
  <n-config-provider :theme-overrides="themeOverrides">
    <n-message-provider>
      <div class="app-shell" :class="{ centered: !showShell }">
        <aside v-if="showShell" class="sidebar">
          <RouterLink class="brand" to="/">
            <Activity :size="22" />
            <span>WUD-Updater</span>
          </RouterLink>

          <nav class="nav-list">
            <RouterLink
              v-for="item in navItems"
              :key="item.to"
              class="nav-item"
              :to="item.to"
            >
              <component :is="item.icon" :size="18" />
              <span>{{ item.label }}</span>
            </RouterLink>
          </nav>

          <div class="sidebar-footer">
            <n-tag
              size="small"
              :type="auth.session?.mutations_enabled ? 'warning' : 'success'"
            >
              <template #icon>
                <ShieldCheck :size="14" />
              </template>
              {{ auth.session?.mutations_enabled ? "Mutations enabled" : "Read-only" }}
            </n-tag>
          </div>
        </aside>

        <main class="main-panel">
          <header v-if="showShell" class="topbar">
            <div>
              <p class="eyebrow">WebUI</p>
              <h1>{{ String(route.meta.title ?? route.name ?? "Dashboard") }}</h1>
            </div>
            <div class="topbar-actions">
              <n-button
                quaternary
                circle
                title="Refresh"
                aria-label="Refresh current view"
                @click="refreshCurrentView"
              >
                <template #icon>
                  <RefreshCw :size="18" />
                </template>
              </n-button>
              <n-button quaternary title="Sign out" @click="handleLogout">
                <template #icon>
                  <LogOut :size="18" />
                </template>
                Sign out
              </n-button>
            </div>
          </header>

          <RouterView />
        </main>
      </div>
    </n-message-provider>
  </n-config-provider>
</template>
