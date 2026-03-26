# AGR Project Overview

AGR (Agentic Governance Runtime) is a drop-in governance layer for AI agents.

## Purpose
AGR evaluates agent actions at runtime before execution. It applies policy rules, deterministic risk scoring, advisory compliance hooks, approval workflows, and audit logging so that sensitive actions are blocked or escalated.

## Core outcomes
- Deny or gate unsafe tool calls before execution
- Require human approval for sensitive actions
- Produce explainable governance decisions
- Record verifiable audit history
- Support integrations across Python and TypeScript ecosystems

## Current platform shape
- `services/agr-api/` — FastAPI control plane and runtime evaluation API
- `packages/agr-core/` — policy engine and execution logic
- `packages/agr-sdk-python/` — Python client SDK and integrations
- `packages/agr-sdk-ts/` — TypeScript client SDK
- `apps/agr-dashboard/` — Angular dashboard for policies, approvals, audit, and settings
- `infra/migrations/` — database schema and operational migrations
- `examples/` — curl, Python, TypeScript demos and policy packs

## Product principles
- Governance at runtime, not only at configuration time
- Policy-first execution
- Deterministic safety controls before model freedom
- Full auditability and traceability
- Enterprise readiness for India and US markets

## What success looks like
A developer can integrate AGR with an agent framework and get policy evaluation, risk scoring, approval routing, compliance visibility, and tamper-evident audit logging without redesigning their entire stack.
