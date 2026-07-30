"""MCP Client helper utilities and session sanitization."""

import os
from typing import Any

from mcp import ClientSession

# HTTP SSE Sunucu Bağlantı Adresi
SSE_URL = os.getenv("MCP_SERVER_URL", "http://localhost:8000/sse")


def _strip_bool_additional_properties(schema: Any) -> Any:
    """`additionalProperties: false` alanlarini semadan temizler.

    FastMCP bunu uretiyor ve JSON Schema'da gecerli, ancak google-genai'nin
    sema donusturucusu (_mcp_utils._filter_to_supported_schema) bu alani her
    zaman ic ice bir sema sanip .items() cagiriyor; bool geldiginde
    "AttributeError: 'bool' object has no attribute 'items'" ile patliyor.
    """
    if isinstance(schema, dict):
        return {
            k: _strip_bool_additional_properties(v)
            for k, v in schema.items()
            if not (k == "additionalProperties" and isinstance(v, bool))
        }
    if isinstance(schema, list):
        return [_strip_bool_additional_properties(v) for v in schema]
    return schema


class SanitizedClientSession(ClientSession):
    """Tool semalarini Gemini'ye verilmeden once temizleyen MCP oturumu."""

    async def list_tools(self, *args: Any, **kwargs: Any) -> Any:
        result = await super().list_tools(*args, **kwargs)
        for tool in result.tools:
            tool.inputSchema = _strip_bool_additional_properties(tool.inputSchema)
        return result
