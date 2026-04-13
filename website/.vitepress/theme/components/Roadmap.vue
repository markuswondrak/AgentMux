<template>
  <div class="roadmap-grid">
    <div v-for="col in data.columns" :key="col.id" class="roadmap-col">
      <div class="roadmap-col-title">{{ col.title }}</div>
      <div v-if="col.items.length === 0" class="roadmap-card">
        <span class="roadmap-card-desc" style="font-style: italic;">Coming soon</span>
      </div>
      <div v-for="item in col.items" :key="item.title" class="roadmap-card">
        <span class="roadmap-card-title">{{ item.title }}</span>
        <span class="roadmap-card-desc">{{ item.description }}</span>
        <a
          v-if="item.issue"
          class="roadmap-issue"
          :href="`https://github.com/markuswondrak/AgentMux/issues/${item.issue}`"
          target="_blank"
          rel="noopener"
        >#{{ item.issue }}</a>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import roadmapData from '../../../data/roadmap.yaml'

interface RoadmapItem {
  title: string
  description: string
  issue?: number
}

interface RoadmapColumn {
  id: string
  title: string
  items: RoadmapItem[]
}

interface RoadmapData {
  columns: RoadmapColumn[]
}

const data = roadmapData as RoadmapData
</script>
