<script setup lang="ts">
defineProps<{
  title?: string
  cta?: string
  href?: string
  variant?: 'info' | 'tip' | 'warning'
}>()
</script>

<template>
  <aside class="doc-callout" :class="`doc-callout--${variant ?? 'info'}`">
    <div class="doc-callout__body">
      <div v-if="title" class="doc-callout__title">{{ title }}</div>
      <slot />
    </div>
    <a
      v-if="cta && href"
      class="am-btn am-btn--primary doc-callout__cta"
      :href="href"
      target="_blank"
      rel="noopener"
    >
      {{ cta }}
    </a>
  </aside>
</template>

<style scoped>
.doc-callout {
  background: var(--am-primary-soft-08);
  border-radius: var(--am-r-md);
  padding: 22px 24px 22px 26px;
  display: flex;
  flex-direction: column;
  gap: 14px;
  margin: 24px 0;
  position: relative;
}

.doc-callout--tip     { background: rgba(0, 110, 0, 0.06); }
.doc-callout--warning { background: rgba(178, 95, 0, 0.07); }

.doc-callout__title {
  font-family: var(--am-font-mono);
  font-size: var(--am-label-md);
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--am-on-surface);
  font-weight: 600;
  margin-bottom: 2px;
}

.doc-callout__body :slotted(p) {
  margin: 0;
  color: var(--am-on-surface-variant);
  font-size: var(--am-body-sm);
  line-height: 1.55;
}

.doc-callout__cta {
  align-self: flex-start;
}
</style>
