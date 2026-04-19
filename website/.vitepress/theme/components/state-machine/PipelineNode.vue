<script setup lang="ts">
import { Handle, Position } from '@vue-flow/core'

defineProps<{
  data: {
    label: string
    variant?: 'standard' | 'optional'
    status?: 'success' | 'error' | 'verdict-pass' | 'verdict-fail'
    showLeftHandle?: boolean
  }
}>()
</script>

<template>
  <div class="sm-pill" :class="[
    data.status ? `sm-pill--${data.status}` : `sm-pill--${data.variant || 'standard'}`,
  ]">
    <Handle v-if="data.showLeftHandle !== false" id="in-left"   class="sm-pill__handle" type="target" :position="Position.Left" />
    <Handle id="in-top"    class="sm-pill__handle" type="target" :position="Position.Top" />
    <Handle id="in-bottom" class="sm-pill__handle" type="target" :position="Position.Bottom" />
    <Handle id="in-right"  class="sm-pill__handle" type="target" :position="Position.Right" />

    <span class="sm-pill__dot" />
    <span class="sm-pill__text">{{ data.label }}</span>

    <Handle id="out-right"  class="sm-pill__handle" type="source" :position="Position.Right" />
    <Handle id="out-bottom" class="sm-pill__handle" type="source" :position="Position.Bottom" />
    <Handle id="out-left"   class="sm-pill__handle" type="source" :position="Position.Left" />
  </div>
</template>

<style scoped>
.sm-pill {
  display: flex;
  align-items: center;
  gap: 8px;
  font-family: var(--am-font-mono, monospace);
  font-size: 13px;
  font-weight: 600;
  letter-spacing: 0.02em;
  padding: 10px 16px;
  border-radius: 10px; /* Etwas runder für einen modernen Look */
  white-space: nowrap;
  position: relative;
  transition: all 0.2s ease;
}

/* Standard */
.sm-pill--standard {
  background: var(--am-surface-lowest, #ffffff);
  color: var(--am-on-surface, #1e293b);
  border: 1px solid var(--am-outline-15, #cbd5e1);
  /* Neuer, weicherer Schatten, damit sie "schweben" */
  box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05), 0 2px 4px -2px rgba(0, 0, 0, 0.03);
}
.sm-pill--standard .sm-pill__dot {
  background: #64748b;
}

/* Optional: ghost / dashed */
.sm-pill--optional {
  background: rgba(255, 255, 255, 0.7); /* Leicht durchlässig */
  backdrop-filter: blur(4px);
  color: var(--am-on-surface-variant, #64748b);
  border: 1.5px dashed var(--am-outline-15, #94a3b8);
}
.sm-pill--optional .sm-pill__dot {
  background: #94a3b8;
}

/* Success */
.sm-pill--success {
  background: #f0fdf4;
  color: #15803d;
  border: 1px solid #4ade80;
  box-shadow: 0 4px 6px -1px rgba(34, 197, 94, 0.1);
}
.sm-pill--success .sm-pill__dot {
  background: #22c55e;
}

/* Error */
.sm-pill--error {
  background: #fef2f2;
  color: #b91c1c;
  border: 1px solid #f87171;
  box-shadow: 0 4px 6px -1px rgba(239, 68, 68, 0.1);
}
.sm-pill--error .sm-pill__dot {
  background: #ef4444;
}

/* Verdict badges (PASS / FAIL) — compact, no dot, bold uppercase */
.sm-pill--verdict-pass {
  background: #f0fdf4;
  color: #16a34a;
  border: 1.5px solid #4ade80;
  font-size: 9px;
  font-weight: 800;
  letter-spacing: 0.1em;
  padding: 2px 6px;
  border-radius: 6px;
}
.sm-pill--verdict-pass .sm-pill__dot {
  display: none;
}

.sm-pill--verdict-fail {
  background: #fef2f2;
  color: #dc2626;
  border: 1.5px solid #f87171;
  font-size: 9px;
  font-weight: 800;
  letter-spacing: 0.1em;
  padding: 2px 6px;
  border-radius: 6px;
}
.sm-pill--verdict-fail .sm-pill__dot {
  display: none;
}

.sm-pill__dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  flex-shrink: 0;
}

.sm-pill__handle {
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
