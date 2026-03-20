# Compatibility Layer

Status: Draft Specification
Version: 0.1

---

## Abstract

Compatibility Layer lets Web4.0 Agents call existing systems.
It is not a core layer. It is a compatibility layer.

Old systems are resource layers, not sovereignty layers.

---

## Scope

Compatibility Layer handles:
- Websites / HTML
- Existing APIs (REST, GraphQL, etc.)
- Legacy auth (OAuth, SAML, API keys, etc.)
- Cloud runtimes (AWS, GCP, Azure, etc.)
- Payment rails (credit cards, bank transfers, etc.)
- App ecosystems (iOS, Android, web apps, etc.)

Compatibility Layer does not handle:
- Agent sovereignty (handled by SAC)
- Intent parsing (handled by IIP)
- Compute allocation (handled by OCI)
- Intelligence federation (handled by FIL)

---

## Design Principle

Old world can be called.
Old world cannot be required.

Agents must be able to function without old systems.
Old systems are optional resources, not mandatory dependencies.

---

## Compatibility Targets

### 1. Websites / HTML

Agents can:
- Fetch web pages
- Parse HTML
- Extract structured data
- Submit forms
- Handle cookies and sessions

Agents cannot:
- Require browser to function
- Depend on JavaScript execution for core operations
- Store state only in browser

### 2. Existing APIs

Agents can:
- Call REST APIs
- Call GraphQL APIs
- Call RPC APIs
- Handle API authentication (OAuth, API keys, etc.)
- Parse API responses

Agents cannot:
- Require specific API to function
- Depend on single API provider for core operations
- Store state only in API provider's system

### 3. Legacy Auth

Agents can:
- Use OAuth for delegated authorization
- Use SAML for enterprise SSO
- Use API keys for service access
- Store credentials securely in SAC

Agents cannot:
- Require platform identity to function
- Depend on OAuth provider for Agent sovereignty
- Expose root key to legacy auth systems

### 4. Cloud Runtimes

Agents can:
- Run on AWS, GCP, Azure, etc.
- Use cloud storage (S3, GCS, etc.)
- Use cloud compute (Lambda, Cloud Functions, etc.)
- Use cloud databases (RDS, Firestore, etc.)

Agents cannot:
- Require specific cloud provider to function
- Store SAC state only in cloud
- Depend on cloud provider for Agent sovereignty

### 5. Payment Rails

Agents can:
- Use credit cards
- Use bank transfers
- Use PayPal, Stripe, etc.
- Use existing payment APIs

Agents cannot:
- Require specific payment provider to function
- Depend on payment provider for Agent sovereignty
- Store payment credentials outside SAC

### 6. App Ecosystems

Agents can:
- Run as iOS apps
- Run as Android apps
- Run as web apps
- Use app store distribution

Agents cannot:
- Require app store to function
- Depend on app store for Agent sovereignty
- Store SAC state only in app sandbox

---

## Open Questions

- Specific adapter interface?
- Specific credential storage format?
- Specific error handling strategy?
- Specific retry logic?

These will be addressed in subsequent RFCs.
