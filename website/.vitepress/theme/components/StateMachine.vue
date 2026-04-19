<script setup lang="ts">
import { markRaw, onBeforeUnmount } from 'vue'
import type { Edge, Node } from '@vue-flow/core'
import { VueFlow, MarkerType } from '@vue-flow/core'

import '@vue-flow/core/dist/style.css'
import PipelineNode from './state-machine/PipelineNode.vue'
import PhaseNode from './state-machine/PhaseNode.vue'

const nodeTypes = {
  pipeline: markRaw(PipelineNode),
  phase: markRaw(PhaseNode),
}

// All phases at y=30. Phase handles hardcoded at top: 87px — aligns with
// implementing/reviewing centers (node y=68, height≈38, center=87).
// The horizontal cross-phase line passes between the top/bottom nodes in
// phases 1 & 2 (product_management center≈49, architecting center≈109).
const nodes: Node[] = [
  // --- Phase containers (~40px gap); larger base size reads better on 4K ---
  { id: 'phase-1', type: 'phase', position: { x: 0,   y: 30 }, style: { width: '300px', height: '160px' }, data: { step: '01', title: 'Definition' },    class: 'sm__phase-container' },
  { id: 'phase-2', type: 'phase', position: { x: 340, y: 30 }, style: { width: '300px', height: '160px' }, data: { step: '02', title: 'Blueprint' },     class: 'sm__phase-container' },
  { id: 'phase-3', type: 'phase', position: { x: 680, y: 30 }, style: { width: '300px', height: '185px' }, data: { step: '03', title: 'Execution' },     class: 'sm__phase-container' },
  { id: 'phase-4', type: 'phase', position: { x: 1020, y: 30 }, style: { width: '640px', height: '220px' }, data: { step: '04', title: 'Quality Gate' },  class: 'sm__phase-container' },

  // --- DEFINITION: product_management (top) → architecting (bottom) ---
  { id: 'product_management', parentNode: 'phase-1', type: 'pipeline', position: { x: 20, y: 30 }, style: { width: '260px' }, data: { label: 'product_management', variant: 'optional', showLeftHandle: false } },
  { id: 'architecting',       parentNode: 'phase-1', type: 'pipeline', position: { x: 20, y: 90 }, style: { width: '260px' }, data: { label: 'architecting', variant: 'standard' } },

  // --- BLUEPRINT: planning (top) → designing (bottom) ---
  { id: 'planning',  parentNode: 'phase-2', type: 'pipeline', position: { x: 20, y: 30 }, style: { width: '260px' }, data: { label: 'planning',  variant: 'standard' } },
  { id: 'designing', parentNode: 'phase-2', type: 'pipeline', position: { x: 20, y: 90 }, style: { width: '260px' }, data: { label: 'designing', variant: 'optional' } },

  // --- EXECUTION: implementing centered (center = 68+19 = 87px = phase handle height) ---
  { id: 'implementing', parentNode: 'phase-3', type: 'pipeline', position: { x: 20, y: 68 }, style: { width: '260px' }, data: { label: 'implementing', variant: 'standard' } },

  // --- QUALITY GATE ---
  // reviewing und completing auf exakt gleicher Y-Höhe
  { id: 'reviewing',  parentNode: 'phase-4', type: 'pipeline', position: { x: 20,  y: 30 }, style: { width: '240px' }, data: { label: 'reviewing',  variant: 'standard' } },
  { id: 'completing', parentNode: 'phase-4', type: 'pipeline', position: { x: 375, y: 30 }, style: { width: '240px' }, data: { label: 'completing', status: 'success' } },
  // pass-badge liegt auf der direkten X-Achse dazwischen
  { id: 'pass-badge', parentNode: 'phase-4', type: 'pipeline', position: { x: 295, y: 39 }, data: { label: 'PASS', status: 'verdict-pass' } },
  // fixing liegt exakt zentriert unter reviewing
  { id: 'fixing',     parentNode: 'phase-4', type: 'pipeline', position: { x: 20, y: 150 }, style: { width: '240px' }, data: { label: 'fixing', status: 'error' } },
  // fail-badge liegt auf der Y-Achse zwischen reviewing und fixing
  { id: 'fail-badge', parentNode: 'phase-4', type: 'pipeline', position: { x: 120, y: 100 }, data: { label: 'FAIL', status: 'verdict-fail' } },
]

