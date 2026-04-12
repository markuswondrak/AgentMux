---
description: "Debug-AgentMux session: show session directory, log files, and their semantics"
---
## AgentMux Session Debug

### Aktuelles Session-Verzeichnis

Das Session-Verzeichnis liegt unter `.agentmux/.sessions/<session-id>-<feature-name>/`.

Jede Session hat folgenden Aufbau:

```
<session-dir>/
├── context.md              # Feature-Kontext und Anforderungen
├── requirements.md         # Produktanforderungen
├── state.json              # Session-State (Phase, Issue, Branch, etc.)
├── runtime_state.json      # TMUX-Pane-Zuordnung der Agent-Rollen
├── orchestrator.log        # TMUX-Session-Erstellung und Pane-Lifecycle
├── created_files.log       # Liste generierter Dateien mit Zeitstempel
├── status_log.txt          # Aktueller Pipeline-Status (Phase-Zeitstempel)
└── <phase_ordner>/         # Phase-spezifische Outputs (z.B. 01_product_management/)
```

### Log-Dateien und deren Semantik

| Datei | Semantik |
|-------|----------|
| `state.json` | **Session-Metadaten**: Feature-Dir, Session-Name, aktuelle Phase, GitHub Issue-Info, Feature-Branch, Subplan-Fortschritt, Review-Iteration. Zeigt wo die Pipeline gerade steht. |
| `runtime_state.json` | **TMUX-Runtime-State**: Pane-IDs pro Agent-Rolle (product-manager, architect, coder, etc.), sichtbare Panes, parallele Tasks, Prozess-PIDs. Wichtig für TMUX-Layout-Probleme. |
| `orchestrator.log` | **TMUX-Lifecycle**: Session-Erstellung, Pane-Ready-Checks, Layout-Enforcement (Monitor-Breite), Pane-Resizes. Debugging-Hilfe wenn Panes nicht korrekt initialisiert werden. |
| `created_files.log` | **Artefakt-Protokoll**: Welche Dateien wurden wann generiert? Zeigt den Output der aktuellen Phase. |
| `status_log.txt` | **Pipeline-Fortschritt**: Einfaches Log welche Phase wann gestartet wurde. Schnell-Überblick des aktuellen Schritts. |

### Debug-Anweisungen

Analysiere den aktuellen Zustand der AgentMux-Session:

1. **Session-Verzeichnis ermitteln**: Finde das neueste Session-Verzeichnis in `.agentmux/.sessions/`
2. **State prüfen**: Lies `state.json` – welche Phase ist aktiv, gibt es ein GitHub Issue?
3. **Runtime prüfen**: Lies `runtime_state.json` – sind alle Agent-Panes korrekt zugewiesen?
4. **Logs prüfen**:
   - `orchestrator.log` auf TMUX-Fehler oder Layout-Probleme
   - `created_files.log` ob erwartete Dateien generiert wurden
   - `status_log.txt` für den letzten Pipeline-Schritt
5. **Phase-Output**: Prüfe den Inhalt des aktuellen Phase-Ordners (z.B. `01_product_management/`)

Gib eine strukturierte Zusammenfassung des Session-Zustands aus und identifiziere eventuelle Probleme.
