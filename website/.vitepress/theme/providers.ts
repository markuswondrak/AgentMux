export interface Provider {
  id: string
  /** Lowercase label used in code/config */
  label: string
  /** Display-case name used in prose */
  display: string
}

export const PROVIDERS: Provider[] = [
  { id: 'claude',   label: 'claude',   display: 'Claude' },
  { id: 'codex',    label: 'codex',    display: 'Codex' },
  { id: 'copilot',  label: 'copilot',  display: 'Copilot' },
  { id: 'cursor',   label: 'cursor',   display: 'Cursor' },
  { id: 'gemini',   label: 'gemini',   display: 'Gemini' },
  { id: 'opencode', label: 'opencode', display: 'OpenCode' },
  { id: 'qwen',     label: 'qwen',     display: 'Qwen' },
]

/** "claude · codex · copilot · cursor · gemini · opencode · qwen" */
export const providerDotList = PROVIDERS.map(p => p.label).join(' · ')

/** "claude, codex, copilot, cursor, gemini, opencode, qwen" */
export const providerCommaList = PROVIDERS.map(p => p.label).join(', ')

/** "Claude, Codex, Copilot, Cursor, Gemini, OpenCode, Qwen" */
export const providerDisplayList = PROVIDERS.map(p => p.display).join(', ')

export const providerCount = PROVIDERS.length
