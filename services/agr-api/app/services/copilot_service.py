"""
Copilot service — LLM-powered governance assistant.
Handles intent classification, LLM calls, DB operations, and response formatting.
"""

import json
import logging
import re
import secrets
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import (
    Agent,
    CopilotConversation,
    CopilotMessageRecord,
    Organization,
    Policy,
    Webhook,
)
from app.schemas import (
    CopilotMessage,
    CopilotPreview,
    CopilotResponse,
)
from app.services.copilot_prompts import (
    AGENT_REGISTRATION_SYSTEM_PROMPT,
    EXPLANATION_SYSTEM_PROMPT,
    GENERAL_SYSTEM_PROMPT,
    POLICY_GENERATION_SYSTEM_PROMPT,
)
from app.services.redis_service import (
    get_conversation_cache,
    set_conversation_cache,
)

logger = logging.getLogger(__name__)

# Sample policies for the "sample" intent
_SAMPLE_POLICIES: list[dict[str, str]] = [
    {
        "name": "block_production_deploys",
        "description": "Block all deploys to production environment",
        "cedar_rule": (
            'forbid(principal, action == Action::"deploy", resource)\n'
            'when { context has "environment" && context.environment == "production" };'
        ),
    },
    {
        "name": "require_approval_for_fund_transfers",
        "description": "Require human approval before transferring funds over $10,000",
        "cedar_rule": (
            'forbid(principal, action == Action::"transfer_funds", resource)\n'
            'unless { context has "approval_status"'
            ' && context.approval_status == "approved" }\n'
            'when { context has "amount" && context.amount > 10000 };'
        ),
    },
    {
        "name": "block_env_file_writes",
        "description": "Block writes to .env and secrets files",
        "cedar_rule": (
            'forbid(principal, action in [Action::"fs.write", Action::"fs.delete"], resource)\n'
            'when { context has "path"'
            ' && (context.path like "*.env*" || context.path like "*secrets*") };'
        ),
    },
    {
        "name": "allow_staging_deploys",
        "description": "Allow deploys to staging environment",
        "cedar_rule": (
            'permit(principal, action == Action::"deploy", resource)\n'
            'when { context has "environment" && context.environment == "staging" };'
        ),
    },
    {
        "name": "block_production_db_drops",
        "description": "Block DROP and TRUNCATE in production",
        "cedar_rule": (
            'forbid(principal, action in [Action::"db.drop", Action::"db.truncate"], resource)\n'
            'when { context has "environment" && context.environment == "production" };'
        ),
    },
]


