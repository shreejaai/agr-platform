"""AGR concurrent async evaluation example using a shared AsyncAGRClient."""

import asyncio
import os

from agr import AsyncAGRClient, EvaluationResult


async def evaluate_action(
    client: AsyncAGRClient,
    agent: str,
    action: str,
    resource: str,
    context: dict[str, object],
) -> EvaluationResult:
    return await client.evaluate(
        agent=agent,
        action=action,
        resource=resource,
        context=context,
    )


async def main() -> None:
    api_key = os.environ.get("AGR_API_KEY", "agr_sk_YOUR_KEY_HERE")
    base_url = os.environ.get("AGR_BASE_URL", "http://localhost:8000")

    requests = [
        ("support-agent", "read_ticket_status", "ticket-12345", {"department": "support"}),
        ("finance-agent", "transfer_funds", "bank-account-001", {"amount": 2500}),
        ("ops-agent", "deploy_release", "staging", {"change_window": "approved"}),
    ]

    async with AsyncAGRClient(api_key=api_key, base_url=base_url) as agr:
        results = await asyncio.gather(
            *(
                evaluate_action(agr, agent, action, resource, context)
                for agent, action, resource, context in requests
            )
        )

    for request, result in zip(requests, results, strict=True):
        agent, action, resource, _ = request
        print(
            f"{agent:14s} {action:20s} {resource:18s} -> {result.decision} "
            f"(risk={result.risk_score}, eval_id={result.eval_id})"
        )


if __name__ == "__main__":
    asyncio.run(main())
