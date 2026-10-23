"""Dynamic multi-BMC Redfish simulator (`gcc-bmc-simulator`).

One process serves N virtual BMCs, one port each (DECISIONS.md D27). Each BMC renders its resources from a
`ServerState` with the same tree builders as the static mockups, so the paths match the static trees; the
state drifts every few seconds and faults can be injected at random or through the control API.

Modules: `config` (environment), `physics` (drift), `faults` (fault kinds and their effects), `bmc` (one
virtual BMC), `redfish` (the BMC HTTP app: auth, sessions, $expand), `control` (control API and Teams
webhook sink), `fleet` (all BMCs, the drift loop, random faults), `app` (entry point).
"""
