<script setup lang="ts">
</script>

<template>
  <section class="am-section am-section--surface rcta">
    <div class="am-container rcta__inner">
      <div class="am-eyebrow">Contribute</div>
      <h2 class="rcta__title">Shape the roadmap.</h2>
      <p class="rcta__body">
        AgentMux is open source. Open an issue to propose a feature, pick up an existing one,
        or start a thread on GitHub Discussions.
      </p>
      <div class="rcta__actions">
        <a
          class="am-btn am-btn--primary"
          href="https://github.com/markuswondrak/AgentMux/issues/new"
          target="_blank"
          rel="noopener"
        >
          Open an Issue
        </a>
        <a
          class="am-btn am-btn--secondary"
          href="https://github.com/markuswondrak/AgentMux/discussions"
          target="_blank"
          rel="noopener"
        >
          Discussions
        </a>
      </div>
    </div>
  </section>
</template>

<style scoped>
.rcta__inner {
  background: var(--am-surface-lowest);
  border-radius: var(--am-r-lg);
  padding: clamp(36px, 5vw, 56px) clamp(28px, 5vw, 56px);
  display: grid;
  grid-template-columns: minmax(0, 1.4fr) minmax(0, auto);
  gap: 28px;
  align-items: center;
}

.rcta__title {
  font-family: var(--am-font-sans);
  font-weight: 700;
  font-size: var(--am-headline-md);
  letter-spacing: -0.022em;
  color: var(--am-on-surface);
  margin: 0 0 12px;
  grid-column: 1;
}

.am-eyebrow {
  grid-column: 1;
  margin-bottom: 0;
}

.rcta__body {
  grid-column: 1;
  font-size: var(--am-body-md);
  color: var(--am-on-surface-variant);
  margin: 0;
  line-height: 1.55;
  max-width: 56ch;
}

.rcta__actions {
  grid-column: 2;
  grid-row: 1 / span 3;
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
  justify-content: flex-end;
}

@media (max-width: 768px) {
  .rcta__inner { grid-template-columns: 1fr; }
  .rcta__actions {
    grid-column: 1;
    grid-row: auto;
    justify-content: flex-start;
  }
}
</style>
