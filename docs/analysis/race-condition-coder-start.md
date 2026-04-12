# Root-Cause-Analyse: Race-Condition beim Coder-Start nach `submit_plan`

## Symptom

Nachdem der Planner `submit_plan` aufruft, werden **zwei Coder-Panes** erstellt statt einem.
Der erste Pane (`%5`) wird im tmux-Layout verloren, der zweite Pane (`%6`) bleibt versteckt —
der Coder startet scheinbar nicht.

**Beleg aus `orchestrator.log`:**
- Zwei `_spawn_hidden_pane: starting 'coder'` Einträge im Abstand von ~3 ms
- Zwei `ContentZone.show: swap for coder pane` Aufrufe (957 ms vs. 960 ms)
- Zwei `_wait_for_pane_ready` Logs für `%5` und `%6`
- Log-Zeilen ohne Newline (zwei Threads schreiben gleichzeitig)
- `runtime_state.json` zeigt `coder: "%5"`, aber `%5` existiert nicht mehr im tmux

## Architektur

Der Orchestrator nutzt drei Event-Quellen auf einem gemeinsamen `EventBus`:

```
┌─────────────────────┐     ┌──────────────┐     ┌─────────────────────────┐
│  FileEventSource    │     │              │     │ PipelineOrchestrator    │
│  (watchdog-Thread)  │────▶│  EventBus    │────▶│  ._on_event()           │
└─────────────────────┘     │  .publish()  │     │    ↓                     │
                            │              │     │  router.handle()         │
┌─────────────────────┐     │              │     │    ↓                     │
│ ToolCallEventSource │────▶│              │     │  _dispatch()             │
│  (watchdog-Thread)  │     │              │     │    ↓                     │
└─────────────────────┘     └──────────────┘     │  handler.handle_event() │
                                                 └─────────────────────────┘
```

- **`FileEventSource`** überwacht das Feature-Directory mit `watchdog` (eigener Thread)
- **`ToolCallEventSource`** tailt `tool_events.jsonl` mit `watchdog` (eigener Thread)
- Beide können **parallel** `bus.publish()` aufrufen → `EventBus` ruft Listener **ohne Synchronisation** auf

## Detaillierter Ablauf der Race-Condition

### Ausgangssituation

Phase ist `"planning"`, der Planner arbeitet. `WorkflowEventRouter._entered` enthält `"planning"`.

### Sequenz der Ereignisse

```
Zeit    Thread A (ToolCallEventSource)          Thread B (FileEventSource)
────    ──────────────────────────────          ──────────────────────────
T0      tool.submit_plan Event einlesen
        → bus.publish(SessionEvent("tool.submit_plan"))
          → _on_event(event)
            → router.handle(event, state, ctx)
              → _dispatch(): match submit_plan
              → PlanningHandler._handle_plan()
                → kill planner
                → return (updates, "implementing")  ← Phasenwechsel!

T1      state["phase"] = "implementing"
        state["last_event"] = "plan_written"
        _entered.discard("planning")
        write_state(state)

T2      → rekursiv: handle(event, state, ctx)
          → phase_name = "implementing"
          → "implementing" not in _entered → True
            → enter_current_phase(state, ctx)
              → ImplementingHandler.enter(state, ctx)
                → send_prompt("coder", ...)
                  → _spawn_hidden_pane() → Pane %5
                  → _wait_for_pane_ready(%5)
                    → time.sleep(0.5)  ← SCHLÄFT!

T3                                                  write_prompt_file() schreibt
                                                    coder_prompt_1.md

T4                                                  watchdog erkennt neue Datei
                                                    → bus.publish(SessionEvent("file.created"))
                                                      → _on_event(event)
                                                        → router.handle(event, state, ctx)

T5                                                        phase_name = "implementing"
        (schläft noch)                                    "implementing" not in _entered → TRUE!
                                                          (Thread A hat _entered.add() noch
                                                           NICHT aufgerufen — er steckt in
                                                           enter() und schläft!)

T6                                                        enter_current_phase(state, ctx)
                                                          → ImplementingHandler.enter(state, ctx)
                                                            → _spawn_hidden_pane() → Pane %6
                                                            → ContentZone.show für %6

T7      wacht auf
        → _entered.add("implementing")  ← ZU SPÄT!
        → Pane %5 wurde erstellt, aber
          Pane %6 hat ihn im Layout
          überschrieben
```

