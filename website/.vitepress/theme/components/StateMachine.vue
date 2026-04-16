<script setup lang="ts">
</script>

<template>
  <section class="am-section am-section--container sm">
    <div class="am-container">
      <div class="am-eyebrow">02 — state machine</div>
      <h2 class="am-section-title">A deterministic flow.</h2>

      <div class="sm__flow">
        <span class="sm__pill sm__pill--opt">product_management</span>
        <span class="sm__arrow">→</span>
        <span class="sm__pill">architecting</span>
        <span class="sm__arrow">→</span>
        <span class="sm__pill">planning</span>
        <span class="sm__arrow">→</span>
        <span class="sm__pill sm__pill--opt">designing</span>
        <span class="sm__arrow">→</span>
        <span class="sm__pill">implementing</span>
        <span class="sm__arrow">→</span>
        <span class="sm__pill">reviewing</span>
        <span class="sm__arrow">→</span>
        <div class="sm__branch">
          <div class="sm__row">
            <span class="sm__branch-label sm__branch-label--pass">pass</span>
            <span class="sm__pill sm__pill--pass">completing</span>
          </div>
          <div class="sm__row">
            <span class="sm__branch-label sm__branch-label--fail">fail</span>
            <span class="sm__pill sm__pill--fail">fixing</span>
            <span class="sm__arrow">↺</span>
            <span class="sm__pill">reviewing</span>
          </div>
        </div>
      </div>

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
.sm__flow {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  row-gap: 14px;
  margin-bottom: 56px;
  font-family: var(--am-font-mono);
  font-size: 12px;
}

.sm__pill {
  background: var(--am-surface-lowest);
  color: var(--am-on-surface);
  border-radius: var(--am-r-md);
  padding: 8px 13px;
  white-space: nowrap;
  font-weight: 500;
  letter-spacing: 0.01em;
}

.sm__pill--opt {
  background: transparent;
  border: 1px dashed var(--am-outline-15);
  color: var(--am-on-surface-variant);
  font-weight: 400;
}

.sm__pill--pass {
  background: var(--am-secondary-strong);
  color: #054b05;
}
.sm__pill--fail {
  background: rgba(186, 26, 26, 0.12);
  color: var(--am-error);
}

.sm__arrow {
  padding: 0 10px;
  color: var(--am-on-surface-3);
  user-select: none;
}

.sm__branch {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.sm__row {
  display: flex;
  align-items: center;
}
.sm__branch-label {
  font-size: 10px;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  margin-right: 12px;
  min-width: 32px;
  font-weight: 500;
}
.sm__branch-label--pass { color: var(--am-secondary); }
.sm__branch-label--fail { color: var(--am-error); }

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
  font-weight: 500;
}
.sm__notes p {
  margin: 0;
  font-size: var(--am-body-sm);
  color: var(--am-on-surface-variant);
  line-height: 1.55;
}

@media (max-width: 900px) {
  .sm__notes { grid-template-columns: 1fr; gap: 22px; }
}
</style>
