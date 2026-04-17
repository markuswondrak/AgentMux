<script setup lang="ts">
import { computed } from 'vue'
import roadmapData from '../../../data/roadmap.yaml'

type Status = 'deployed' | 'in_progress' | 'ambitious'

interface Item {
  title: string
  status: Status
}

interface Column {
  id: string
  title: string
  items: Item[]
}

const data = roadmapData as { columns: Column[] }

type StationState = 'shipped' | 'active' | 'future'

const stations = computed(() => {
  return data.columns.map((col, idx) => {
    const deployed = col.items.filter((i) => i.status === 'deployed').length
    const inProgress = col.items.filter((i) => i.status === 'in_progress').length
    const active = col.items.find((i) => i.status === 'in_progress')
    let state: StationState = 'future'
    if (inProgress > 0) state = 'active'
    else if (deployed === col.items.length && deployed > 0) state = 'shipped'
    return {
      index: idx,
      id: col.id,
      title: col.title,
      total: col.items.length,
      deployed,
      inProgress,
      state,
      activeTitle: active?.title,
      pips: col.items.map((i) => i.status),
    }
  })
})

function segmentStyle(fromState: StationState): 'solid' | 'dashed' | 'dotted' {
  if (fromState === 'shipped') return 'solid'
  if (fromState === 'active') return 'dashed'
  return 'dotted'
}
</script>

<template>
  <section class="am-section am-section--surface rh">
    <div class="am-container rh__grid">
      <div class="rh__copy">
        <div class="am-eyebrow">Our roadmap</div>
        <h1 class="rh__headline">
          Engineering<br />
          the <em>future</em>.
        </h1>
        <p class="rh__tagline">
          AgentMux's technical trajectory — from the deterministic tmux runtime that exists today
          to declarative pipelines, IDE integration, and cloud handoff. See what is shipped,
          in flight, and on the horizon.
        </p>
      </div>

      <aside class="rh__spine" aria-label="Roadmap trajectory">
        <div class="rh__spine-eyebrow">▸ Trajectory</div>

        <ol class="rh__stations">
          <li
            v-for="(s, i) in stations"
            :key="s.id"
            class="rh__station"
            :class="`rh__station--${s.state}`"
          >
            <div class="rh__marker">
              <span class="rh__dot" />
              <span
                v-if="i < stations.length - 1"
                class="rh__line"
                :class="`rh__line--${segmentStyle(s.state)}`"
              />
            </div>

            <div class="rh__body">
              <div class="rh__label">{{ s.title }}</div>
              <div class="rh__count">
                {{ s.total }} item{{ s.total === 1 ? '' : 's' }}
                <template v-if="s.inProgress > 0">
                  · {{ s.inProgress }} in flight
                </template>
                <template v-else-if="s.state === 'shipped'">
                  · all deployed
                </template>
                <template v-else>
                  · ambitious
                </template>
              </div>
              <div class="rh__pips">
                <span
                  v-for="(p, j) in s.pips"
                  :key="j"
                  class="rh__pip"
                  :class="`rh__pip--${p}`"
                />
              </div>
              <div v-if="s.activeTitle" class="rh__now">
                ▸ now: {{ s.activeTitle }}
              </div>
            </div>
          </li>
        </ol>
      </aside>
    </div>
  </section>
</template>

<style scoped>
.rh {
  padding-top: clamp(80px, 12vw, 130px);
  padding-bottom: clamp(64px, 10vw, 110px);
}

.rh__grid {
  display: grid;
  grid-template-columns: minmax(0, 1.05fr) minmax(0, 1fr);
  gap: clamp(36px, 6vw, 72px);
  align-items: center;
}

.rh__headline {
  font-family: var(--am-font-sans);
  font-weight: 700;
  font-size: var(--am-display-xl);
  line-height: 1;
  letter-spacing: -0.028em;
  color: var(--am-on-surface);
  margin: 0 0 24px;
  text-transform: uppercase;
}
.rh__headline em {
  font-style: italic;
  font-weight: 700;
  text-transform: none;
  background: var(--am-grad-text);
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
}
.rh__tagline {
  font-size: var(--am-body-lg);
  color: var(--am-on-surface-variant);
  line-height: 1.55;
  max-width: 56ch;
  margin: 0;
}

/* --- Trajectory spine --- */
.rh__spine {
  background: var(--am-surface-lowest);
  border-radius: var(--am-r-md);
  padding: 28px 24px 32px 32px;
  min-width: 0;
}

.rh__spine-eyebrow {
  font-family: var(--am-font-mono);
  font-size: var(--am-label-sm);
  font-weight: 500;
  text-transform: uppercase;
  letter-spacing: 0.14em;
  color: var(--am-on-surface-3);
  margin-bottom: 28px;
}

.rh__stations {
  list-style: none;
  margin: 0;
  padding: 0;
}

.rh__station {
  display: grid;
  grid-template-columns: 28px 1fr;
  gap: 18px;
  padding-bottom: 28px;
}
.rh__station:last-child { padding-bottom: 0; }

.rh__marker {
  position: relative;
  display: flex;
  justify-content: center;
}

.rh__dot {
  width: 14px;
  height: 14px;
  border-radius: 50%;
  background: var(--am-surface-container);
  margin-top: 4px;
  z-index: 1;
  flex-shrink: 0;
}
.rh__station--shipped .rh__dot {
  background: var(--am-primary);
}
.rh__station--active .rh__dot {
  background: var(--am-surface-lowest);
  box-shadow: inset 0 0 0 3px var(--am-primary);
}
.rh__station--future .rh__dot {
  background: var(--am-surface-lowest);
  box-shadow: inset 0 0 0 1.5px var(--am-outline-15);
}

.rh__line {
  position: absolute;
  top: 22px;
  bottom: -28px;
  left: 50%;
  transform: translateX(-50%);
  width: 0;
}
.rh__line--solid  { border-left: 2px solid var(--am-primary); }
.rh__line--dashed { border-left: 2px dashed var(--am-primary); opacity: 0.55; }
.rh__line--dotted { border-left: 2px dotted var(--am-on-surface-3); opacity: 0.55; }

.rh__body { min-width: 0; }

.rh__label {
  font-family: var(--am-font-mono);
  font-size: var(--am-label-md);
  font-weight: 500;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  color: var(--am-on-surface);
  margin-bottom: 4px;
}
.rh__station--future .rh__label { color: var(--am-on-surface-3); }

.rh__count {
  font-family: var(--am-font-mono);
  font-size: var(--am-label-sm);
  color: var(--am-on-surface-variant);
  margin-bottom: 10px;
  letter-spacing: 0.02em;
}

.rh__pips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.rh__pip {
  width: 10px;
  height: 10px;
  border-radius: 2px;
}
.rh__pip--deployed    { background: var(--am-secondary); }
.rh__pip--in_progress { background: var(--am-primary); }
.rh__pip--ambitious   { background: var(--am-surface-container); }

.rh__now {
  margin-top: 12px;
  font-family: var(--am-font-mono);
  font-size: var(--am-label-sm);
  color: var(--am-primary);
  letter-spacing: 0.02em;
}

@media (max-width: 1024px) {
  .rh__grid { grid-template-columns: 1fr; gap: 48px; }
  .rh__spine { max-width: 520px; }
}
</style>
