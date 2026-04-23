<script setup lang="ts">
import { onMounted, onBeforeUnmount, ref } from 'vue'
import { providerCommaList, providerDotList } from '../providers'

const root = ref<HTMLElement | null>(null)
const svgEl = ref<SVGSVGElement | null>(null)
let resizeObserver: ResizeObserver | null = null
let raf: number | null = null

const wires: [string, string, string, string, boolean][] = [
  ['.n-cli',      'bottom', '.n-orch',     'top',    false],
  ['.n-config',   'bottom', '.n-orch',     'top',    false],
  ['.n-state',    'bottom', '.n-orch',     'top',    false],
  ['.n-mcp',      'right',  '.n-bus',      'left',   false],
  ['.n-tmux',     'left',   '.n-monitor',  'right',  false],
  ['.n-orch',     'bottom', '.n-bus',      'top',    true],
  ['.n-bus',      'bottom', '.n-handlers', 'top',    true],
  ['.n-handlers', 'bottom', '.n-runtime',  'top',    true],
  ['.n-runtime',  'bottom', '.n-tmux',     'top',    true],
  ['.n-tmux',     'bottom', '.n-fs',       'top',    true],
  ['.n-fs',       'right',  '.n-bus',      'right',  true],
]

function edge(rect: DOMRect, side: string, origin: DOMRect): [number, number] {
  const x = rect.left - origin.left
  const y = rect.top - origin.top
  switch (side) {
    case 'right':  return [x + rect.width,    y + rect.height / 2]
    case 'left':   return [x,                 y + rect.height / 2]
    case 'top':    return [x + rect.width / 2, y]
    case 'bottom': return [x + rect.width / 2, y + rect.height]
  }
  return [x, y]
}

function bezier(p1: [number, number], fromSide: string, p2: [number, number], toSide: string) {
  const [x1, y1] = p1
  const [x2, y2] = p2
  const horiz = (s: string) => s === 'left' || s === 'right'

  if (fromSide === toSide && horiz(fromSide)) {
    const offset = Math.max(90, Math.abs(y2 - y1) * 0.45)
    const cx = fromSide === 'right' ? Math.max(x1, x2) + offset : Math.min(x1, x2) - offset
    return `M ${x1},${y1} C ${cx},${y1} ${cx},${y2} ${x2},${y2}`
  }
  if (fromSide === toSide && !horiz(fromSide)) {
    const offset = Math.max(70, Math.abs(x2 - x1) * 0.45)
    const cy = fromSide === 'bottom' ? Math.max(y1, y2) + offset : Math.min(y1, y2) - offset
    return `M ${x1},${y1} C ${x1},${cy} ${x2},${cy} ${x2},${y2}`
  }
  if (horiz(fromSide) && horiz(toSide)) {
    const mx = (x1 + x2) / 2
    return `M ${x1},${y1} C ${mx},${y1} ${mx},${y2} ${x2},${y2}`
  }
  if (!horiz(fromSide) && !horiz(toSide)) {
    const my = (y1 + y2) / 2
    return `M ${x1},${y1} C ${x1},${my} ${x2},${my} ${x2},${y2}`
  }
  if (horiz(fromSide)) {
    return `M ${x1},${y1} C ${x2},${y1} ${x2},${y1} ${x2},${y2}`
  }
  return `M ${x1},${y1} C ${x1},${y2} ${x1},${y2} ${x2},${y2}`
}

function clear() {
  if (!svgEl.value) return
  svgEl.value.querySelectorAll('path:not(defs path)').forEach((n) => n.remove())
}

function draw() {
  if (!svgEl.value || !root.value) return
  clear()
  const origin = svgEl.value.getBoundingClientRect()
  if (origin.width === 0 || origin.height === 0) return
  svgEl.value.setAttribute('viewBox', `0 0 ${origin.width} ${origin.height}`)
  const svgNS = 'http://www.w3.org/2000/svg'

  for (const [fromSel, fromSide, toSel, toSide, hot] of wires) {
    const a = root.value.querySelector(fromSel) as HTMLElement | null
    const b = root.value.querySelector(toSel) as HTMLElement | null
    if (!a || !b) continue
    const p1 = edge(a.getBoundingClientRect(), fromSide, origin)
    const p2 = edge(b.getBoundingClientRect(), toSide, origin)
    const path = document.createElementNS(svgNS, 'path')
    path.setAttribute('d', bezier(p1, fromSide, p2, toSide))
    if (hot) path.setAttribute('class', 'hot')
    path.setAttribute('marker-end', hot ? 'url(#arrow-hot)' : 'url(#arrow)')
    svgEl.value.appendChild(path)
  }
}

