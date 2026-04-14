# AgentMux Website

VitePress site for AgentMux — landing page, full docs, and roadmap. Deployed to GitHub Pages from the `main` branch via `.github/workflows/deploy-pages.yml`.

## Develop

```bash
cd website
pnpm install
pnpm run dev
```

Visit `http://localhost:5173/AgentMux/`.

## Build

```bash
pnpm run build      # outputs to .vitepress/dist
pnpm run preview    # serve the built site locally
```

## Docs source

The contents of `../docs/**` are copied into `./docs/` at build time by `scripts/sync-docs.mjs`. Do **not** edit files in `./docs/` directly — they are generated and gitignored. Edit the source markdown in the repo's top-level `docs/` directory.
