<script setup lang="ts">
import { computed, ref, watch, type Component } from "vue";
import { RouterLink, RouterView, useRoute, useRouter } from "vue-router";
import {
  Activity,
  ArrowUpCircle,
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
  Repeat2,
  Settings2,
  SlidersHorizontal,
  Stethoscope,
  Sun,
  Tags,
} from "@lucide/vue";
import { NFlex } from "naive-ui";

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

type NavItem = {
  to: string;
  label: string;
  icon: Component;
  activeRouteNames: string[];
};

const navItems: NavItem[] = [
  {
    to: "/",
    label: "Dashboard",
    icon: LayoutDashboard,
    activeRouteNames: ["dashboard"],
  },
  {
    to: "/pending",
    label: "Pending",
    icon: ListChecks,
    activeRouteNames: ["pending"],
  },
  {
    to: "/retags",
    label: "Retags",
    icon: Repeat2,
    activeRouteNames: ["retags"],
  },
  {
    to: "/runs",
    label: "History",
    icon: Clock3,
    activeRouteNames: ["runs", "audit", "run-detail", "run-log"],
  },
  {
    to: "/policies",
    label: "Policies",
    icon: Settings2,
    activeRouteNames: ["policies"],
  },
  {
    to: "/snoozes",
    label: "Snoozes",
    icon: BellOff,
    activeRouteNames: ["snoozes"],
  },
  {
    to: "/tag-exclusions",
    label: "Exclusions",
    icon: Tags,
    activeRouteNames: ["tag-exclusions"],
  },
  {
    to: "/settings",
    label: "Settings",
    icon: SlidersHorizontal,
    activeRouteNames: ["settings"],
  },
  {
    to: "/doctor",
    label: "Doctor",
    icon: Stethoscope,
    activeRouteNames: ["doctor"],
  },
];

function isNavItemActive(item: NavItem): boolean {
  return (
    typeof route.name === "string" &&
    item.activeRouteNames.includes(route.name)
  );
}

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
              :class="{ 'nav-item-active': isNavItemActive(item) }"
              :to="item.to"
              :title="item.label"
              :aria-label="item.label"
              :aria-current="isNavItemActive(item) ? 'page' : undefined"
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
              <h1>{{ String(route.meta.title ?? route.name ?? "Dashboard") }}</h1>
            </div>
            <n-flex class="topbar-actions" align="center" :size="8">
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
            </n-flex>
          </header>

          <section
            v-if="selfUpdateVisible"
            class="self-update-banner"
            aria-label="WUD-Updater self-update"
          >
            <div class="self-update-banner-main">
              <ArrowUpCircle :size="20" aria-hidden="true" />
              <div>
                <strong>
                  Update available:
                  {{ updates.selfUpdate?.current_tag }} &rarr; {{ updates.selfUpdate?.latest_tag }}
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
                :title="selfUpdateActionTitle"
                @click="openSelfUpdateDialog"
              >
                {{ selfUpdateActionLabel }}
              </n-button>
            </div>
          </section>

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

        <n-modal
          v-model:show="selfUpdateDialogVisible"
          preset="dialog"
          title="Update WUD-Updater"
          :positive-text="selfUpdateActionLabel"
          negative-text="Cancel"
          :positive-button-props="{
            type: 'warning',
            loading: updates.loading,
            disabled: selfUpdateConfirmDisabled,
          }"
          @positive-click="confirmSelfUpdate"
        >
          <div class="self-update-modal">
            <n-alert
              v-if="selfUpdateStrategy === 'prepare_tag_update'"
              type="warning"
            >
              This updates the Compose image tag and pulls the image. Recreate
              the WUD-Updater container from outside the WebUI to run it.
            </n-alert>
            <n-alert v-else type="warning">
              This pulls the WUD-Updater image only. Recreate the container
              outside the WebUI to run the new version.
            </n-alert>

            <n-tabs type="line" animated>
              <n-tab-pane name="overview" tab="Update Plan">
                <div style="display: grid; gap: 14px; margin-top: 14px;">
                  <div class="self-update-facts">
                    <div>
                      <span>Image</span>
                      <code>{{ updates.selfUpdate?.target_image || "unavailable" }}</code>
                    </div>
                    <div>
                      <span>Container</span>
                      <code>{{ updates.selfUpdate?.restart_container || "unavailable" }}</code>
                    </div>
                  </div>

                  <div
                    v-if="selfUpdateStrategy === 'prepare_tag_update'"
                    class="self-update-plan"
                    style="display: grid; gap: 14px;"
                  >
                    <div class="self-update-notes-heading">
                      <strong>Compose tag update</strong>
                      <span v-if="updates.loading" class="self-update-disabled">
                        Loading preview
                      </span>
                    </div>
                    <template v-if="selfUpdatePlanStack">
                      <div class="self-update-facts">
                        <div>
                          <span>Stack</span>
                          <code>{{ selfUpdatePlanStack.name }}</code>
                        </div>
                        <div>
                          <span>Services</span>
                          <code>{{ selfUpdatePlanStack.services.join(", ") }}</code>
                        </div>
                      </div>
                      <div class="self-update-tag-updates">
                        <div
                          v-for="item in selfUpdatePlanTagUpdates"
                          :key="`${item.old_image}:${item.desired_tag}`"
                        >
                          <span>{{ item.old_image }} &rarr;</span>
                          <code>{{ item.new_image }}</code>
                        </div>
                      </div>
                    </template>
                    <n-alert v-else type="info">
                      Generating Compose tag-update preview.
                    </n-alert>
                  </div>
                </div>
              </n-tab-pane>

              <n-tab-pane name="notes" tab="Release Notes">
                <div style="display: grid; gap: 14px; margin-top: 14px;">
                  <div class="self-update-notes-heading">
                    <strong>Release notes</strong>
                    <n-tooltip trigger="hover">
                      <template #trigger>
                        <button
                          type="button"
                          class="self-update-cap"
                          :title="selfUpdateReleaseCapTitle"
                        >
                          <Info :size="14" aria-hidden="true" />
                          Cap {{ updates.selfUpdate?.release_notes_cap ?? 10 }}
                        </button>
                      </template>
                      {{ selfUpdateReleaseCapTitle }}
                    </n-tooltip>
                  </div>

                  <div
                    v-if="updates.selfUpdate?.release_notes.length"
                    class="self-update-notes"
                  >
                    <article
                      v-for="note in updates.selfUpdate.release_notes"
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
              </n-tab-pane>
            </n-tabs>
          </div>
        </n-modal>
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