function schedule() {
  if (raf) cancelAnimationFrame(raf)
  raf = requestAnimationFrame(() => requestAnimationFrame(draw))
}

onMounted(() => {
  if (typeof document !== 'undefined' && document.fonts && document.fonts.ready) {
    document.fonts.ready.then(schedule)
  }
  schedule()
  window.addEventListener('resize', schedule)
  if (typeof ResizeObserver !== 'undefined' && root.value) {
    resizeObserver = new ResizeObserver(schedule)
    resizeObserver.observe(root.value)
  }
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', schedule)
  if (raf) cancelAnimationFrame(raf)
  resizeObserver?.disconnect()
})
</script>

<template>
  <section class="am-section am-section--container arch">
    <div class="am-container">
      <div class="am-eyebrow">Architecture · the closed event loop</div>
      <h2 class="am-section-title">A tmux-based orchestration kernel.</h2>
      <p class="arch__intro">
        Existing CLI agents ({{ providerCommaList }}) are driven by keystroke
        events injected into tmux panes. <strong>Agents never talk to each other</strong> — the
        orchestrator mediates exclusively through the file system and a shared event bus.
        <span class="arch__hot">The blue line marks the closed event loop.</span>
      </p>

      <div class="arch__diagram" ref="root">
        <svg class="arch__wires" ref="svgEl" aria-hidden="true">
          <defs>
            <marker id="arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="5" markerHeight="5" orient="auto">
              <path d="M0,0 L10,5 L0,10 z" fill="#c8d3e5" />
            </marker>
            <marker id="arrow-hot" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="5.5" markerHeight="5.5" orient="auto">
              <path d="M0,0 L10,5 L0,10 z" fill="#0051ae" />
            </marker>
          </defs>
        </svg>

        <div class="arch__grid">
          <article class="node n-cli">
            <div class="node__label">entry</div>
            <h3>pipeline.application</h3>
            <p>CLI entry, launcher, --orchestrate mode.</p>
          </article>

          <article class="node n-config">
            <div class="node__label">config</div>
            <h3>configuration</h3>
            <p>Four layers: defaults → user → project → CLI.</p>
          </article>

          <article class="node n-state">
            <div class="node__label">sessions</div>
            <h3>state_store</h3>
            <p>Creates &amp; resumes feature sessions. state.json holds the phase.</p>
          </article>

          <article class="node n-orch">
            <div class="node__label">core</div>
            <h3>workflow.orchestrator</h3>
            <p>Routes events to phase handlers, drives the state machine, builds prompts lazily and dispatches them to the right pane.</p>
          </article>

          <article class="node n-mcp">
            <div class="node__label">mcp</div>
            <h3>mcp_server</h3>
            <p>Research dispatch and submit tools. Writes tool events to jsonl.</p>
          </article>

          <article class="node n-bus">
            <div class="node__label">events</div>
            <h3>event bus</h3>
            <ul>
              <li>FileEventSource — watchdog</li>
              <li>ToolCallEventSource — jsonl tail</li>
              <li>InterruptionEventSource — pane poll</li>
            </ul>
          </article>

          <article class="node n-handlers">
            <div class="node__label">handlers</div>
            <h3>phase handlers</h3>
            <p>architecting · planning · designing · implementing · reviewing (∥) · fixing · completing</p>
          </article>

          <article class="node n-runtime">
            <div class="node__label">runtime</div>
            <h3>tmux_control</h3>
            <p>Pane lifecycle. send_prompt() injects "Read /path/prompt.md".</p>
          </article>

          <article class="node n-monitor">
            <div class="node__label">render</div>
            <h3>monitor.render</h3>
            <p>ANSI status rendering for the control pane.</p>
          </article>

          <article class="node n-tmux">
            <div class="node__label">session</div>
            <h3>tmux session</h3>
            <p>Monitor pane left, agent panes right. Each pane hosts a CLI: {{ providerDotList }}.</p>
          </article>

          <article class="node n-fs">
            <div class="node__label">artifacts</div>
            <h3>.agentmux/.sessions/&lt;feature&gt;</h3>
            <ul>
              <li>state.json · created_files.log</li>
              <li>01_product · 02_arch · 03_plan · 04_research · 05_design …</li>
              <li>tool_events.jsonl</li>
            </ul>
          </article>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.arch__intro {
  max-width: 720px;
  font-size: var(--am-body-md);
  line-height: 1.6;
  color: var(--am-on-surface-variant);
  margin: 0 0 56px;
}
.arch__intro strong { color: var(--am-on-surface); font-weight: 600; }
.arch__hot { color: var(--am-primary); font-weight: 500; }

