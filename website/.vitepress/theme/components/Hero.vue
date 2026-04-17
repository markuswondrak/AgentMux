<script setup lang="ts">
import { withBase } from 'vitepress'
</script>

<template>
  <section class="am-section am-section--surface hero">
    <div class="am-container hero__grid">
      <div class="hero__copy">
        <div class="am-eyebrow">Introducing AgentMux v0 · Alpha</div>
        <h1 class="hero__headline">
          The <em>deterministic</em><br />
          agentic pipeline.
        </h1>
        <p class="hero__tagline">
          AgentMux orchestrates a deterministic multi-agent workflow for end-to-end software
          development. It drives the AI CLIs you already use — Claude, Codex, Copilot, Gemini,
          OpenCode, Qwen — through tmux, reusing your existing subscriptions instead of paying
          per token.
        </p>
        <div class="hero__cta-row">
          <a class="am-btn am-btn--primary" :href="withBase('/docs/getting-started')">
            Get Started
          </a>
          <a
            class="am-btn am-btn--tertiary"
            href="https://github.com/markuswondrak/AgentMux"
            target="_blank"
            rel="noopener"
          >
            View Source ▸
          </a>
        </div>
      </div>

      <div class="hero__visual">
        <div class="hero__sheet">
          <img
            class="hero__sheet-img"
            :src="withBase('/hero-agentmux.png')"
            alt="AgentMux tmux session — monitor pane on the left, agent panes on the right running claude, codex, gemini"
            width="1287"
            height="1063"
            loading="eager"
          />
        </div>

        <div class="hero__metric">
          <div class="hero__metric-label">▸ CLI providers</div>
          <div class="hero__metric-value">6<span class="hero__metric-unit">&nbsp;bridges</span></div>
          <div class="hero__metric-sub">claude · codex · copilot · gemini · opencode · qwen</div>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.hero {
  padding-top: clamp(80px, 12vw, 140px);
  padding-bottom: clamp(72px, 10vw, 120px);
}

.hero__grid {
  display: grid;
  grid-template-columns: minmax(0, 1.05fr) minmax(0, 1fr);
  gap: clamp(36px, 6vw, 80px);
  align-items: center;
}

.hero__headline {
  font-family: var(--am-font-sans);
  font-weight: 700;
  font-size: var(--am-display-xl);
  line-height: 1.02;
  letter-spacing: -0.028em;
  color: var(--am-on-surface);
  margin: 0 0 24px;
}

.hero__headline em {
  font-style: italic;
  font-weight: 700;
  background: var(--am-grad-text);
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
}

.hero__tagline {
  font-size: var(--am-body-lg);
  line-height: 1.55;
  color: var(--am-on-surface-variant);
  max-width: 56ch;
  margin: 0 0 36px;
}

.hero__cta-row {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

/* Visual column */
.hero__visual {
  position: relative;
  display: flex;
  justify-content: center;
  align-items: center;
  min-height: 380px;
}

.hero__sheet {
  position: relative;
  width: 100%;
  max-width: 560px;
  background: var(--am-on-surface);
  border-radius: var(--am-r-lg);
  padding: 28px 32px 32px 32px;
  overflow: hidden;
  box-shadow: var(--am-shadow-ambient);
  isolation: isolate;
}

.hero__sheet::before {
  content: '';
  position: absolute;
  inset: 0;
  background: radial-gradient(ellipse at 50% 60%, rgba(9, 105, 218, 0.35) 0%, transparent 60%);
  z-index: 0;
}

.hero__sheet-img {
  position: relative;
  z-index: 1;
  width: 100%;
  height: auto;
  display: block;
}

.hero__metric {
  position: absolute;
  bottom: -28px;
  left: -28px;
  background: rgba(247, 249, 255, 0.82);
  -webkit-backdrop-filter: blur(14px) saturate(140%);
  backdrop-filter: blur(14px) saturate(140%);
  border-radius: var(--am-r-md);
  padding: 16px 22px 18px 24px;
  min-width: 200px;
  box-shadow: var(--am-shadow-ambient-strong);
}

.hero__metric-label {
  font-family: var(--am-font-mono);
  font-size: var(--am-label-sm);
  font-weight: 500;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  color: var(--am-on-surface-3);
  margin-bottom: 6px;
}

.hero__metric-value {
  font-family: var(--am-font-mono);
  font-weight: 500;
  font-size: 2.25rem;
  color: var(--am-on-surface);
  letter-spacing: -0.02em;
  line-height: 1;
}

.hero__metric-unit {
  font-size: 1.125rem;
  color: var(--am-on-surface-variant);
  margin-left: 2px;
}

.hero__metric-sub {
  margin-top: 4px;
  font-family: var(--am-font-mono);
  font-size: var(--am-label-sm);
  color: var(--am-on-surface-variant);
  letter-spacing: 0.02em;
}

@media (max-width: 1024px) {
  .hero__grid {
    grid-template-columns: 1fr;
    gap: 56px;
  }
  .hero__visual { min-height: 0; }
  .hero__metric {
    position: relative;
    bottom: auto;
    left: auto;
    margin-top: -32px;
    margin-left: 16px;
  }
}

@media (max-width: 640px) {
  .hero__sheet { padding: 20px 22px 24px 22px; }
}
</style>
