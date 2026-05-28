<script setup lang="ts">
import { computed } from "vue";
import { RouterLink, RouterView, useRoute, useRouter } from "vue-router";
import {
  Activity,
  Clock3,
  LayoutDashboard,
  ListChecks,
  LogOut,
  RefreshCw,
  ShieldCheck,
} from "@lucide/vue";

import { useAuthStore } from "./stores/auth";
import { useWebuiStore } from "./stores/webui";

const route = useRoute();
const router = useRouter();
const auth = useAuthStore();
const webui = useWebuiStore();

const showShell = computed(
  () => route.name !== "login" && route.name !== "setup" && auth.authenticated,
);
const navItems = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard },
  { to: "/pending", label: "Pending", icon: ListChecks },
  { to: "/runs", label: "History", icon: Clock3 },
];

async function refreshCurrentView(): Promise<void> {
  if (route.name === "dashboard") {
    await webui.loadDashboard();
  } else if (route.name === "pending") {
    await webui.loadPending();
  } else if (route.name === "runs") {
    await webui.loadRuns();
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
  <n-config-provider>
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
              <n-button quaternary circle title="Refresh" @click="refreshCurrentView">
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
