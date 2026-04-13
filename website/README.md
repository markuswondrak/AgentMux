# AgentMux Website

This directory contains the [VitePress](https://vitepress.dev) source for the AgentMux documentation website, published to [markuswondrak.github.io/AgentMux/](https://markuswondrak.github.io/AgentMux/).

## Local development

```bash
cd website
pnpm install
pnpm dev      # starts dev server at http://localhost:5173/AgentMux/
```

## How docs sync works

The Markdown files under `website/docs/` are **build artifacts** — they are copied from the project's top-level `docs/` directory by `scripts/sync-docs.mjs` before every `dev` and `build` run. Do not edit files inside `website/docs/`; edit the source in `../docs/` instead.

The sync script also rewrites `.md` link suffixes for VitePress' `cleanUrls` mode.

## Building

```bash
pnpm build    # output in .vitepress/dist/
pnpm preview  # serve dist/ locally
```

## Deploy

Deployment to GitHub Pages happens automatically via `.github/workflows/deploy-pages.yml` on every push to `main` that touches `website/` or `docs/`.