.arch__diagram {
  position: relative;
}

.arch__wires {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  pointer-events: none;
  z-index: 1;
  overflow: visible;
}
.arch__wires :deep(path) {
  fill: none;
  stroke: #c8d3e5;
  stroke-width: 1;
}
.arch__wires :deep(path.hot) {
  stroke: var(--am-primary);
  stroke-width: 1.6;
}

.arch__grid {
  display: grid;
  grid-template-columns: 1fr 1.45fr 1fr;
  gap: 32px 56px;
  position: relative;
  z-index: 2;
  font-family: var(--am-font-mono);
  font-size: 12px;
  color: var(--am-on-surface);
}

.node {
  background: var(--am-surface-lowest);
  border-radius: var(--am-r-md);
  padding: 16px 18px 18px;
  position: relative;
}

.node__label {
  font-family: var(--am-font-mono);
  font-size: 9.5px;
  font-weight: 500;
  letter-spacing: 0.18em;
  text-transform: uppercase;
  color: var(--am-on-surface-3);
  margin-bottom: 8px;
}

.node h3 {
  margin: 0 0 6px;
  font-family: var(--am-font-sans);
  font-weight: 600;
  font-size: 14px;
  color: var(--am-on-surface);
  letter-spacing: -0.005em;
}

.node p {
  margin: 0;
  font-family: var(--am-font-mono);
  font-size: 11px;
  color: var(--am-on-surface-variant);
  line-height: 1.55;
  font-weight: 400;
}

.node ul {
  margin: 6px 0 0;
  padding: 0;
  list-style: none;
  font-family: var(--am-font-mono);
  font-size: 10.5px;
  color: var(--am-on-surface-variant);
  font-weight: 400;
}
.node ul li::before { content: '· '; color: var(--am-on-surface-3); }

/* Inverted orchestrator */
.n-orch {
  background: var(--am-on-surface);
  background-image: radial-gradient(circle at 20% 0%, rgba(9, 105, 218, 0.30) 0%, transparent 60%);
}
.n-orch h3 { color: var(--am-surface-lowest); }
.n-orch p, .n-orch ul { color: rgba(226, 232, 240, 0.78); }
.n-orch .node__label { color: rgba(226, 232, 240, 0.45); }
.n-orch ul li::before { color: rgba(226, 232, 240, 0.45); }

/* Grid placement — vertical event-loop spine (preserved from original) */
.n-cli       { grid-column: 1; grid-row: 1; }
.n-config    { grid-column: 2; grid-row: 1; }
.n-state     { grid-column: 3; grid-row: 1; }
.n-orch      { grid-column: 2; grid-row: 2; }
.n-mcp       { grid-column: 1; grid-row: 3; }
.n-bus       { grid-column: 2; grid-row: 3; }
.n-handlers  { grid-column: 2; grid-row: 4; }
.n-runtime   { grid-column: 2; grid-row: 5; }
.n-monitor   { grid-column: 1; grid-row: 6; }
.n-tmux      { grid-column: 2; grid-row: 6; }
.n-fs        { grid-column: 2; grid-row: 7; }

@media (max-width: 1000px) {
  .arch__grid {
    grid-template-columns: 1fr;
    gap: 16px;
  }
  .n-cli, .n-config, .n-state, .n-mcp, .n-orch, .n-bus,
  .n-handlers, .n-runtime, .n-tmux, .n-fs, .n-monitor {
    grid-column: 1;
    grid-row: auto;
  }
  .arch__wires { display: none; }
}
</style>
