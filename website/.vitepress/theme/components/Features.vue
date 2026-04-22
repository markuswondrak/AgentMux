<script setup lang="ts">
import { providerCommaList } from '../providers'

interface Feature {
  variant: 'wide' | 'narrow' | 'dark' | 'split'
  icon: string
  title: string
  body: string
  chips: string[]
}

const features: Feature[] = [
  {
    variant: 'wide',
    icon: '∗',
    title: 'Phase state machine',
    body: 'A deterministic state machine moves work through product_management → architecting → planning → designing → implementing → reviewing → completing. Every transition is driven by structured events, never by artifact sniffing.',
    chips: ['STATE_MACHINE', 'EVENT_BUS', 'PHASE_HANDLERS'],
  },
  {
    variant: 'narrow',
    icon: '✓',
    title: 'Structured handoffs',
    body: 'Each phase hands off through MCP-validated contracts — no freeform drift between architect, planner, coder, and reviewer.',
    chips: ['MCP_HANDOFF'],
  },
  {
    variant: 'dark',
    icon: '>_',
    title: 'CLI first',
    body: `No bespoke runtime, no proprietary harness. AgentMux drives the existing CLIs you already authenticated against — ${providerCommaList} — through tmux key injection, reusing your subscriptions.`,
    chips: ['NO_API_COSTS', 'TMUX_NATIVE'],
  },
  {
    variant: 'split',
    icon: '◆',
    title: 'Bounded review loop',
    body: 'The reviewing phase fans out into logic, quality, and expert reviewers. A single pass/fail verdict either promotes the work to completing or sends it back through fixing — bounded by an explicit loop cap.',
    chips: ['REVIEW_LOOP', 'VERDICT_PASS_FAIL'],
  },
]
</script>

<template>
  <section class="am-section am-section--low features">
    <div class="am-container">
      <div class="am-eyebrow">Capabilities</div>
      <h2 class="am-section-title">Architectural Logic</h2>

      <div class="features__grid">
        <article
          v-for="f in features"
          :key="f.title"
          class="feature"
          :class="`feature--${f.variant}`"
        >
          <div class="feature__icon">{{ f.icon }}</div>
          <h3 class="feature__title">{{ f.title }}</h3>
          <p class="feature__body">{{ f.body }}</p>
          <div class="feature__chips">
            <span v-for="chip in f.chips" :key="chip" class="am-chip">{{ chip }}</span>
          </div>
        </article>
      </div>
    </div>
  </section>
</template>

<style scoped>
.features__grid {
  display: grid;
  grid-template-columns: 2fr 1fr;
  grid-auto-rows: minmax(240px, auto);
  gap: 24px;
}

.feature {
  position: relative;
  display: flex;
  flex-direction: column;
  background: var(--am-surface-lowest);
  border-radius: var(--am-r-md);
  padding: 28px 22px 24px 28px;
  isolation: isolate;
  overflow: hidden;
}

.feature--wide   { grid-column: 1; }
.feature--narrow { grid-column: 2; }
.feature--dark   { grid-column: 1; background: var(--am-on-surface); color: var(--am-surface-lowest); }
.feature--split  { grid-column: 2; }

.feature--dark::before {
  content: '';
  position: absolute;
  inset: -1px;
  background: radial-gradient(circle at 30% 0%, rgba(9, 105, 218, 0.30) 0%, transparent 55%);
  z-index: 0;
}
.feature--dark > * { position: relative; z-index: 1; }

.feature__icon {
  font-family: var(--am-font-mono);
  font-size: 1.5rem;
  color: var(--am-primary);
  margin-bottom: 14px;
  line-height: 1;
}
.feature--dark .feature__icon { color: #5fa6ff; }

.feature__title {
  font-family: var(--am-font-sans);
  font-weight: 600;
  font-size: 1.25rem;
  letter-spacing: -0.018em;
  color: var(--am-on-surface);
  margin: 0 0 10px;
}
.feature--dark .feature__title { color: var(--am-surface-lowest); }

.feature__body {
  font-size: var(--am-body-md);
  line-height: 1.55;
  color: var(--am-on-surface-variant);
  margin: 0 0 18px;
  flex-grow: 1;
}
.feature--dark .feature__body { color: rgba(226, 232, 240, 0.78); }

.feature__chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: auto;
  padding-top: 12px;
}
.feature--dark .feature__chips .am-chip {
  background: rgba(255, 255, 255, 0.10);
  color: rgba(226, 232, 240, 0.86);
}

@media (max-width: 900px) {
  .features__grid {
    grid-template-columns: 1fr;
    grid-auto-rows: auto;
  }
  .feature--wide,
  .feature--narrow,
  .feature--dark,
  .feature--split { grid-column: 1; }
}
</style>
