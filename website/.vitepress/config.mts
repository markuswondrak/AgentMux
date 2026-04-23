import { defineConfig } from 'vitepress'
import yaml from '@rollup/plugin-yaml'

export default defineConfig({
  title: 'AgentMux',
  description: 'The deterministic agentic pipeline. Run a full multi-agent software workflow on the AI subscriptions you already have.',
  base: '/AgentMux/',
  cleanUrls: true,
  lastUpdated: true,
  appearance: false,

  head: [
    ['link', { rel: 'icon', href: '/AgentMux/favicon.svg?v=2', type: 'image/svg+xml' }],
    ['meta', { name: 'theme-color', content: '#0051ae' }],
    ['meta', { property: 'og:title', content: 'AgentMux — The deterministic agentic pipeline' }],
    ['meta', { property: 'og:description', content: 'Multi-agent software pipelines on the AI subscriptions you already have.' }],
    ['link', { rel: 'preconnect', href: 'https://fonts.googleapis.com' }],
    ['link', { rel: 'preconnect', href: 'https://fonts.gstatic.com', crossorigin: '' }],
    ['link', {
      rel: 'stylesheet',
      href: 'https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap',
    }],
  ],

  vite: {
    plugins: [yaml()],
  },

  themeConfig: {
    logo: { light: '/logo-light.svg', dark: '/logo-dark.svg', alt: 'AgentMux' },
    siteTitle: false,

    nav: [
      { text: 'Vision', link: '/#vision' },
      { text: 'Documentation', link: '/docs/getting-started', activeMatch: '/docs/' },
      { text: 'Roadmap', link: '/roadmap' },
      {
        text: 'GitHub',
        link: 'https://github.com/markuswondrak/AgentMux',
      },
    ],

    sidebar: {
      '/docs/': [
        {
          text: 'Getting Started',
          items: [
            { text: 'Quickstart', link: '/docs/getting-started' },
            { text: 'Configuration', link: '/docs/configuration' },
            { text: 'Prompts', link: '/docs/prompts' },
          ],
        },
        {
          text: 'Runtime',
          items: [
            { text: 'tmux Layout', link: '/docs/tmux-layout' },
            { text: 'Monitor', link: '/docs/monitor' },
            { text: 'Session Resumption', link: '/docs/session-resumption' },
          ],
        },
        {
          text: 'Protocols',
          items: [
            { text: 'File Protocol', link: '/docs/file-protocol' },
            { text: 'Handoff Contracts', link: '/docs/handoff-contracts' },
            { text: 'Research Dispatch', link: '/docs/research-dispatch' },
          ],
        },
        {
          text: 'Phases',
          collapsed: false,
          items: [
            { text: 'Overview', link: '/docs/phases/' },
            { text: 'Product Management', link: '/docs/phases/01_product-management' },
            { text: 'Architecting', link: '/docs/phases/02_architecting' },
            { text: 'Planning', link: '/docs/phases/04_planning' },
            { text: 'Design', link: '/docs/phases/05_design' },
            { text: 'Implementation', link: '/docs/phases/06_implementation' },
            { text: 'Review', link: '/docs/phases/07_review' },
            { text: 'Completion', link: '/docs/phases/08_completion' },
          ],
        },
        {
          text: 'Artifacts',
          collapsed: true,
          items: [
            { text: 'Overview', link: '/docs/artifacts/' },
            { text: 'Plan YAML', link: '/docs/artifacts/plan-yaml' },
            { text: 'Review YAML', link: '/docs/artifacts/review-yaml' },
            { text: 'Session State', link: '/docs/artifacts/session-state' },
            { text: 'Event Logs', link: '/docs/artifacts/event-logs' },
            { text: 'Completion Artifacts', link: '/docs/artifacts/completion-artifacts' },
          ],
        },
      ],
    },

    search: {
      provider: 'local',
    },

    editLink: {
      pattern: 'https://github.com/markuswondrak/AgentMux/edit/main/docs/:path',
      text: 'Edit on GitHub',
    },

    socialLinks: [
      { icon: 'github', link: 'https://github.com/markuswondrak/AgentMux' },
    ],

    footer: {
      message: 'Released under the MIT License.',
      copyright: 'Copyright © 2024–present AgentMux contributors',
    },
  },
})