const arrow = (color: string) => ({ type: MarkerType.ArrowClosed, color, width: 14, height: 14 })
const withinStyle  = { stroke: '#94a3b8', strokeWidth: 1.5 }
const dashedStyle  = { stroke: '#94a3b8', strokeWidth: 1.5, strokeDasharray: '5 4' }
const standardStyle = { stroke: '#94a3b8', strokeWidth: 2 }
const passStyle    = { stroke: '#22c55e', strokeWidth: 2 }
const failStyle    = { stroke: '#ef4444', strokeWidth: 2 }
const loopStyle    = { stroke: '#ef4444', strokeWidth: 2, strokeDasharray: '5 4' }

const edges: Edge[] = [
  // --- Within DEFINITION: product_management → architecting (vertical) ---
  {
    id: 'e-pm-arch',
    source: 'product_management', target: 'architecting',
    sourceHandle: 'out-bottom', targetHandle: 'in-top',
    type: 'smoothstep', style: withinStyle, markerEnd: arrow('#94a3b8'),
  },

  // --- Within BLUEPRINT: planning → designing (vertical, dashed = optional step) ---
  {
    id: 'e-plan-des',
    source: 'planning', target: 'designing',
    sourceHandle: 'out-bottom', targetHandle: 'in-top',
    type: 'smoothstep', style: dashedStyle, markerEnd: arrow('#94a3b8'),
  },

  // --- Cross-phase horizontal connections via phase-level handles ---
  // All three are perfectly horizontal because phase handles are hardcoded at top: 87px
  // and all phase containers share y=30.
  {
    id: 'e-phase-1-2',
    source: 'phase-1', target: 'phase-2',
    sourceHandle: 'phase-out', targetHandle: 'phase-in',
    type: 'straight', style: dashedStyle, markerEnd: arrow('#94a3b8'),
  },
  {
    id: 'e-phase-2-3',
    source: 'phase-2', target: 'phase-3',
    sourceHandle: 'phase-out', targetHandle: 'phase-in',
    type: 'straight', style: dashedStyle, markerEnd: arrow('#94a3b8'),
  },
  {
    id: 'e-phase-3-4',
    source: 'phase-3', target: 'phase-4',
    sourceHandle: 'phase-out', targetHandle: 'phase-in',
    type: 'straight', style: dashedStyle, markerEnd: arrow('#94a3b8'),
  },

  // --- QUALITY GATE EDGES ---
  // Horizontale Linie (Reviewing -> PASS -> Completing)
  { id: 'e-rev-pass',  source: 'reviewing',  target: 'pass-badge', sourceHandle: 'out-right',  targetHandle: 'in-left', type: 'straight', style: standardStyle },
  { id: 'e-pass-comp', source: 'pass-badge', target: 'completing', sourceHandle: 'out-right',  targetHandle: 'in-left', type: 'straight', style: standardStyle, markerEnd: arrow('#94a3b8') },

  // Vertikale Linie (Reviewing -> FAIL -> Fixing)
  { id: 'e-rev-fail',  source: 'reviewing',  target: 'fail-badge', sourceHandle: 'out-bottom', targetHandle: 'in-top',  type: 'straight', style: failStyle },
  { id: 'e-fail-fix',  source: 'fail-badge', target: 'fixing',     sourceHandle: 'out-bottom', targetHandle: 'in-top',  type: 'straight', style: failStyle, markerEnd: arrow('#ef4444') },

  // Der geschwungene Rück-Pfeil (Loop)
  { 
    id: 'e-fix-rev', 
    source: 'fixing', target: 'reviewing', 
    sourceHandle: 'out-left', targetHandle: 'in-left', 
    type: 'default',
    animated: false, 
    style: failStyle, 
    markerEnd: arrow('#ef4444') 
  },
]

// --- Responsive Auto-Fit Logic ---
let vueFlowInstance: any = null

const fitViewOptions = { padding: 0.05, minZoom: 1, maxZoom: 1 }

const onPaneReady = (instance: any) => {
  vueFlowInstance = instance

  // Zoom auf 1 = zentrieren ohne skalieren
  setTimeout(() => {
    vueFlowInstance.fitView(fitViewOptions)
  }, 50)

  window.addEventListener('resize', handleResize)
}

