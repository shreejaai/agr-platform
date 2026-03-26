# AGR AI Prompt System

This folder contains the Claude → Qwen orchestration system for development.

## Flow
1. Use planner prompt (Claude)
2. Send output to executor (Qwen/Ollama)
3. Review with Claude
4. Iterate

## Commands (future automation)
- plan
- execute
- review
- fix

## Rules
- Small tasks only
- Deny-by-default logic
- Modular development
- Always review before merge
