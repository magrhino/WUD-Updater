<script setup lang="ts">
import { scrollToElementId } from "./settingsDom";
import { SETTINGS_NAV_GROUPS } from "./settingsDisplay";
</script>

<template>
  <nav
    class="settings-map"
    aria-label="Settings sections"
    data-test="settings-jump-nav"
  >
    <div class="settings-map-heading">
      <strong>Settings map</strong>
    </div>
    <div class="settings-map-groups">
      <section
        v-for="group in SETTINGS_NAV_GROUPS"
        :key="group.id"
        class="settings-map-group"
        :aria-labelledby="`settings-map-${group.id}`"
        :data-test="`settings-nav-group-${group.id}`"
      >
        <div class="settings-map-group-heading">
          <h2 :id="`settings-map-${group.id}`">{{ group.label }}</h2>
        </div>
        <ul class="settings-map-group-list">
          <li
            v-for="link in group.links"
            :key="link.id"
            class="settings-map-group-list-item"
            :data-test="`settings-nav-item-${link.id}`"
          >
            <button
              type="button"
              class="settings-map-link"
              @click="scrollToElementId(link.id)"
            >
              <span>{{ link.label }}</span>
            </button>
          </li>
        </ul>
      </section>
    </div>
  </nav>
</template>

<style scoped>
.settings-map {
  position: sticky;
  top: 16px;
  display: grid;
  gap: 14px;
  min-width: 0;
  max-height: calc(100vh - 32px);
  padding: 12px;
  overflow: auto;
  border: 1px solid var(--color-border);
  border-radius: 8px;
  background: var(--color-surface);
  box-shadow: var(--shadow-panel-lift);
}

.settings-map-heading,
.settings-map-group-heading {
  display: grid;
  min-width: 0;
}

.settings-map-heading strong,
.settings-map-group-heading h2 {
  margin: 0;
  color: var(--color-ink);
  font-size: 0.92rem;
  line-height: 1.25;
}

.settings-map-groups {
  display: grid;
  gap: 12px;
}

.settings-map-group {
  display: grid;
  gap: 6px;
  min-width: 0;
}

.settings-map-group-list {
  display: grid;
  gap: 6px;
  min-width: 0;
  margin: 0;
  padding: 0;
  list-style: none;
}

.settings-map-group-list-item {
  display: grid;
  min-width: 0;
}

.settings-map-link {
  width: 100%;
  min-height: 42px;
  padding: 0 8px;
  border: 1px solid transparent;
  border-radius: 7px;
  background: transparent;
  color: var(--color-text-secondary);
  font: inherit;
  text-align: left;
  cursor: pointer;
  transition:
    border-color 180ms ease-out,
    color 180ms ease-out,
    background-color 180ms ease-out;
}

.settings-map-link span {
  color: var(--color-ink);
  font-size: 0.86rem;
  font-weight: 700;
  line-height: 1.25;
}

.settings-map-link:hover,
.settings-map-link:focus-visible {
  border-color: var(--color-border-hover);
  background: var(--color-panel-tint);
  color: var(--color-ink);
}

.settings-map-link:focus-visible {
  outline: 2px solid var(--color-border-hover);
  outline-offset: 2px;
}

@media (--wud-app-shell) {
  .settings-map {
    position: static;
    max-height: none;
  }

  .settings-map-groups {
    display: flex;
    align-items: start;
    max-width: 100%;
    overflow-x: auto;
    padding-bottom: 2px;
  }

  .settings-map-group {
    flex: 0 0 min(190px, 78vw);
  }
}

@media (--wud-compact) {
  .settings-map-link {
    min-height: var(--size-touch-target);
  }
}
</style>