## Root Cause: TOCTOU in `enter_current_phase`

```python
# src/agentmux/workflow/event_router.py

def enter_current_phase(self, state: dict, ctx: PipelineContext) -> dict:
    phase_name = state.get("phase", "")
    handler = self._phases.get(phase_name)
    if handler is None or phase_name in self._entered:  # ← CHECK (Time)
        return {}

    enter_updates = handler.enter(state, ctx)           # ← CHECK (Time of Use)
    state.update(enter_updates)
    self._entered.add(phase_name)                       # ← HIER wäre der Schutz
    ...
```

**Das Problem:** `handler.enter()` ist eine **lange Operation** (send_prompt, Pane-Erstellung,
sleeps). Erst NACH `enter()` wird `_entered.add()` aufgerufen. In diesem Fenster kann ein
zweiter Thread den Check `phase_name in self._entered` passieren.

## Warum ein File-Event beteiligt ist

`ImplementingHandler.enter()` schreibt über `write_prompt_file()` die Datei
`coder_prompt_N.md`. Der `watchdog`-Thread von `FileEventSource` erkennt diese Datei und
publiziert ein `file.created` Event. Dieses Event trifft auf den Router in einem Zustand,
in dem `state["phase"]` schon `"implementing"` ist, aber `_entered` noch nicht.

Das File-Event selbst hat keine Logik die einen Coder startet — es wird von
`BaseToolHandler.handle_event()` ignoriert (kein Tool-Name matcht). Aber es tritt durch
`router.handle()` → `enter_current_phase()` die Race-Condition los.

## Warum FileEventSource nicht entfernt werden kann

Drei Handler benötigen weiterhin File-Events:

| Handler | File-Event für | Datei |
|---|---|---|
| `DesigningHandler` | `design_written` | `05_design/design.md` |
| `ReviewingHandler` | `summary_ready` | `08_completion/summary.md` |
| `CompletingHandler` | `approval_received`, `changes_requested` | `08_completion/approval.json`, `changes.md` |

## Lösung: `_entered.add()` vor `handler.enter()` verschieben

```python
def enter_current_phase(self, state: dict, ctx: PipelineContext) -> dict:
    phase_name = state.get("phase", "")
    handler = self._phases.get(phase_name)
    if handler is None or phase_name in self._entered:
        return {}

    self._entered.add(phase_name)  # ← VOR enter() — kein TOCTOU-Fenster mehr
    enter_updates = handler.enter(state, ctx)
    state.update(enter_updates)
    ...
```

**Warum das reicht:** Sobald ein Thread den Check passiert hat und `_entered.add()` aufruft,
sieht jeder andere Thread sofort `phase_name in self._entered` → `True` und überspringt
`enter_current_phase` komplett. Das Zeitfenster zwischen Check und Markierung verschwindet.

## Alternative (verworfen): Lock in `_on_event`

Ein `threading.Lock` um die gesamte `_on_event`-Methode würde ebenfalls funktionieren,
aber:
- Deutlich breiterer Eingriff (serialisiert ALLE Event-Verarbeitung)
- File-Events müssten auf Tool-Events warten und umgekehrt
- Overkill für das eigentliche Problem (nur `_entered` ist betroffen)

Der `_entered.add()`-vor-`enter()`-Fix ist minimal, gezielt und löst die spezifische
Race-Condition mit einer 1-Zeilen-Änderung.

## Dateien

| Datei | Rolle |
|---|---|
| `src/agentmux/workflow/event_router.py` | `enter_current_phase()` — hier der Fix |
| `src/agentmux/workflow/orchestrator.py` | `_on_event()` — ruft `router.handle()` auf |
| `src/agentmux/workflow/handlers/implementing.py` | `enter()` — erstellt Coder-Panes |
| `src/agentmux/runtime/file_events.py` | `FileEventSource` — watchdog-Thread |
| `src/agentmux/runtime/tool_events.py` | `ToolCallEventSource` — watchdog-Thread |
| `src/agentmux/runtime/event_bus.py` | `EventBus.publish()` — ruft Listener ohne Lock auf |

## Tests

- `tests/workflow/test_event_router.py` — Router-Tests
- `tests/workflow/test_orchestrator_refactor.py` — Orchestrator-Tests
- `tests/workflow/handlers/test_tool_event_migration.py` — Handler-Tests
