<script setup lang="ts">
withDefaults(defineProps<{
  eyebrow?: string
  title?: string
  body?: string
  primaryLabel?: string
  primaryHref?: string
  secondaryLabel?: string
  secondaryHref?: string
}>(), {
  eyebrow: 'Open source',
  title: 'Run a deterministic pipeline today.',
  body: 'AgentMux is open source on GitHub. Install it with pipx, point it at a repo, and drive your existing CLI subscriptions through a structured multi-agent workflow.',
  primaryLabel: 'OPEN ON GITHUB',
  primaryHref: 'https://github.com/markuswondrak/AgentMux',
  secondaryLabel: 'GET STARTED',
  secondaryHref: '/AgentMux/docs/getting-started',
})
</script>

<template>
  <section class="am-section am-section--dark dark-cta">
    <div class="am-container dark-cta__grid">
      <div class="dark-cta__copy">
        <div class="dark-cta__eyebrow">▸ {{ eyebrow }}</div>
        <h2 class="dark-cta__title">{{ title }}</h2>
        <p class="dark-cta__body">{{ body }}</p>
      </div>
      <div class="dark-cta__actions">
        <a class="am-btn am-btn--green" :href="primaryHref" target="_blank" rel="noopener">
          {{ primaryLabel }}
        </a>
        <a class="am-btn am-btn--ghost-dark" :href="secondaryHref">
          {{ secondaryLabel }}
        </a>
      </div>
    </div>
  </section>
</template>

<style scoped>
.dark-cta {
  background: var(--am-dark);
  background-image: radial-gradient(circle at 85% 30%, rgba(9, 105, 218, 0.18) 0%, transparent 60%);
  color: var(--am-dark-text);
}

.dark-cta__grid {
  display: grid;
  grid-template-columns: minmax(0, 1.4fr) minmax(0, 1fr);
  gap: 36px;
  align-items: center;
}

.dark-cta__eyebrow {
  font-family: var(--am-font-mono);
  font-size: var(--am-label-sm);
  text-transform: uppercase;
  letter-spacing: 0.12em;
  color: var(--am-dark-text-muted);
  margin-bottom: 14px;
}

.dark-cta__title {
  font-family: var(--am-font-sans);
  font-weight: 700;
  font-size: var(--am-headline-lg);
  letter-spacing: -0.022em;
  color: #ffffff;
  margin: 0 0 12px;
  line-height: 1.05;
}

.dark-cta__body {
  font-size: var(--am-body-md);
  color: var(--am-dark-text-muted);
  margin: 0;
  line-height: 1.55;
  max-width: 56ch;
}

.dark-cta__actions {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
  justify-content: flex-end;
}

@media (max-width: 768px) {
  .dark-cta__grid {
    grid-template-columns: 1fr;
    gap: 28px;
  }
  .dark-cta__actions { justify-content: flex-start; }
}
</style>
