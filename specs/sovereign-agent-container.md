# Sovereign Agent Container (SAC)

Status: Draft Specification
Version: 0.1

---

## Abstract

Sovereign Agent Container (SAC) is the sovereignty layer of Efferva.
It is not a platform account, not a cloud profile, not a wallet UI.
It is a user-controlled container that holds Agent state, keys, memory references, and permissions.

---

## Core Objects

### 1. Root Key Material

Root key is the user's sovereignty anchor.

Properties:
- User holds root key (passkey / hardware key)
- Root key binds to SAC
- Root key never stored on any platform
- Root key can derive child keys

Operations:
- `bind(root_key, sac_id)` — bind root key to SAC
- `derive(root_key, purpose)` — derive child key for specific purpose
- `revoke(child_key)` — revoke derived key

### 2. Memory Root

Memory root is an encrypted reference to user's memory store.

Properties:
- Encrypted pointer to memory location
- Memory can be local, self-hosted, or encrypted cloud
- Memory is not uploaded by default
- Memory is exportable in full

Operations:
- `set_memory_root(encrypted_ref)` — set memory root reference
- `get_memory_root()` — retrieve memory root reference
- `export_memory()` — export full memory
- `delete_memory()` — irreversibly delete memory

### 3. Permission Cage

Permission cage defines what Agent can do.

Properties:
- Financial single transaction limit
- Financial daily limit
- Actions requiring confirmation

Operations:
- `check_permission(operation)` — check if operation is allowed

### 4. Recovery Metadata

Recovery metadata is a placeholder for future recovery mechanisms.

Properties:
- Recovery method identifier
- Recovery parameters (opaque)

Operations:
- Not yet specified

### 5. Derived Agents

Derived agents are child agents with limited scope.

Properties:
- Derived from root key
- Independent permission scope
- Can be revoked by parent
- Cannot exceed parent's permissions

Operations:
- `derive_agent(purpose, permissions)` — create derived agent
- `revoke_agent(agent_id)` — revoke derived agent
- `list_agents()` — list all derived agents

---

## SAC Lifecycle

### Creation
1. User generates or imports root key
2. User creates SAC and binds root key
3. User sets memory root
4. User configures permissions
5. User optionally configures recovery

### Usage
1. User authenticates with root key
2. Agent operates within permission cage
3. Agent accesses memory through memory root
4. Agent can derive child agents for specific tasks

### Migration
1. User exports SAC state
2. User imports SAC state to new container
3. User verifies root key binding
4. User continues using Agent

### Recovery
1. User initiates recovery process
2. User provides recovery proof (social recovery, backup key, etc.)
3. System verifies proof
4. System restores SAC state

---

## What SAC Is Not

SAC is not:
- A platform account (no platform required)
- A cloud profile (can be fully local)
- A wallet UI (no built-in transaction interface)
- A blockchain address (no blockchain required)
- An identity system (identity is optional)

---

## Open Questions

- Specific encryption scheme for memory root?
- Specific format for SAC state export?
- Specific protocol for social recovery?
- Specific binding mechanism for hardware keys?

These will be addressed in subsequent RFCs.
