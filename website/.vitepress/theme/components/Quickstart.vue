<template>
  <div class="qs-root">
    <h2>Quickstart</h2>
    <div class="qs-steps">
      <div v-for="(step, i) in steps" :key="i" class="qs-step">
        <span class="qs-num">{{ i + 1 }}</span>
        <div class="qs-content">
          <span class="qs-label">{{ step.label }}</span>
          <div class="qs-code-wrap">
            <code>{{ step.code }}</code>
            <button class="qs-copy" :title="copied === i ? 'Copied!' : 'Copy'" @click="copy(i, step.code)">
              <svg v-if="copied !== i" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                <rect x="9" y="9" width="13" height="13" rx="2" />
                <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
              </svg>
              <svg v-else xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.5">
                <polyline points="20 6 9 17 4 12" />
              </svg>
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'

const steps = [
  {
    label: 'Install',
    code: 'pipx install git+https://github.com/markuswondrak/AgentMux.git',
  },
  {
    label: 'Configure providers',
    code: 'agentmux init',
  },
  {
    label: 'Run a pipeline',
    code: 'agentmux "Add a dark-mode toggle to the settings page"',
  },
]

const copied = ref<number | null>(null)
let timer: ReturnType<typeof setTimeout> | null = null

async function copy(index: number, text: string) {
  try {
    await navigator.clipboard.writeText(text)
    copied.value = index
    if (timer) clearTimeout(timer)
    timer = setTimeout(() => {
      copied.value = null
    }, 2000)
  } catch {
    // clipboard API not available (non-https dev env, etc.) — silently ignore
  }
}
</script>
