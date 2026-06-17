<script setup lang="ts">
import { type Component } from "vue";
import { RouterLink, useRoute } from "vue-router";
import {
  Activity,
  BellOff,
  Clock3,
  LayoutDashboard,
  ListChecks,
  Repeat2,
  Settings2,
  SlidersHorizontal,
  Stethoscope,
  Tags,
} from "@lucide/vue";
import { NTag } from "naive-ui";

defineProps<{
  versionLabel: string;
  versionHref: string;
  versionTitle: string;
}>();

const route = useRoute();

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
</script>

<template>
  <aside class="sidebar">
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
        v-if="versionLabel"
        class="version-tag"
        size="small"
      >
        <a
          class="version-link"
          :href="versionHref"
          target="_blank"
          rel="noopener noreferrer"
          :title="versionTitle"
          :aria-label="versionTitle"
        >
          {{ versionLabel }}
        </a>
      </n-tag>
    </div>
  </aside>
</template>

<style scoped>
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

@media (max-width: 920px) {
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
}
</style>
