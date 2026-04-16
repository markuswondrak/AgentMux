#!/usr/bin/env node
/**
 * sync-docs.mjs
 *
 * Copies ../docs/** /*.md into website/docs/ (skipping analysis/) and rewrites
 * .md link suffixes for VitePress cleanUrls. Also extracts the `roadmap` block
 * from docs/roadmap.md frontmatter into website/data/roadmap.yaml so the docs
 * file stays the single source of truth for the roadmap.
 *
 * Hooked into: predev, prebuild
 */

import { readdir, readFile, writeFile, mkdir, rm } from 'node:fs/promises'
import { join, relative, dirname, extname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { dump } from 'js-yaml'

const __dirname = dirname(fileURLToPath(import.meta.url))
const SOURCE_ROOT = join(__dirname, '../../docs')
const DEST_ROOT = join(__dirname, '../docs')
const ROADMAP_SRC = join(SOURCE_ROOT, 'roadmap.md')
const ROADMAP_OUT = join(__dirname, '../data/roadmap.yaml')
const SKIP_DIRS = new Set(['analysis'])

const MD_LINK_RE = /(\]\()(?!https?:|mailto:|#)([^)]+?)\.md(#[^)]*)?(\))/g
const FRONTMATTER_RE = /^---\r?\n[\s\S]*?\r?\n---\r?\n?/
const HTML_COMMENT_RE = /<!--[\s\S]*?-->/g
const H2_RE = /^## (.+)\s*$/
const BULLET_RE = /^- \*\*(.+?)\*\*\s*·\s*(.+)$/
const STATUSES = new Set(['deployed', 'in_progress', 'ambitious'])
const CATEGORY_RE = /^[A-Z][A-Z0-9_]*$/
const ISSUE_RE = /^#(\d+)$/

let fileCount = 0
let linkCount = 0
const startTime = Date.now()

async function* walk(dir) {
  const entries = await readdir(dir, { withFileTypes: true })
  for (const entry of entries) {
    const fullPath = join(dir, entry.name)
    if (entry.isDirectory()) {
      if (SKIP_DIRS.has(entry.name)) continue
      yield* walk(fullPath)
    } else if (entry.isFile() && extname(entry.name) === '.md') {
      yield fullPath
    }
  }
}

function rewriteLinks(content) {
  let count = 0
  const result = content.replace(MD_LINK_RE, (match, open, path, anchor, close) => {
    count++
    return `${open}${path}${anchor ?? ''}${close}`
  })
  linkCount += count
  return result
}

function slug(str) {
  return str.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '')
}

function parseRoadmap(raw) {
  const body = raw.replace(FRONTMATTER_RE, '').replace(HTML_COMMENT_RE, '')
  const lines = body.split('\n')
  const columns = []
  let currentColumn = null
  let currentItem = null

  const fail = (msg, lineNum) => {
    throw new Error(`docs/roadmap.md:${lineNum + 1}: ${msg}`)
  }

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]

    const h2 = line.match(H2_RE)
    if (h2) {
      currentItem = null
      currentColumn = { id: slug(h2[1]), title: h2[1].trim(), items: [] }
      columns.push(currentColumn)
      continue
    }

    const bullet = line.match(BULLET_RE)
    if (bullet) {
      if (!currentColumn) fail(`bullet appears before any '## Column' heading`, i)
      const title = bullet[1].trim()
      const segments = bullet[2].split(/\s*·\s*/).map((s) => s.trim()).filter(Boolean)
      let status = null
      let category
      let issue
      for (const seg of segments) {
        if (STATUSES.has(seg)) {
          status = seg
        } else if (ISSUE_RE.test(seg)) {
          issue = Number(seg.slice(1))
        } else if (CATEGORY_RE.test(seg)) {
          category = seg
        } else {
          fail(`item "${title}": unknown segment "${seg}" (expected status, UPPERCASE category, or #issue)`, i)
        }
      }
      if (!status) {
        fail(`item "${title}": missing status (one of ${[...STATUSES].join(', ')})`, i)
      }
      currentItem = { title, status }
      if (category) currentItem.category = category
      if (issue !== undefined) currentItem.issue = issue
      currentItem.description = ''
      currentColumn.items.push(currentItem)
      continue
    }

    // Indented continuation under the current bullet → description text.
    if (currentItem && /^\s{2,}\S/.test(line)) {
      const text = line.trim()
      currentItem.description = currentItem.description
        ? `${currentItem.description} ${text}`
        : text
      continue
    }

    // Any non-indented, non-empty line ends the current item context so
    // free prose between bullets never leaks into the parsed data.
    if (line.trim() && !/^\s/.test(line)) {
      currentItem = null
    }
  }

  if (columns.length === 0) {
    throw new Error(`docs/roadmap.md: no '## Column' headings found`)
  }

  for (const col of columns) {
    for (const item of col.items) {
      if (!item.description) delete item.description
    }
  }

  return { columns }
}

async function extractRoadmapData() {
  const raw = await readFile(ROADMAP_SRC, 'utf-8')
  const data = parseRoadmap(raw)
  const yaml = dump(data, { lineWidth: 120, noRefs: true })
  const header = `# AUTO-GENERATED from docs/roadmap.md by scripts/sync-docs.mjs.\n# Do not edit by hand — update docs/roadmap.md and rerun 'pnpm sync-docs'.\n`
  await mkdir(dirname(ROADMAP_OUT), { recursive: true })
  await writeFile(ROADMAP_OUT, header + yaml, 'utf-8')
}

async function main() {
  await rm(DEST_ROOT, { recursive: true, force: true })
  await mkdir(DEST_ROOT, { recursive: true })

  for await (const srcPath of walk(SOURCE_ROOT)) {
    const rel = relative(SOURCE_ROOT, srcPath)
    const destPath = join(DEST_ROOT, rel)
    await mkdir(dirname(destPath), { recursive: true })
    const content = await readFile(srcPath, 'utf-8')
    const rewritten = rewriteLinks(content)
    await writeFile(destPath, rewritten, 'utf-8')
    fileCount++
  }

  await extractRoadmapData()

  const indexContent = `---
title: Documentation
---

# Documentation

Welcome to the AgentMux documentation. Use the sidebar to navigate.

- [Getting Started](/docs/getting-started)
- [Configuration](/docs/configuration)
- [File Protocol](/docs/file-protocol)
- [Handoff Contracts](/docs/handoff-contracts)
- [Session Resumption](/docs/session-resumption)
- [Research Dispatch](/docs/research-dispatch)
- [Prompts](/docs/prompts)
- [tmux Layout](/docs/tmux-layout)
- [Monitor](/docs/monitor)
- [Roadmap](/roadmap)
`
  await writeFile(join(DEST_ROOT, 'index.md'), indexContent, 'utf-8')

  const elapsed = Date.now() - startTime
  console.log(`[sync-docs] copied ${fileCount} files, rewrote ${linkCount} links, extracted roadmap in ${elapsed}ms`)
}

main().catch((err) => {
  console.error('[sync-docs] error:', err)
  process.exit(1)
})
