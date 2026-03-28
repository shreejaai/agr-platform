# AGR LangChain Middleware

`AGRToolGuard` wraps LangChain tools and calls AGR before execution.

## Usage

```python
from agr.client import AGRClient
from agr_langchain import guard_tools

agr_client = AGRClient(api_key="agr_sk_...")
agent.tools = guard_tools(agent.tools, agr_client, "my-agent")
```

`AGRCallbackHandler` can also be attached for lightweight tool-start and tool-error logging.