class CopilotService:
    def __init__(
        self,
        session: AsyncSession,
        org_id: uuid.UUID,
        org: Organization,
    ) -> None:
        self.session = session
        self.org_id = org_id
        self.org = org

    # ──────────────────────────────────────────────────────────────────────────
    # Public entry point
    # ──────────────────────────────────────────────────────────────────────────

    async def handle_message(
        self,
        message: str,
        conversation_id: str | None,
        auto_confirm: bool = False,
        confirm_preview: dict | None = None,
    ) -> CopilotResponse:
        """Route the user message to the appropriate handler."""
        if not settings.copilot_enabled or not settings.anthropic_api_key:
            return CopilotResponse(
                message=(
                    "The AGR Copilot is not configured. "
                    "Set ANTHROPIC_API_KEY to enable AI-powered governance assistance."
                ),
                action_type="error",
                conversation_id="",
                suggestions=["Contact your administrator to enable the Copilot"],
            )

        # ── Confirm using already-generated preview (no LLM re-call) ─────────
        # When the user clicks "Confirm", the frontend sends back the preview
        # data so we can create the resource directly without calling Claude.
        if auto_confirm and confirm_preview:
            conv = await self._get_or_create_conversation(conversation_id)
            resource_type = confirm_preview.get("resource_type")
            data = confirm_preview.get("data", {})
            if resource_type == "policy":
                response = await self._create_policy_confirmed(
                    name=data.get("name", "policy"),
                    cedar_rule=confirm_preview.get("cedar_rule") or data.get("cedar_rule", ""),
                    level=data.get("level", "org"),
                    description=data.get("description", ""),
                )
            elif resource_type == "agent":
                response = await self._register_agent_confirmed(
                    agent_id=data.get("agent_id", ""),
                    metadata=data.get("metadata", {}),
                )
            elif resource_type == "webhook":
                response = await self._create_webhook_confirmed(url=data.get("url", ""))
            else:
                response = CopilotResponse(
                    message="Unknown resource type in preview.",
                    action_type="error",
                    conversation_id="",
                )
            await self._save_messages(conv, message, response)
            response.conversation_id = str(conv.id)
            return response

        # ── Get or create conversation ────────────────────────────────────────
        conv = await self._get_or_create_conversation(conversation_id)
        conv_id_str = str(conv.id)

        # ── Load history from Redis → DB fallback ────────────────────────────
        history = await self._load_history(conv)

        # ── Classify and dispatch ─────────────────────────────────────────────
        intent = self._classify_intent(message)
        logger.debug("Copilot intent: %s for message: %.80s", intent, message)

        if intent == "list_policies":
            response = await self._handle_list_policies()
        elif intent == "list_agents":
            response = await self._handle_list_agents()
        elif intent == "list_webhooks":
            response = await self._handle_list_webhooks()
        elif intent == "sample":
            response = self._handle_sample()
        elif intent == "create_policy":
            response = await self._handle_create_policy(message, auto_confirm)
        elif intent == "register_agent":
            response = await self._handle_register_agent(message, auto_confirm)
        elif intent == "create_webhook":
            response = await self._handle_create_webhook(message, auto_confirm)
        elif intent == "explain":
            response = await self._handle_explain(message, history)
        else:
            response = await self._handle_general(message, history)

        # ── Persist user + assistant messages ────────────────────────────────
        await self._save_messages(conv, message, response)
        response.conversation_id = conv_id_str
        return response

    # ── Conversation persistence helpers ─────────────────────────────────────

    async def _get_or_create_conversation(self, conversation_id: str | None) -> CopilotConversation:
        """Return an existing conversation or create a new one."""
        if conversation_id:
            result = await self.session.execute(
                select(CopilotConversation).where(
                    CopilotConversation.id == uuid.UUID(conversation_id),
                    CopilotConversation.org_id == self.org_id,
                )
            )
            conv = result.scalar_one_or_none()
            if conv:
                return conv
        # Create new
        conv = CopilotConversation(
            id=uuid.uuid4(),
            org_id=self.org_id,
            title="New conversation",
            message_count=0,
        )
        self.session.add(conv)
        await self.session.flush()
        return conv

    async def _load_history(self, conv: CopilotConversation) -> list[CopilotMessage]:
        """Load conversation history: Redis first, DB fallback."""
        conv_id_str = str(conv.id)

        cached = await get_conversation_cache(conv_id_str)
        if cached is not None:
            return [CopilotMessage(role=m["role"], content=m["content"]) for m in cached]

        # DB fallback — load last 20 messages
        result = await self.session.execute(
            select(CopilotMessageRecord)
            .where(CopilotMessageRecord.conversation_id == conv.id)
            .order_by(CopilotMessageRecord.created_at.asc())
            .limit(20)
        )
        db_msgs = result.scalars().all()
        history = [
            CopilotMessage(
                role="user" if m.role == "user" else "assistant",
                content=m.content,
            )
            for m in db_msgs
        ]

        # Warm the cache
        await set_conversation_cache(
            conv_id_str, [{"role": m.role, "content": m.content} for m in history]
        )
        return history

    async def _save_messages(
        self,
        conv: CopilotConversation,
        user_message: str,
        response: CopilotResponse,
    ) -> None:
        """Persist user + assistant messages and update conversation metadata."""
        # Derive title from first user message (truncated to 60 chars)
        if conv.message_count == 0:
            conv.title = user_message[:60] + ("…" if len(user_message) > 60 else "")

        user_record = CopilotMessageRecord(
            id=uuid.uuid4(),
            conversation_id=conv.id,
            org_id=self.org_id,
            role="user",
            content=user_message,
        )
        assistant_record = CopilotMessageRecord(
            id=uuid.uuid4(),
            conversation_id=conv.id,
            org_id=self.org_id,
            role="assistant",
            content=response.message,
            action_type=response.action_type,
            msg_metadata={
                k: v
                for k, v in {
                    "preview": response.preview.model_dump() if response.preview else None,
                    "created_resource": response.created_resource,
                    "suggestions": response.suggestions,
                }.items()
                if v is not None
            }
            or None,
        )

        self.session.add(user_record)
        self.session.add(assistant_record)
        conv.message_count += 2
        await self.session.flush()

        # Update Redis cache — append new messages
        conv_id_str = str(conv.id)
        cached = await get_conversation_cache(conv_id_str) or []
        cached.extend(
            [
                {"role": "user", "content": user_message},
                {"role": "assistant", "content": response.message},
            ]
        )
        # Keep last 20 messages in cache
        await set_conversation_cache(conv_id_str, cached[-20:])

    # ──────────────────────────────────────────────────────────────────────────
    # Intent classification (keyword-based, no LLM call needed)
    # ──────────────────────────────────────────────────────────────────────────

    def _classify_intent(self, message: str) -> str:
        """Classify user intent from message text using keyword heuristics."""
        lower = message.lower()

        # Strip URLs early so "example.com" / "https://example.com/..." never
        # trigger the sample-keyword check below.
        lower_no_urls = re.sub(r"https?://\S+", "", lower)

        # Sample / example intent — checked FIRST so "show me sample policies"
        # or "give me an example policy" wins before list/create heuristics.
        if re.search(r"\b(sample|example|template|demo|starter)\b", lower_no_urls):
            return "sample"

        # List intents
        if re.search(r"\b(list|show|get|fetch|display)\b", lower):
            if "polic" in lower:
                return "list_policies"
            if "agent" in lower:
                return "list_agents"
            if "webhook" in lower:
                return "list_webhooks"

        # Explain intents
        if re.search(r"\b(explain|what is|what are|how does|describe|tell me about)\b", lower):
            return "explain"

        # Create / register intents
        if re.search(r"\b(create|add|make|generate|build|write)\b", lower):
            if "webhook" in lower:
                return "create_webhook"
            if "agent" in lower:
                return "register_agent"
            return "create_policy"

        if re.search(r"\b(register)\b", lower):
            if "webhook" in lower:
                return "create_webhook"
            return "register_agent"

        if "webhook" in lower and re.search(r"https?://", lower):
            return "create_webhook"

        # Policy intents with governance keywords
        if re.search(
            r"\b(block|forbid|deny|prevent|allow|permit|require approval|policy|rule|cedar)\b",
            lower,
        ):
            return "create_policy"

        return "general"

    # ──────────────────────────────────────────────────────────────────────────
    # List handlers (no LLM needed)
    # ──────────────────────────────────────────────────────────────────────────

    async def _handle_list_policies(self) -> CopilotResponse:
        result = await self.session.execute(
            select(Policy)
            .where(Policy.org_id == self.org_id, Policy.active == True)  # noqa: E712
            .order_by(Policy.created_at.desc())
            .limit(20)
        )
        policies = result.scalars().all()

        if not policies:
            return CopilotResponse(
                message="You have no active policies yet.",
                action_type="list_policies",
                suggestions=[
                    "Create a policy that blocks production deploys",
                    "Show me sample policies",
                    "Create a policy requiring approval for fund transfers",
                ],
            )

        lines = [f"You have {len(policies)} active policy/policies:\n"]
        for p in policies:
            lines.append(f"- **{p.name}** (level: {p.level})")
        lines.append("\nSay 'create a policy that...' to add a new one.")

        return CopilotResponse(
            message="\n".join(lines),
            action_type="list_policies",
            suggestions=["Create a new policy", "Show sample policies"],
        )

    async def _handle_list_agents(self) -> CopilotResponse:
        result = await self.session.execute(
            select(Agent)
            .where(Agent.org_id == self.org_id, Agent.active == True)  # noqa: E712
            .order_by(Agent.created_at.desc())
            .limit(20)
        )
        agents = result.scalars().all()

        if not agents:
            return CopilotResponse(
                message="No agents registered yet.",
                action_type="list_agents",
                suggestions=[
                    "Register an agent called my-finance-agent",
                    "Register a LangGraph agent",
                ],
            )

        lines = [f"You have {len(agents)} registered agent(s):\n"]
        for a in agents:
            meta = a.agent_metadata or {}
            name = meta.get("name", a.agent_id)
            framework = meta.get("framework", "unknown")
            lines.append(f"- **{name}** (id: `{a.agent_id}`, framework: {framework})")

        return CopilotResponse(
            message="\n".join(lines),
            action_type="list_agents",
            suggestions=["Register a new agent", "Create a policy for an agent"],
        )

    async def _handle_list_webhooks(self) -> CopilotResponse:
        result = await self.session.execute(
            select(Webhook)
            .where(Webhook.org_id == self.org_id, Webhook.active == True)  # noqa: E712
            .order_by(Webhook.created_at.desc())
            .limit(20)
        )
        webhooks = result.scalars().all()

        if not webhooks:
            return CopilotResponse(
                message="No webhooks configured yet.",
                action_type="list_webhooks",
                suggestions=[
                    "Create a webhook for https://example.com/agr-events",
                ],
            )

        lines = [f"You have {len(webhooks)} active webhook(s):\n"]
        for wh in webhooks:
            events = ", ".join(wh.events) if wh.events else "none"
            lines.append(f"- `{wh.url}` (events: {events})")

        return CopilotResponse(
            message="\n".join(lines),
            action_type="list_webhooks",
            suggestions=["Create a new webhook", "List approval events"],
        )

    # ──────────────────────────────────────────────────────────────────────────
    # Sample handler
    # ──────────────────────────────────────────────────────────────────────────

    def _handle_sample(self) -> CopilotResponse:
        lines = ["Here are some sample policies to get you started:\n"]
        for sp in _SAMPLE_POLICIES:
            lines.append(f"**{sp['name']}** — {sp['description']}")
            lines.append(f"```\n{sp['cedar_rule']}\n```\n")

        lines.append(
            'Say "create a policy that..." to generate a custom policy '
            "or pick one of the samples above."
        )

        return CopilotResponse(
            message="\n".join(lines),
            action_type="sample",
            suggestions=[
                "Create a policy that blocks production deploys",
                "Create a policy requiring approval for fund transfers over $10,000",
                "Create a policy that blocks .env file writes",
            ],
        )

    # ──────────────────────────────────────────────────────────────────────────
    # Create policy handler
    # ──────────────────────────────────────────────────────────────────────────

    async def _handle_create_policy(self, message: str, auto_confirm: bool) -> CopilotResponse:
        llm_response = await self._call_llm(
            system_prompt=POLICY_GENERATION_SYSTEM_PROMPT,
            user_message=message,
        )

        parsed = self._parse_json_response(llm_response)
        if parsed is None:
            return CopilotResponse(
                message=(
                    "I couldn't generate a valid policy from your description. "
                    "Try being more specific, e.g. "
                    "'create a policy that blocks deploys to production'."
                ),
                action_type="error",
                suggestions=[
                    "Create a policy that blocks production deploys",
                    "Show sample policies",
                ],
            )

        name = parsed.get("name", "generated_policy")
        cedar_rule = parsed.get("cedar_rule", "")
        description = parsed.get("description", "")
        level = parsed.get("level", "org")

        if not cedar_rule:
            return CopilotResponse(
                message="I couldn't generate a valid Cedar rule. Please try rephrasing.",
                action_type="error",
                suggestions=["Show sample policies"],
            )

        if auto_confirm:
            return await self._create_policy_confirmed(
                name=name, cedar_rule=cedar_rule, level=level, description=description
            )

        preview = CopilotPreview(
            resource_type="policy",
            data={"name": name, "level": level, "description": description},
            cedar_rule=cedar_rule,
            confirmation_prompt=(
                f"Create policy **{name}**?\n\n"
                f"```\n{cedar_rule}\n```\n\n"
                "Reply with **yes** to confirm or **no** to cancel."
            ),
        )

        return CopilotResponse(
            message=(
                f"I've generated a Cedar policy for you:\n\n"
                f"**{name}** — {description}\n\n"
                f"```\n{cedar_rule}\n```\n\n"
                "Would you like me to create this policy? Reply **yes** to confirm."
            ),
            action_type="create_policy",
            preview=preview,
            suggestions=["yes", "no", "modify the policy"],
        )

    async def _create_policy_confirmed(
        self, name: str, cedar_rule: str, level: str, description: str
    ) -> CopilotResponse:
        policy = Policy(
            id=uuid.uuid4(),
            org_id=self.org_id,
            name=name,
            level=level,
            cedar_rule=cedar_rule,
            active=True,
        )
        self.session.add(policy)
        await self.session.flush()
        await self.session.refresh(policy)

        return CopilotResponse(
            message=f"Policy **{name}** has been created successfully.",
            action_type="confirmed",
            created_resource={
                "id": str(policy.id),
                "name": policy.name,
                "level": policy.level,
                "cedar_rule": policy.cedar_rule,
                "active": policy.active,
            },
            suggestions=["List all policies", "Create another policy", "Register an agent"],
        )

    # ──────────────────────────────────────────────────────────────────────────
    # Register agent handler
    # ──────────────────────────────────────────────────────────────────────────

    async def _handle_register_agent(self, message: str, auto_confirm: bool) -> CopilotResponse:
        llm_response = await self._call_llm(
            system_prompt=AGENT_REGISTRATION_SYSTEM_PROMPT,
            user_message=message,
        )

        parsed = self._parse_json_response(llm_response)
        if parsed is None:
            return CopilotResponse(
                message=(
                    "I couldn't extract agent details from your message. "
                    "Try: 'Register an agent called my-agent that uses LangGraph'."
                ),
                action_type="error",
                suggestions=["Register an agent called my-finance-agent"],
            )

        agent_id = parsed.get("agent_id", "")
        metadata: dict[str, Any] = parsed.get("metadata", {})

        if not agent_id:
            return CopilotResponse(
                message="I couldn't determine an agent ID. Please specify a name for the agent.",
                action_type="error",
                suggestions=["Register an agent called my-agent"],
            )

        if auto_confirm:
            return await self._register_agent_confirmed(agent_id=agent_id, metadata=metadata)

        name = metadata.get("name", agent_id)
        framework = metadata.get("framework", "unknown")

        preview = CopilotPreview(
            resource_type="agent",
            data={"agent_id": agent_id, "metadata": metadata},
            confirmation_prompt=(
                f"Register agent **{name}** (id: `{agent_id}`, framework: {framework})?\n\n"
                "Reply **yes** to confirm."
            ),
        )

        return CopilotResponse(
            message=(
                f"I'll register the following agent:\n\n"
                f"- **ID**: `{agent_id}`\n"
                f"- **Name**: {name}\n"
                f"- **Framework**: {framework}\n\n"
                "Reply **yes** to confirm."
            ),
            action_type="register_agent",
            preview=preview,
            suggestions=["yes", "no"],
        )

    async def _register_agent_confirmed(
        self, agent_id: str, metadata: dict[str, Any]
    ) -> CopilotResponse:
        # Upsert — same pattern as the agents route
        result = await self.session.execute(
            select(Agent).where(
                Agent.org_id == self.org_id,
                Agent.agent_id == agent_id,
            )
        )
        agent = result.scalar_one_or_none()

        if agent is None:
            agent = Agent(
                id=uuid.uuid4(),
                org_id=self.org_id,
                agent_id=agent_id,
                agent_metadata=metadata,
                active=True,
            )
            self.session.add(agent)
        else:
            agent.agent_metadata = metadata

        await self.session.flush()
        await self.session.refresh(agent)

        return CopilotResponse(
            message=f"Agent **{agent_id}** has been registered successfully.",
            action_type="confirmed",
            created_resource={
                "id": str(agent.id),
                "agent_id": agent.agent_id,
                "metadata": agent.agent_metadata,
                "active": agent.active,
            },
            suggestions=["List agents", "Create a policy for this agent", "Register another agent"],
        )

    # ──────────────────────────────────────────────────────────────────────────
    # Create webhook handler
    # ──────────────────────────────────────────────────────────────────────────

    async def _handle_create_webhook(self, message: str, auto_confirm: bool) -> CopilotResponse:
        # Extract URL from the message directly
        url_match = re.search(r"https?://[^\s]+", message)
        if not url_match:
            return CopilotResponse(
                message=(
                    "Please provide the webhook URL. "
                    "Example: 'Create a webhook for https://example.com/agr-events'"
                ),
                action_type="error",
                suggestions=["Create a webhook for https://example.com/agr-events"],
            )

        url = url_match.group(0).rstrip(".,;)")

        if auto_confirm:
            return await self._create_webhook_confirmed(url=url)

        preview = CopilotPreview(
            resource_type="webhook",
            data={
                "url": url,
                "events": ["approval.approved", "approval.rejected"],
            },
            confirmation_prompt=(
                f"Create a webhook for `{url}`?\n\n"
                "Events: `approval.approved`, `approval.rejected`\n\n"
                "Reply **yes** to confirm."
            ),
        )

        return CopilotResponse(
            message=(
                f"I'll create a webhook for:\n\n"
                f"- **URL**: `{url}`\n"
                f"- **Events**: approval.approved, approval.rejected\n\n"
                "Reply **yes** to confirm."
            ),
            action_type="create_webhook",
            preview=preview,
            suggestions=["yes", "no"],
        )

    async def _create_webhook_confirmed(self, url: str) -> CopilotResponse:
        webhook = Webhook(
            id=uuid.uuid4(),
            org_id=self.org_id,
            url=url,
            secret="agr_wh_" + secrets.token_hex(24),
            events=["approval.approved", "approval.rejected"],
            active=True,
        )
        self.session.add(webhook)
        await self.session.flush()
        await self.session.refresh(webhook)

        return CopilotResponse(
            message=(
                f"Webhook for `{url}` has been created. "
                "Store the secret securely — it won't be shown again."
            ),
            action_type="confirmed",
            created_resource={
                "id": str(webhook.id),
                "url": webhook.url,
                "secret": webhook.secret,
                "events": list(webhook.events) if webhook.events else [],
                "active": webhook.active,
            },
            suggestions=["List webhooks", "Create another webhook"],
        )

    # ──────────────────────────────────────────────────────────────────────────
    # Explain handler
    # ──────────────────────────────────────────────────────────────────────────

    async def _handle_explain(
        self, message: str, conversation_history: list[CopilotMessage]
    ) -> CopilotResponse:
        llm_response = await self._call_llm(
            system_prompt=EXPLANATION_SYSTEM_PROMPT,
            user_message=message,
            conversation_history=conversation_history,
        )

        return CopilotResponse(
            message=llm_response,
            action_type="explain",
            suggestions=[
                "Show sample policies",
                "Create a policy that blocks production deploys",
                "List my policies",
            ],
        )

    # ──────────────────────────────────────────────────────────────────────────
    # General fallback
    # ──────────────────────────────────────────────────────────────────────────

    async def _handle_general(
        self, message: str, conversation_history: list[CopilotMessage]
    ) -> CopilotResponse:
        llm_response = await self._call_llm(
            system_prompt=GENERAL_SYSTEM_PROMPT,
            user_message=message,
            conversation_history=conversation_history,
        )

        return CopilotResponse(
            message=llm_response,
            action_type="general",
            suggestions=[
                "Show sample policies",
                "List my policies",
                "Create a policy that blocks production deploys",
            ],
        )

    # ──────────────────────────────────────────────────────────────────────────
    # LLM helper
    # ──────────────────────────────────────────────────────────────────────────

    async def _call_llm(
        self,
        system_prompt: str,
        user_message: str,
        conversation_history: list[CopilotMessage] | None = None,
    ) -> str:
        """Call Anthropic Claude and return the text response."""
        try:
            import anthropic

            client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

            messages: list[Any] = []
            if conversation_history:
                for msg in conversation_history:
                    messages.append({"role": msg.role, "content": msg.content})
            messages.append({"role": "user", "content": user_message})

            response = await client.messages.create(
                model=settings.copilot_model,
                max_tokens=settings.copilot_max_tokens,
                system=system_prompt,
                messages=messages,
            )

            # Use getattr so this works with both real TextBlock objects and
            # MagicMock stubs in tests (isinstance(mock, TextBlock) is False).
            return next(
                (t for t in (getattr(b, "text", None) for b in response.content) if t),
                "",
            )

        except Exception as exc:
            logger.error("Copilot LLM call failed: %s", exc)
            return (
                "I encountered an error processing your request. "
                "Please try again or contact support."
            )

    # ──────────────────────────────────────────────────────────────────────────
    # JSON parsing helper
    # ──────────────────────────────────────────────────────────────────────────

    def _parse_json_response(self, text: str) -> dict[str, Any] | None:
        """Extract and parse a JSON object from LLM response text."""
        if not text:
            return None

        # Try direct parse first
        try:
            return json.loads(text.strip())
        except json.JSONDecodeError:
            pass

        # Try extracting JSON from markdown code blocks
        match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                pass

        # Try finding any JSON object in the text
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass

        return None
