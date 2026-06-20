<script setup lang="ts">
import wudupMarkUrl from "../../assets/brand/wudup-mark.svg";

withDefaults(
  defineProps<{
    size?: number;
  }>(),
  {
    size: 32,
  },
);
</script>

<template>
  <img
    class="app-brand-mark"
    :src="wudupMarkUrl"
    alt=""
    aria-hidden="true"
    :width="size"
    :height="size"
    decoding="async"
  >
</template>

<style scoped>
.app-brand-mark {
  display: block;
  flex: 0 0 auto;
}
</style>
