<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { RouterLink, RouterView, useRoute, useRouter } from "vue-router";
import {
  Activity,
  AlertTriangle,
  BellOff,
  Clock3,
  ExternalLink,
  Info,
  LayoutDashboard,
  ListChecks,
  LogOut,
  Monitor,
  Moon,
  RefreshCw,
  Settings2,
  SlidersHorizontal,
  Stethoscope,
  Sun,
  Tags,
} from "@lucide/vue";

import { useAuthStore } from "./stores/auth";
import { useWebuiStore } from "./stores/webui";
import { themePreferenceLabels, useWebuiTheme } from "./theme";

const route = useRoute();
const router = useRouter();
const auth = useAuthStore();
const webui = useWebuiStore();
const {
  preference: themePreference,
  effectiveTheme,
  nextPreference,
  naiveTheme,
  themeOverrides,
  cycleThemePreference,
} = useWebuiTheme();

const RELEASES_URL = "https://github.com/magrhino/WUD-Updater/releases";
const VERSION_RELEASE_RE = /^v?\d+\.\d+/;
const selfUpdateDialogVisible = ref(false);

const showShell = computed(
  () => route.name !== "login" && route.name !== "setup" && auth.authenticated,
);
const appVersion = computed(() => webui.status?.version ?? "");
const appVersionIsRelease = computed(() =>
  VERSION_RELEASE_RE.test(appVersion.value),
);
const appVersionLabel = computed(() => {
  if (!appVersion.value) {
    return "";
  }
  if (appVersionIsRelease.value) {
    return appVersion.value.startsWith("v")
      ? appVersion.value
      : `v${appVersion.value}`;
  }
  return appVersion.value;
});
const appVersionHref = computed(() => {
  if (!appVersion.value || !appVersionIsRelease.value) {
    return RELEASES_URL;
  }
  return `${RELEASES_URL}/tag/${appVersionLabel.value}`;
});
const appVersionTitle = computed(() =>
  appVersionIsRelease.value
    ? `Open ${appVersionLabel.value} release notes`
    : "Open WUD-Updater releases",
);
const managedThemePreference = computed(() =>
  webui.settings?.managed.find((entry) => entry.key === "theme_preference"),
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
const selfUpdateVisible = computed(
  () => showShell.value && webui.selfUpdate?.status === "available",
);
const selfUpdateButtonDisabled = computed(
  () => webui.loading || !(webui.selfUpdate?.can_update ?? false),
);
const selfUpdateDisabledReason = computed(
  () => webui.selfUpdate?.disabled_reason ?? "",
);
const selfUpdateFacts = computed(() => {
  const update = webui.selfUpdate;
  if (!update) {
    return "";
  }
  const image = update.target_image || "image unavailable";
  const container = update.restart_container || "restart target unavailable";
  return `${image} -> ${container}`;
});
const selfUpdateReleaseCapTitle = computed(() => {
  const cap = webui.selfUpdate?.release_notes_cap ?? 10;
  return `Showing the newest ${cap} matching releases between the running version and latest version. Open GitHub releases for older notes.`;
});
const selfUpdateReleasesUrl = computed(() => {
  const latest = webui.selfUpdate?.latest_tag;
  return latest
    ? `${RELEASES_URL}/tag/${latest}`
    : RELEASES_URL;
});
const navItems = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard },
  { to: "/pending", label: "Pending", icon: ListChecks },
  { to: "/runs", label: "History", icon: Clock3 },
  { to: "/policies", label: "Policies", icon: Settings2 },
  { to: "/snoozes", label: "Snoozes", icon: BellOff },
  { to: "/tag-exclusions", label: "Exclusions", icon: Tags },
  { to: "/settings", label: "Settings", icon: SlidersHorizontal },
  { to: "/doctor", label: "Doctor", icon: Stethoscope },
];

watch(
  showShell,
  (visible) => {
    if (visible && webui.status === null) {
      void webui.loadStatus().catch(() => undefined);
    }
    if (visible && webui.settings === null) {
      void webui.loadSettings().catch(() => undefined);
    }
    if (visible && webui.coreUpdateTour === null) {
      void webui.loadCoreUpdateTour().catch(() => undefined);
    }
    if (visible && webui.selfUpdate === null) {
      void webui.loadSelfUpdate().catch(() => undefined);
    }
  },
  { immediate: true },
);

