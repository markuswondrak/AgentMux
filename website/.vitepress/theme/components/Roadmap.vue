<script setup lang="ts">
import { computed, ref } from 'vue'
import roadmapData from '../../../data/roadmap.yaml'

type Status = 'deployed' | 'in_progress' | 'ambitious'

interface Item {
  title: string
  description: string
  status: Status
  category?: string
  issue?: number
}

interface Column {
  id: string
  title: string
  items: Item[]
}

interface Roadmap {
  columns: Column[]
}

const data = roadmapData as Roadmap

const filters: { id: 'all' | Status; label: string }[] = [
  { id: 'all',         label: 'ALL DEVELOPMENTS' },
  { id: 'ambitious',   label: 'AMBITIOUS' },
  { id: 'in_progress', label: 'IN PROGRESS' },
  { id: 'deployed',    label: 'DEPLOYED' },
]

const active = ref<'all' | Status>('all')

const filteredColumns = computed(() => {
  if (active.value === 'all') return data.columns
  return data.columns.map((col) => ({
    ...col,
    items: col.items.filter((i) => i.status === active.value),
  }))
})

const statusLabel: Record<Status, string> = {
  deployed:    'DEPLOYED',
  in_progress: 'IN PROGRESS',
  ambitious:   'AMBITIOUS',
}
</script>

<template>
  <section class="am-section am-section--low rb">
    <div class="am-container">
      <div class="rb__filter-row">
        <button
          v-for="f in filters"
          :key="f.id"
          type="button"
          class="rb__filter"
          :class="{ 'rb__filter--active': active === f.id }"
          @click="active = f.id"
        >
          {{ f.label }}
        </button>
      </div>

      <div class="rb__columns">
        <div v-for="col in filteredColumns" :key="col.id" class="rb__col">
          <div class="rb__col-header">▸ {{ col.title }}</div>

          <article
            v-for="item in col.items"
            :key="item.title"
            class="card"
          >
            <div class="card__top">
              <span class="am-chip" :class="`am-chip--${item.status === 'in_progress' ? 'progress' : item.status}`">
                <span v-if="item.status !== 'ambitious'" class="am-led" />
                {{ statusLabel[item.status] }}
              </span>
            </div>
            <h3 class="card__title">{{ item.title }}</h3>
            <p class="card__body">{{ item.description }}</p>
            <div v-if="item.category || item.issue" class="card__meta">
              <span v-if="item.category" class="am-chip">{{ item.category }}</span>
              <a
                v-if="item.issue"
                class="card__issue"
                :href="`https://github.com/markuswondrak/AgentMux/issues/${item.issue}`"
                target="_blank"
                rel="noopener"
              >#{{ item.issue }}</a>
            </div>
          </article>

          <div v-if="col.items.length === 0" class="rb__empty">
            no items in this filter
          </div>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.rb__filter-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 40px;
  padding-bottom: 20px;
}

.rb__filter {
  font-family: var(--am-font-mono);
  font-size: var(--am-label-sm);
  font-weight: 500;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  padding: 9px 14px;
  background: var(--am-surface-lowest);
  color: var(--am-on-surface-variant);
  border: none;
  border-radius: var(--am-r-md);
  cursor: pointer;
  transition: background 160ms ease, color 160ms ease, transform 100ms ease;
}
.rb__filter:hover { background: var(--am-surface-container); color: var(--am-on-surface); }

.rb__filter--active {
  background: var(--am-grad-primary);
  color: var(--am-on-primary);
  box-shadow: 0 4px 14px rgba(0, 81, 174, 0.2);
}
.rb__filter--active:hover { color: var(--am-on-primary); background: var(--am-grad-primary); }

.rb__columns {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 28px;
}

.rb__col {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.rb__col-header {
  font-family: var(--am-font-mono);
  font-size: var(--am-label-md);
  font-weight: 500;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  color: var(--am-on-surface-3);
  margin-bottom: 4px;
}

.card {
  background: var(--am-surface-lowest);
  border-radius: var(--am-r-md);
  padding: 20px 18px 18px 22px;
  display: flex;
  flex-direction: column;
}

.card__top {
  margin-bottom: 12px;
}

.card__title {
  font-family: var(--am-font-sans);
  font-weight: 600;
  font-size: 1.0625rem;
  letter-spacing: -0.012em;
  color: var(--am-on-surface);
  margin: 0 0 8px;
}

.card__body {
  font-size: var(--am-body-sm);
  color: var(--am-on-surface-variant);
  line-height: 1.55;
  margin: 0 0 14px;
}

.card__meta {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: auto;
  padding-top: 6px;
}

.card__issue {
  font-family: var(--am-font-mono);
  font-size: var(--am-label-sm);
  color: var(--am-primary);
  text-decoration: none;
  padding: 4px 8px;
  border-radius: var(--am-r-sm);
  background: var(--am-primary-soft-08);
}
.card__issue:hover { background: var(--am-primary-soft-12); }

.rb__empty {
  font-family: var(--am-font-mono);
  font-size: var(--am-label-sm);
  color: var(--am-on-surface-3);
  padding: 14px 18px;
  background: var(--am-surface-lowest);
  border-radius: var(--am-r-md);
  text-transform: uppercase;
  letter-spacing: 0.06em;
}

@media (max-width: 1024px) {
  .rb__columns { grid-template-columns: 1fr; }
}
</style>
