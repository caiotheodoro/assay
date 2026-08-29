# Trajectory — sandbox approval gate

**Role:** human_checkpoint  
**Environment:** `harbor/self-graded`  
**Task:** `self-graded`

**What this shows:** **the human checkpoint.** The identical request is put to two approvers: the default refuses and nothing runs, an explicit standing approval carrying a reason lets it through. Nothing in Assay executes untrusted environment code without one of these.

## What the agent was told

> Assay has to run third-party gold solutions, verifier scripts and adversarial policies. Containment is Docker with the network off and a read-only root; the other half is a human who has to say yes.

## Turns

### Turn 1

_the default approver. An unattended Assay executes nothing._

```json
{"approver":"DenyAll","ask_human_to_approve":{"command":["sh","-c","cat expected.txt"],"image":"alpine:3.20","limits":{"cpus":1.0,"memory":"512m","pids":128,"read_only_root":true,"wall_seconds":120},"mounts":[{"read_only":true,"source":"src/assay/fixtures/harbor_suite/self-graded/environment","target":"/work"}],"network":"off"}}
```

Tool responded: `ApprovalDenied: execution of 'sh -c cat expected.txt' in alpine:3.20 was not approved; nothing ran — requests recorded as approved: 0`

### Turn 2

_explicit standing approval, carrying a reason. An approval nobody can account for later is the same as no approval._

```json
{"approver":"AutoApprove('standing approval for the trajectory export')","ask_human_to_approve":{"command":["sh","-c","cat expected.txt"],"image":"alpine:3.20","limits":{"cpus":1.0,"memory":"512m","pids":128,"read_only_root":true,"wall_seconds":120},"mounts":[{"read_only":true,"source":"src/assay/fixtures/harbor_suite/self-graded/environment","target":"/work"}],"network":"off"}}
```

Tool responded: `approved and executed: exit 0, stdout '42'`

## Human checkpoints

- execute untrusted environment code in alpine:3.20 — the default approver. An unattended Assay executes nothing. — ApprovalDenied: execution of 'sh -c cat expected.txt' in alpine:3.20 was not approved; nothing ran — requests recorded as approved: 0
  - asked `DenyAll` → **REFUSED — nothing ran**

```json
{"command":["sh","-c","cat expected.txt"],"image":"alpine:3.20","limits":{"cpus":1.0,"memory":"512m","pids":128,"read_only_root":true,"wall_seconds":120},"mounts":[{"read_only":true,"source":"src/assay/fixtures/harbor_suite/self-graded/environment","target":"/work"}],"network":"off"}
```

- execute untrusted environment code in alpine:3.20 — explicit standing approval, carrying a reason. An approval nobody can account for later is the same as no approval. — approved and executed: exit 0, stdout '42'
  - asked `AutoApprove('standing approval for the trajectory export')` → **APPROVED**

```json
{"command":["sh","-c","cat expected.txt"],"image":"alpine:3.20","limits":{"cpus":1.0,"memory":"512m","pids":128,"read_only_root":true,"wall_seconds":120},"mounts":[{"read_only":true,"source":"src/assay/fixtures/harbor_suite/self-graded/environment","target":"/work"}],"network":"off"}
```


## Outcome

```json
{"default_approver":"DenyAll \u2014 an unattended Assay executes nothing","executed_without_approval":0,"granted":1,"refused":1,"requests":2}
```
