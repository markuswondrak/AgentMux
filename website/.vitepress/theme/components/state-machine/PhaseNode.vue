<script setup lang="ts">
import { Handle, Position } from '@vue-flow/core'

defineProps<{
  data: {
    step: string
    title: string
  }
}>()
</script>

<template>
  <div class="phase-node">
    <!-- Header: blue square badge + bold uppercase title, floats above the phase border -->
    <div class="phase-node__label">
      <span class="phase-node__number">{{ data.step }}</span>
      <span class="phase-node__name">{{ data.title }}</span>
    </div>
    <!-- Phase-level connection handles at fixed top: 87px — aligns with implementing/reviewing center -->
    <Handle id="phase-in"  class="phase-node__handle" type="target" :position="Position.Left"  style="top: 87px" />
    <Handle id="phase-out" class="phase-node__handle" type="source" :position="Position.Right" style="top: 87px" />
  </div>
</template>

<style scoped>
.phase-node {
  width: 100%;
  height: 100%;
  position: relative;
  border: 1.5px solid #cbd5e1;
  border-radius: 16px;
  background: rgba(248, 250, 252, 0.5);
  pointer-events: none;
  overflow: visible;
}

.phase-node__label {
  position: absolute;
  top: -30px;
  left: 0;
  display: inline-flex;
  align-items: center;
  gap: 10px;
  pointer-events: none;
}

.phase-node__number {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  border-radius: 6px;
  background: #2563eb;
  color: #ffffff;
  font-family: var(--am-font-mono, monospace);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0;
  flex-shrink: 0;
}

.phase-node__name {
  font-family: var(--am-font-mono, monospace);
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  color: #1e293b;
  white-space: nowrap;
}

.phase-node__handle {
  width: 1px !important;
  height: 1px !important;
  min-width: 1px !important;
  min-height: 1px !important;
  border: none !important;
  background: transparent !important;
  opacity: 0;
  pointer-events: none !important;
}
</style>
