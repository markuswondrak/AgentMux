#!/usr/bin/env node
/**
 * sync-docs.mjs
 *
 * Copies ../docs/**\/*.md into website/docs/, skipping the analysis/ subdirectory.
 * Also rewrites .md link suffixes for VitePress cleanUrls mode.
 *
 * Run via: node scripts/sync-docs.mjs
 * Hooked into: predev, prebuild
 */

import { readdir, readFile, writeFile, mkdir, rm } from 'node:fs/promises'
import { join, relative, dirname, extname } from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = dirname(fileURLToPath(import.meta.url))
const SOURCE_ROOT = join(__dirname, '../../docs')
const DEST_ROOT = join(__dirname, '../docs')
const SKIP_DIRS = new Set(['analysis'])

// Regex: matches markdown links pointing to local .md files (not http/mailto/#)
// Captures: group 1 = path (without .md), group 2 = optional anchor
const MD_LINK_RE = /(\]\()(?!https?:|mailto:|#)([^)]+?)\.md(#[^)]*)?(\))/g

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

async function main() {
  // Wipe and recreate destination
  await rm(DEST_ROOT, { recursive: true, force: true })
  await mkdir(DEST_ROOT, { recursive: true })

  for await (const srcPath of walk(SOURCE_ROOT)) {
    const rel = relative(SOURCE_ROOT, srcPath)
    const destPath = join(DEST_ROOT, rel)

    // Ensure parent directory exists
    await mkdir(dirname(destPath), { recursive: true })

    const content = await readFile(srcPath, 'utf-8')
    const rewritten = rewriteLinks(content)
    await writeFile(destPath, rewritten, 'utf-8')
    fileCount++
  }

  // Write a minimal docs index so /docs/ doesn't 404
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
`
  await writeFile(join(DEST_ROOT, 'index.md'), indexContent, 'utf-8')

  const elapsed = Date.now() - startTime
  console.log(`[sync-docs] copied ${fileCount} files, rewrote ${linkCount} links in ${elapsed}ms`)
}

main().catch((err) => {
  console.error('[sync-docs] error:', err)
  process.exit(1)
})
