<script setup lang="ts">
import { PROVIDERS as providers } from '../providers'
</script>

<template>
  <section class="am-section am-section--low providers">
    <div class="am-container">
      <div class="am-eyebrow">Supported Providers</div>
      <h2 class="am-section-title">Mix and match per role.</h2>
      <p class="am-section-tagline">
        Run the architect on Claude Max, the coder on Codex, the reviewer on Gemini —
        each role independently configurable in <code>.agentmux/config.yaml</code>.
      </p>

      <div class="providers__row">
        <div v-for="p in providers" :key="p.id" class="providers__chip">
          <span class="providers__dot" />
          {{ p.label }}
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.providers__row {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.providers__chip {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  background: var(--am-surface-lowest);
  color: var(--am-on-surface);
  font-family: var(--am-font-mono);
  font-size: 0.8125rem;
  font-weight: 500;
  padding: 10px 14px 10px 12px;
  border-radius: var(--am-r-md);
}

.providers__dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--am-secondary);
  box-shadow: 0 0 4px var(--am-secondary);
}

code {
  font-family: var(--am-font-mono);
  font-size: 0.85em;
  background: var(--am-surface-container);
  color: var(--am-on-surface);
  padding: 2px 6px;
  border-radius: var(--am-r-sm);
}
</style>