watch(
  managedThemePreference,
  (entry) => {
    if (
      auth.authenticated &&
      entry?.source === "configured" &&
      (entry.value === "system" || entry.value === "light" || entry.value === "dark") &&
      themePreference.value !== entry.value
    ) {
      themePreference.value = entry.value;
    }
  },
  { immediate: true },
);

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
  } else if (route.name === "settings") {
    await Promise.all([
      webui.loadSettings(),
      webui.loadOnboarding(),
      webui.loadCoreUpdateTour(),
    ]);
  } else if (route.name === "doctor") {
    await webui.loadDoctor();
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

async function confirmSelfUpdate(): Promise<void> {
  await webui.applySelfUpdate();
  selfUpdateDialogVisible.value = false;
}
</script>

<template>
  <n-config-provider :theme="naiveTheme" :theme-overrides="themeOverrides">
    <n-message-provider>
      <div class="app-shell" :class="{ centered: !showShell }">
        <aside v-if="showShell" class="sidebar">
          <RouterLink class="brand" to="/" aria-label="WUD-Updater dashboard">
            <Activity :size="22" />
            <span>WUD-Updater</span>
          </RouterLink>

          <nav class="nav-list">
            <RouterLink
              v-for="item in navItems"
              :key="item.to"
              class="nav-item"
              :to="item.to"
              :title="item.label"
              :aria-label="item.label"
            >
              <component :is="item.icon" :size="18" />
              <span>{{ item.label }}</span>
            </RouterLink>
          </nav>

          <div class="sidebar-footer">
            <n-tag
              v-if="appVersionLabel"
              class="version-tag"
              size="small"
            >
              <a
                class="version-link"
                :href="appVersionHref"
                target="_blank"
                rel="noopener noreferrer"
                :title="appVersionTitle"
                :aria-label="appVersionTitle"
              >
                {{ appVersionLabel }}
              </a>
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
                :title="themeButtonTitle"
                :aria-label="themeButtonAriaLabel"
                @click="cycleThemePreference"
              >
                <template #icon>
                  <component :is="themePreferenceIcon" :size="18" />
                </template>
              </n-button>
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

          <section
            v-if="selfUpdateVisible"
            class="self-update-banner"
            aria-label="WUD-Updater self-update"
          >
            <div class="self-update-banner-main">
              <AlertTriangle :size="20" aria-hidden="true" />
              <div>
                <strong>
                  Update available:
                  {{ webui.selfUpdate?.current_tag }} -> {{ webui.selfUpdate?.latest_tag }}
                </strong>
                <span>{{ selfUpdateFacts }}</span>
              </div>
            </div>
            <div class="self-update-banner-actions">
              <span
                v-if="selfUpdateDisabledReason"
                class="self-update-disabled"
              >
                {{ selfUpdateDisabledReason }}
              </span>
              <n-button
                type="primary"
                size="small"
                :disabled="selfUpdateButtonDisabled"
                :title="selfUpdateDisabledReason || 'Review release notes and update'"
                @click="selfUpdateDialogVisible = true"
              >
                Update
              </n-button>
            </div>
          </section>

          <n-alert
            v-if="webui.selfUpdateMessage"
            class="self-update-message"
            type="success"
            :show-icon="false"
          >
            {{ webui.selfUpdateMessage }}
          </n-alert>

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

        <n-modal
          v-model:show="selfUpdateDialogVisible"
          preset="dialog"
          title="Update WUD-Updater"
          positive-text="Pull image and restart container"
          negative-text="Cancel"
          :positive-button-props="{
            type: 'warning',
            loading: webui.loading,
            disabled: selfUpdateButtonDisabled,
          }"
          @positive-click="confirmSelfUpdate"
        >
          <div class="self-update-modal">
            <n-alert type="warning" :show-icon="false">
              This pulls the WUD-Updater image and restarts the WebUI container.
              The page may disconnect while Docker brings it back.
            </n-alert>

            <div class="self-update-facts">
              <div>
                <span>Image</span>
                <code>{{ webui.selfUpdate?.target_image || "unavailable" }}</code>
              </div>
              <div>
                <span>Container</span>
                <code>{{ webui.selfUpdate?.restart_container || "unavailable" }}</code>
              </div>
            </div>

            <div class="self-update-notes-heading">
              <strong>Release notes</strong>
              <n-tooltip trigger="hover">
                <template #trigger>
                  <span
                    class="self-update-cap"
                    tabindex="0"
                    :title="selfUpdateReleaseCapTitle"
                  >
                    <Info :size="14" aria-hidden="true" />
                    Cap {{ webui.selfUpdate?.release_notes_cap ?? 10 }}
                  </span>
                </template>
                {{ selfUpdateReleaseCapTitle }}
              </n-tooltip>
            </div>

            <div
              v-if="webui.selfUpdate?.release_notes.length"
              class="self-update-notes"
            >
              <article
                v-for="note in webui.selfUpdate.release_notes"
                :key="note.tag"
                class="self-update-note"
              >
                <div class="self-update-note-title">
                  <a
                    :href="note.url"
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    {{ note.title || note.tag }}
                    <ExternalLink :size="14" aria-hidden="true" />
                  </a>
                  <span>{{ note.published_at || note.tag }}</span>
                </div>
                <n-tag v-if="note.breaking" type="warning" size="small">
                  Review required
                </n-tag>
                <p>{{ note.body || "No release-note body was published." }}</p>
                <small v-if="note.body_truncated">
                  Release note body truncated in the WebUI. Open GitHub for the full text.
                </small>
              </article>
            </div>
            <p v-else class="self-update-empty-notes">
              Release notes are unavailable from the WebUI. Open GitHub releases before updating.
            </p>

            <a
              class="text-link self-update-github-link"
              :href="selfUpdateReleasesUrl"
              target="_blank"
              rel="noopener noreferrer"
            >
              Open GitHub releases
              <ExternalLink :size="14" aria-hidden="true" />
            </a>
          </div>
        </n-modal>
      </div>
    </n-message-provider>
  </n-config-provider>
</template>
