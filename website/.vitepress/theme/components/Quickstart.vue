<script setup lang="ts">
import { ref } from 'vue'

interface Step {
  num: string
  title: string
  body: string
  command: string
}

const steps: Step[] = [
  {
    num: '01',
    title: 'Install',
    body: 'Pull the AgentMux CLI as an isolated tool with pipx. It exposes the agentmux command everywhere.',
    command: 'pipx install git+https://github.com/markuswondrak/AgentMux.git',
  },
  {
    num: '02',
    title: 'Initialise the project',
    body: 'Scaffold the .agentmux/ directory in your repo. The interactive wizard configures providers per role.',
    command: 'cd your-repo && agentmux init',
  },
  {
    num: '03',
    title: 'Run the pipeline',
    body: 'Hand AgentMux a feature description. It opens a tmux session and drives the workflow end-to-end.',
    command: 'agentmux "Add rate limiting to the API"',
  },
]

const copied = ref<string | null>(null)

async function copy(cmd: string) {
  try {
    await navigator.clipboard.writeText(cmd)
    copied.value = cmd
    setTimeout(() => (copied.value = null), 1600)
  } catch (_) {
    /* noop */
  }
}
</script>

<template>
  <section class="am-section am-section--surface qs">
    <div class="am-container">
      <div class="am-eyebrow">Quickstart</div>
      <h2 class="am-section-title">Three commands to a deterministic pipeline.</h2>
      <p class="am-section-tagline">
        From zero to a tmux session driving multiple AI CLIs in under three minutes.
      </p>

      <ol class="qs__steps">
        <li v-for="step in steps" :key="step.num" class="qs__step">
          <div class="qs__num">{{ step.num }}</div>
          <div class="qs__content">
            <h3 class="qs__title">{{ step.title }}</h3>
            <p class="qs__body">{{ step.body }}</p>
            <div class="qs__code">
              <code>{{ step.command }}</code>
              <button
                class="qs__copy"
                type="button"
                :aria-label="`Copy command: ${step.command}`"
                @click="copy(step.command)"
              >
                {{ copied === step.command ? 'COPIED' : 'COPY' }}
              </button>
            </div>
          </div>
        </li>
      </ol>
    </div>
  </section>
</template>

<style scoped>
.qs__steps {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 28px;
}

.qs__step {
  display: grid;
  grid-template-columns: 64px 1fr;
  gap: 24px;
  align-items: start;
}

.qs__num {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 48px;
  height: 48px;
  border-radius: 50%;
  background: var(--am-secondary-strong);
  color: #054b05;
  font-family: var(--am-font-mono);
  font-weight: 500;
  font-size: 0.875rem;
  letter-spacing: 0.04em;
}

.qs__content { min-width: 0; }

.qs__title {
  font-family: var(--am-font-sans);
  font-weight: 600;
  font-size: 1.25rem;
  letter-spacing: -0.018em;
  color: var(--am-on-surface);
  margin: 6px 0 6px;
}

.qs__body {
  font-size: var(--am-body-md);
  color: var(--am-on-surface-variant);
  margin: 0 0 14px;
  line-height: 1.55;
}

.qs__code {
  position: relative;
  display: flex;
  align-items: center;
  background: var(--am-surface-container);
  border-radius: var(--am-r-md);
  padding: 14px 16px;
  padding-right: 92px;
  overflow-x: auto;
}
.qs__code code {
  font-family: var(--am-font-mono);
  font-size: 0.875rem;
  color: var(--am-on-surface);
  white-space: nowrap;
}

.qs__copy {
  position: absolute;
  right: 10px;
  top: 50%;
  transform: translateY(-50%);
  background: transparent;
  color: var(--am-primary);
  font-family: var(--am-font-mono);
  font-size: var(--am-label-sm);
  font-weight: 500;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  padding: 6px 10px;
  border-radius: var(--am-r-sm);
  border: none;
  cursor: pointer;
  transition: background 160ms ease;
}
.qs__copy:hover { background: var(--am-primary-soft-08); }

@media (max-width: 640px) {
  .qs__step { grid-template-columns: 48px 1fr; gap: 16px; }
  .qs__num { width: 40px; height: 40px; }
}
</style>