.sidebar {
  display: flex;
  flex-direction: column;
  gap: 28px;
  min-height: 100vh;
  padding: 22px 16px;
  background: var(--color-sidebar);
  color: var(--color-sidebar-text);
}

.brand {
  display: flex;
  align-items: center;
  gap: 10px;
  min-height: 40px;
  padding: 0 10px;
  font-weight: 700;
}

.nav-list {
  display: grid;
  gap: 6px;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 10px;
  min-height: 42px;
  padding: 0 10px;
  border-radius: 7px;
  color: var(--color-sidebar-muted);
  transition:
    background-color var(--motion-base) var(--ease-out-quart),
    color var(--motion-base) var(--ease-out-quart),
    transform var(--motion-fast) var(--ease-out-quart);
}

.nav-item.router-link-active,
.nav-item.nav-item-active,
.nav-item:hover {
  background: var(--color-sidebar-hover);
  color: var(--color-sidebar-text);
  transform: translateX(2px);
}

.sidebar-footer {
  margin-top: auto;
  padding: 0 10px;
}

.version-tag {
  max-width: 100%;
  border-color: rgba(247, 251, 252, 0.18);
  background: rgba(247, 251, 252, 0.08);
  color: var(--color-sidebar-muted);
}

.version-link {
  display: inline-flex;
  max-width: 100%;
  color: inherit;
  font-weight: 700;
  line-height: 1.2;
  overflow-wrap: anywhere;
}

.version-link:hover,
.version-link:focus-visible {
  color: var(--color-sidebar-text);
  text-decoration: underline;
}

.main-panel {
  min-width: 0;
  padding: 24px;
}

.topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 22px;
}

.topbar h1 {
  margin: 0;
  color: var(--color-ink);
  font-size: 1.35rem;
  line-height: 1.2;
}

.self-update-banner,
.self-update-message {
  margin-bottom: 16px;
}

.self-update-banner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  padding: 12px 14px;
  border: 1px solid color-mix(in srgb, var(--color-operational-teal) 34%, var(--color-border));
  border-radius: 8px;
  background: color-mix(in srgb, var(--color-operational-teal) 8%, var(--color-surface));
  color: var(--color-ink);
}

