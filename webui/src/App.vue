<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { RouterView, useRoute, useRouter } from "vue-router";
import { Monitor, Moon, Sun } from "@lucide/vue";

import AppSelfUpdateBanner from "./components/app/AppSelfUpdateBanner.vue";
import AppSelfUpdateDialog from "./components/app/AppSelfUpdateDialog.vue";
import AppSidebar from "./components/app/AppSidebar.vue";
import AppTopbar from "./components/app/AppTopbar.vue";
import { useAuthStore } from "./stores/auth";
import { useConnectionStore } from "./stores/connection";
import { useSettingsStore } from "./stores/settings";
import { useUpdatesStore } from "./stores/updates";
import { useRunsStore } from "./stores/runs";
import { themePreferenceLabels, useWebuiTheme } from "./theme";
import { runInBackground } from "./utils/promises";

const route = useRoute();
const router = useRouter();
const auth = useAuthStore();
const connection = useConnectionStore();
const settings = useSettingsStore();
const updates = useUpdatesStore();
const runs = useRunsStore();
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
const appVersion = computed(() => connection.status?.version ?? "");
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
  settings.settings?.managed.find((entry) => entry.key === "theme_preference"),
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
  () => showShell.value && updates.selfUpdate?.status === "available",
);
const selfUpdateButtonDisabled = computed(
  () => updates.loading || !(updates.selfUpdate?.can_update ?? false),
);
const selfUpdateStrategy = computed(
  () => updates.selfUpdate?.strategy ?? "pull_image",
);
const selfUpdateConfirmDisabled = computed(
  () =>
    selfUpdateButtonDisabled.value ||
    (selfUpdateStrategy.value === "prepare_tag_update" &&
      updates.selfUpdatePlan === null),
);
const selfUpdateActionLabel = computed(() =>
  selfUpdateStrategy.value === "prepare_tag_update"
    ? "Prepare tag update"
    : "Pull image",
);
const selfUpdateActionTitle = computed(() => {
  if (selfUpdateDisabledReason.value) {
    return selfUpdateDisabledReason.value;
  }
  return selfUpdateStrategy.value === "prepare_tag_update"
    ? "Review release notes and prepare tag update"
    : "Review release notes and pull image";
});
const selfUpdateDisabledReason = computed(
  () => updates.selfUpdate?.disabled_reason ?? "",
);
const selfUpdateFacts = computed(() => {
  const update = updates.selfUpdate;
  if (!update) {
    return "";
  }
  const image = update.target_image || "image unavailable";
  const container = update.restart_container || "restart target unavailable";
  return `${image} -> ${container}`;
});
const selfUpdateReleaseCapTitle = computed(() => {
  const cap = updates.selfUpdate?.release_notes_cap ?? 10;
  return `Showing the newest ${cap} matching releases between the running version and latest version. Open GitHub releases for older notes.`;
});
const selfUpdateReleasesUrl = computed(() => {
  const latest = updates.selfUpdate?.latest_tag;
  return latest
    ? `${RELEASES_URL}/tag/${latest}`
    : RELEASES_URL;
});
const selfUpdatePlanStack = computed(() => updates.selfUpdatePlan?.plan.stacks[0]);
const selfUpdatePlanTagUpdates = computed(
  () => selfUpdatePlanStack.value?.tag_updates ?? [],
);

watch(
  showShell,
  (visible) => {
    if (visible && connection.status === null) {
      runInBackground(connection.loadStatus());
    }
    if (visible && settings.settings === null) {
      runInBackground(settings.loadSettings());
    }
    if (visible && settings.coreUpdateTour === null) {
      runInBackground(settings.loadCoreUpdateTour());
    }
    if (visible && updates.selfUpdate === null) {
      runInBackground(updates.loadSelfUpdate());
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
    await Promise.all([
      connection.loadStatus(),
      updates.loadPending(),
      runs.loadRuns(),
      settings.loadServicePolicies(),
      settings.loadSnoozes("active"),
      settings.loadTagExclusions("active"),
    ]);
  } else if (route.name === "pending") {
    await updates.loadPending();
  } else if (route.name === "retags") {
    await updates.loadRetagTargets();
  } else if (route.name === "runs" || route.name === "audit") {
    await runs.loadRuns();
  } else if (route.name === "policies") {
    await settings.loadServicePolicies();
  } else if (route.name === "snoozes") {
    await settings.loadSnoozes(settings.snoozeStateFilter);
  } else if (route.name === "tag-exclusions") {
    await settings.loadTagExclusions(settings.tagExclusionStatusFilter);
  } else if (route.name === "settings") {
    await Promise.all([
      settings.loadSettings(),
      settings.loadOnboarding(),
      settings.loadCoreUpdateTour(),
    ]);
  } else if (route.name === "doctor") {
    await connection.loadDoctor();
  } else if (route.name === "run-detail") {
    await runs.loadRunDetail(Number(route.params.id));
  } else if (route.name === "run-log") {
    await runs.loadRunLog(Number(route.params.id));
  }
}

async function handleLogout(): Promise<void> {
  await auth.logout();
  await router.replace({ name: "login" });
}

async function openSelfUpdateDialog(): Promise<void> {
  selfUpdateDialogVisible.value = true;
  if (
    updates.selfUpdate?.strategy === "prepare_tag_update" &&
    updates.selfUpdatePlan === null
  ) {
    await updates.planSelfUpdate().catch(() => undefined);
  }
}

async function confirmSelfUpdate(): Promise<void> {
  await updates.applySelfUpdate();
  selfUpdateDialogVisible.value = false;
}
</script>

<template>
  <n-config-provider :theme="naiveTheme" :theme-overrides="themeOverrides">
    <n-message-provider>
      <div class="app-shell" :class="{ centered: !showShell }">
        <AppSidebar
          v-if="showShell"
          :version-label="appVersionLabel"
          :version-href="appVersionHref"
          :version-title="appVersionTitle"
        />

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

          <AppSelfUpdateBanner
            v-if="selfUpdateVisible"
            :current-tag="updates.selfUpdate?.current_tag"
            :latest-tag="updates.selfUpdate?.latest_tag"
            :facts="selfUpdateFacts"
            :disabled-reason="selfUpdateDisabledReason"
            :button-disabled="selfUpdateButtonDisabled"
            :action-title="selfUpdateActionTitle"
            :action-label="selfUpdateActionLabel"
            @open="openSelfUpdateDialog"
          />

          <n-alert
            v-if="updates.selfUpdateMessage"
            class="self-update-message"
            type="success"
          >
            {{ updates.selfUpdateMessage }}
          </n-alert>
          <n-alert
            v-if="updates.selfUpdateError"
            class="self-update-message"
            type="error"
          >
            {{ updates.selfUpdateError }}
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

        <AppSelfUpdateDialog
          v-model:show="selfUpdateDialogVisible"
          :strategy="selfUpdateStrategy"
          :action-label="selfUpdateActionLabel"
          :loading="updates.loading"
          :confirm-disabled="selfUpdateConfirmDisabled"
          :self-update="updates.selfUpdate"
          :plan-stack="selfUpdatePlanStack"
          :tag-updates="selfUpdatePlanTagUpdates"
          :release-cap-title="selfUpdateReleaseCapTitle"
          :releases-url="selfUpdateReleasesUrl"
          @confirm="confirmSelfUpdate"
        />
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

.self-update-message {
  margin-bottom: 16px;
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