const handleResize = () => {
  if (vueFlowInstance) {
    window.requestAnimationFrame(() => {
      vueFlowInstance.fitView(fitViewOptions)
    })
  }
}

onBeforeUnmount(() => {
  window.removeEventListener('resize', handleResize)
})
</script>

<template>
  <section class="am-section am-section--container sm">
    <div class="am-container">
      <div class="am-eyebrow">02 — state machine</div>
      <h2 class="am-section-title">A deterministic flow.</h2>

      <ClientOnly>
        <div class="sm__flow-wrap">
          <VueFlow
            class="sm__vue-flow"
            :nodes="nodes"
            :edges="edges"
            :node-types="nodeTypes"
            :min-zoom="1"
            :max-zoom="1"
            fit-view-on-init="false"
            @pane-ready="onPaneReady"
            :nodes-draggable="false"
            :nodes-connectable="false"
            :elements-selectable="false"
            :pan-on-drag="false"
            :zoom-on-scroll="false"
            :zoom-on-double-click="false"
            :zoom-on-pinch="false"
            prevent-scrolling
          />
        </div>
        <template #fallback>
          <div class="sm__flow-wrap sm__flow-wrap--fallback" aria-hidden="true" />
        </template>
      </ClientOnly>

      <div class="sm__notes">
        <div>
          <strong>review loop</strong>
          <p>fixing → reviewing repeats until the verdict is pass or the loop cap is reached.</p>
        </div>
        <div>
          <strong>parallel reviewers</strong>
          <p>reviewing fans out into logic, quality, and expert — controlled by review_strategy.</p>
        </div>
        <div>
          <strong>changes_requested</strong>
          <p>At the approval step, a human can jump back to architecting.</p>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.sm__flow-wrap {
  width: 100%;
  min-height: 500px;
  height: 55vh;
  max-height: 640px;
  margin-bottom: 40px;
  border-radius: var(--am-r-md, 12px);
  overflow: hidden;
  background: var(--am-surface-lowest, #ffffff);
  border: 1px solid var(--am-outline-08, #e2e8f0);
}

.sm__flow-wrap--fallback {
  min-height: 500px;
}

.sm__vue-flow {
  width: 100%;
  height: 100%;
  min-height: 450px;
  border-radius: var(--am-r-md, 12px);
  image-rendering: -webkit-optimize-contrast;
}

/* Interaktion deaktivieren */
.sm__vue-flow :deep(.vue-flow__pane) {
  cursor: default !important;
}

/* === Z-INDEX FIX: Kanten (Edges) über die Boxen, unter die Agenten legen === */
.sm__vue-flow :deep(.vue-flow__edges) {
  z-index: 10 !important;
}
.sm__vue-flow :deep(.vue-flow__nodes) {
  z-index: 20 !important;
}

/* Kanten Label Styling */
.sm__vue-flow :deep(.vue-flow__edge-text) {
  font-family: var(--am-font-mono, monospace);
  text-transform: uppercase;
  letter-spacing: 0.08em;
}

/* === PHASE CONTAINERS === */
.sm__vue-flow :deep(.vue-flow__node-phase.sm__phase-container) {
  background-color: transparent !important;
  border: none !important;
  border-radius: 0 !important;
  padding: 0 !important;
  display: block !important;
  box-shadow: none !important;
  z-index: -1;
  overflow: visible !important;
}

/* Notes Section */
.sm__notes {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr;
  gap: 40px;
  padding-top: 32px;
}
.sm__notes strong {
  display: block;
  font-family: var(--am-font-mono);
  font-size: var(--am-label-md);
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--am-on-surface);
  margin-bottom: 6px;
  font-weight: 600;
}
.sm__notes p {
  margin: 0;
  font-size: var(--am-body-sm);
  color: var(--am-on-surface-variant);
  line-height: 1.6;
}

@media (max-width: 900px) {
  .sm__flow-wrap {
    min-height: 320px;
    height: 320px;
    max-height: none;
  }
  .sm__vue-flow {
    min-height: 0;
    height: 100%;
  }
  .sm__notes {
    grid-template-columns: 1fr;
    gap: 22px;
  }
}
</style>
