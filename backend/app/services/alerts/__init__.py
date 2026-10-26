"""Alert engine: threshold, state, missing-data, event and compliance rules (design doc "Alerting").

- `evaluate.evaluate_server`: threshold, state and event rules for one server (after each batch)
- `missing.check_servers` / `missing.check_collectors`: missing data (scheduled every 30 s)
- `escalation.escalate_due`: 15-minute Critical escalation (scheduled)
- `app.services.firmware.run_compliance`: daily firmware compliance
- `evaluate.resolve_stale_events`: event alerts auto-resolve 24 h after the last occurrence

All of them write through `store.AlertStore` and collect side effects in `effects.Effects`, applied after
commit.
"""
