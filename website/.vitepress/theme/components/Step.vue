<script setup lang="ts">
defineProps<{
  n: string | number
  title?: string
}>()
</script>

<template>
  <div class="doc-step">
    <div class="doc-step__num">{{ n }}</div>
    <div class="doc-step__content">
      <h3 v-if="title" class="doc-step__title">{{ title }}</h3>
      <slot />
    </div>
  </div>
</template>

<style scoped>
.doc-step {
  display: grid;
  grid-template-columns: 56px 1fr;
  gap: 22px;
  align-items: start;
  margin: 32px 0;
}

.doc-step__num {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 44px;
  height: 44px;
  border-radius: 50%;
  background: var(--am-primary-soft-12);
  color: var(--am-primary);
  font-family: var(--am-font-mono);
  font-weight: 500;
  font-size: 0.875rem;
  letter-spacing: 0.04em;
}

.doc-step__title {
  font-family: var(--am-font-sans);
  font-weight: 600;
  font-size: 1.25rem;
  letter-spacing: -0.018em;
  color: var(--am-on-surface);
  margin: 6px 0 8px;
}

.doc-step__content :slotted(p) {
  margin: 0 0 12px;
  color: var(--am-on-surface-variant);
}

.doc-step__content :slotted(div[class*='language-']) {
  margin-top: 10px;
}

@media (max-width: 640px) {
  .doc-step { grid-template-columns: 40px 1fr; gap: 14px; }
  .doc-step__num { width: 36px; height: 36px; font-size: 0.8125rem; }
}
</style>