.self-update-banner-main,
.self-update-banner-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}

.self-update-banner-main>svg {
  flex: 0 0 auto;
  color: var(--color-operational-teal);
}

.self-update-banner-main div {
  display: grid;
  gap: 2px;
  min-width: 0;
}

.self-update-banner-main span,
.self-update-disabled {
  color: var(--color-muted-text);
  font-size: 0.86rem;
  overflow-wrap: anywhere;
}

.self-update-disabled {
  max-width: 42ch;
}

.self-update-modal {
  display: grid;
  gap: 14px;
}

.self-update-facts {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}

.self-update-facts div {
  display: grid;
  gap: 4px;
  min-width: 0;
  padding: 10px;
  border: 1px solid var(--color-border-subtle);
  border-radius: 7px;
  background: var(--color-panel-tint);
}

.self-update-facts span,
.self-update-note-title span,
.self-update-empty-notes,
.self-update-note small {
  color: var(--color-muted-text);
  font-size: 0.84rem;
}

.self-update-facts code,
.self-update-note p {
  overflow-wrap: anywhere;
}

.self-update-plan {
  display: grid;
  gap: 10px;
}

.self-update-tag-updates {
  display: grid;
  gap: 8px;
}

.self-update-tag-updates div {
  display: grid;
  gap: 4px;
  padding: 10px;
  border: 1px solid var(--color-border-subtle);
  border-radius: 7px;
  background: var(--color-surface);
}

.self-update-tag-updates span {
  color: var(--color-muted-text);
  font-size: 0.84rem;
  overflow-wrap: anywhere;
}

.self-update-tag-updates code {
  overflow-wrap: anywhere;
}

.self-update-notes-heading,
.self-update-note-title,
.self-update-github-link,
.self-update-cap {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.self-update-notes-heading {
  justify-content: space-between;
}

.self-update-cap {
  border: 0;
  padding: 0;
  color: var(--color-muted-text);
  background: transparent;
  font: inherit;
  font-size: 0.84rem;
  cursor: help;
}

.self-update-notes {
  display: grid;
  gap: 10px;
  max-height: min(44vh, 420px);
  overflow: auto;
}

.self-update-note {
  display: grid;
  gap: 8px;
  padding: 10px;
  border: 1px solid var(--color-border-subtle);
  border-radius: 7px;
  background: var(--color-surface);
}

.self-update-note-title {
  justify-content: space-between;
  gap: 10px;
}

.self-update-note-title a {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  color: var(--color-action-blue);
  font-weight: 700;
}

.self-update-note p,
.self-update-empty-notes {
  margin: 0;
  white-space: pre-wrap;
}

@media (max-width: 920px) {
  .app-shell {
    grid-template-columns: minmax(0, 1fr);
  }

  .sidebar {
    position: sticky;
    top: 0;
    z-index: 10;
    min-height: auto;
    flex-direction: row;
    align-items: center;
    gap: 12px;
    width: 100%;
    max-width: 100%;
    min-width: 0;
    padding: 10px 12px;
    overflow: hidden;
  }

  .brand span,
  .sidebar-footer {
    display: none;
  }

  .brand {
    min-width: 44px;
    min-height: 44px;
  }

  .nav-list {
    flex: 1 1 auto;
    grid-auto-flow: column;
    min-width: 0;
    max-width: 100%;
    overflow-x: auto;
  }

  .nav-item {
    flex: 0 0 auto;
    min-height: 44px;
    white-space: nowrap;
  }

  .nav-item span {
    display: none;
  }

  .main-panel {
    padding: 16px;
  }

  .topbar {
    align-items: flex-start;
  }

  .self-update-banner {
    align-items: flex-start;
    flex-direction: column;
  }

  .self-update-banner-actions {
    width: 100%;
  }
}

@media (max-width: 560px) {
  .topbar {
    display: grid;
  }

  .topbar-actions :deep(.n-button),
  :deep(.inline-actions .n-button) {
    min-width: 44px;
    min-height: 44px;
  }

  .topbar-actions :deep(.n-button--circle),
  :deep(.inline-actions .n-button--circle) {
    min-width: 44px;
  }

  .self-update-banner-actions,
  .self-update-facts,
  .self-update-note-title {
    display: grid;
    grid-template-columns: 1fr;
  }
}
</style>
