"""AGR async evaluate example using AsyncAGRClient."""

import asyncio
import os

from agr import AsyncAGRClient


async def main() -> None:
    api_key = os.environ.get("AGR_API_KEY", "agr_sk_YOUR_KEY_HERE")
    base_url = os.environ.get("AGR_BASE_URL", "http://localhost:8000")

    async with AsyncAGRClient(api_key=api_key, base_url=base_url) as agr:
        result = await agr.evaluate(
            agent="support-agent",
            action="read_ticket_status",
            resource="ticket-12345",
            context={"department": "support"},
        )

    print(f"Decision:   {result.decision}")
    print(f"Risk Score: {result.risk_score}")
    print(f"Risk Level: {result.risk_level}")
    print(f"Reason:     {result.reason}")


if __name__ == "__main__":
    asyncio.run(main())
