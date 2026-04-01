# Cryovial Roadmap

Cryovial is the first system in the exophial ecosystem to evolve from
a passive deploy gateway into an autonomous edge rhizomorph. This
document traces that arc.

## Current State (v0.2.0)

Cryovial is a webhook listener that executes deploy commands on behalf
of a remote dispatcher. All decision-making happens elsewhere (CI
triggers the webhook, laconic-so manages the cluster). Cryovial's role
is to accept notifications, enforce cooldowns, and shell out.

```
Dispatcher / CI
  |
  | POST /deploy/notify (Bearer auth)
  v
Cryovial (passive gateway)
  +-- services.yml (service -> deployment dir mapping)
  +-- deploy.py (laconic-so wrapper, SHA-tagged images)
  +-- deploy records (YAML, audit trail)
  +-- per-stack cooldown (429 within 5 minutes)
```

The dispatcher decides everything. Cryovial executes commands.

## Target State (edge rhizomorph, exophial v2.0.0)

Cryovial becomes "Rhizomorph A" — a locally autonomous agent that
makes decisions within a constrained action space, communicates with
peers via DIDComm, and holds its own cryptographic identity.

```
Meta-agent (generates packages, bootstraps trust)
  |
  | rhizomorph package (action_library.yaml, system_prompt.md, ...)
  v
Cryovial (autonomous rhizomorph)
  +-- Loads rhizomorph package at startup
  +-- Makes local decisions within action space
  +-- Queries live cluster state via typed READ actions
  +-- Mutates only with capability-gated MUTATE actions
  +-- Escalates when outside its action space
  +-- Optional on-device 1.5B model for intent classification
```

## Migration Phases

### Phase 0: Pellicle (safety scaffolding)

Deploy the hub-spoke access architecture that makes it safe to grant
cryovial more autonomy. Without pellicle, there is no rollback, no
audit trail beyond git, and no filesystem isolation.

Pellicle adds:
- **The Bastion** — SSH session broker with RBAC and full session
  recording (ttyrec). Protocol break between ingress and egress.
- **step-ca** — SSH Certificate Authority anchored to a Yubikey.
  Replaces `authorized_keys` with short-lived certificates.
- **AgentFS** — FUSE-based copy-on-write overlay on spoke hosts.
  Every agent write goes to a SQLite delta; the host filesystem is
  never directly modified. Reversible with `agentfs prune`.

Pellicle is temporary scaffolding. Its job is done when the action
space is narrow enough that AgentFS deltas are auto-committed.

See: `exophial/docs/v2.0.0/PELLICLE.md`

### Phase 1: Rhizomorph package format

Define the deployable artifact that replaces cryovial's hardcoded
behavior:

| Current cryovial | Rhizomorph package |
|---|---|
| `services.yml` | `action_library.yaml` (typed, categorized, safety-classified) |
| Implicit cluster knowledge | `system_prompt.md` + `rag_index/` (generated from live state) |
| No pre-deploy validation | `validation_suite/` (gates deployment) |
| No model | `archetype.gguf` (optional fine-tuned 1.5B) |

The action library categorizes operations by trust level:
- **READ** — no credential beyond rhizomorph identity
- **PLAN** — read-only simulation (dry-run, helm diff)
- **MUTATE** — requires specific capability in identity record
- **ROLLBACK** — requires specific capability
- **ESCALATE** — always permitted (safety valve)

See: `exophial/docs/v2.0.0/RHIZOMORPH_PACKAGE.md`

### Phase 2: Meta-agent as package generator

The exophial meta-agent (v1.0.0 planner + spec tool) learns to
generate rhizomorph packages from cluster state + user intent. It
ingests kubectl output, git manifests, and CRDs, then produces a
validated package.

Package updates are triggered by git push, drift detection, or
scheduled resync (default: every 6 hours).

### Phase 3: Laconicd identity layer

Replace SSH key authentication with laconicd identity records.
Each rhizomorph gets an `ExophialRhizomorph` record with:
- LRN naming (`lrn://exophial/rz/cryovial-woodburn-001`)
- Capability encoding in record attributes
- Bond-based credential lifecycle (automatic expiry)

### Phase 4: DIDComm transport

Replace SSH tunnels with DIDComm v2 for inter-rhizomorph
communication. Rhizomorphs discover each other via laconicd and
negotiate directly.

### Phase 5: Payment primitives

Nitro state channels for inter-rhizomorph micropayments. Economic
coordination between autonomous agents.

### Phase 6: On-device inference

LoRA-tuned 1.5B model (Qwen2.5-Coder) running locally via MLC LLM
for intent classification and action selection within the constrained
domain. Training data comes from the v1.0.0 learning loop.

## What Doesn't Change

- **Ansible bootstraps hosts.** Docker, kind, kubectl, cluster
  creation — Ansible keeps this job.
- **laconic-so manages the cluster.** Cryovial delegates k8s
  operations to laconic-so today and will continue to do so through
  the action library abstraction.
- **kind is the interface boundary.** Every target runs kind.
  Rhizomorphs interact with kubectl.

## Design Sources

- `exophial/docs/v2.0.0/PLAN.md` — full v2.0.0 plan
- `exophial/docs/v2.0.0/PELLICLE.md` — agent access architecture
- `exophial/docs/v2.0.0/RHIZOMORPH_PACKAGE.md` — package format spec
- `exophial/docs/v2.0.0/IDENTITY_AND_TRUST.md` — credential migration
- `exophial/docs/v2.0.0/PAYMENT.md` — payment primitives
- `exophial/docs/v2.0.0/INFERENCE.md` — on-device model strategy
