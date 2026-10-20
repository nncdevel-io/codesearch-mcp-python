"""MCPServer wiring with concurrency guard, per-tool timeouts, error handling."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from mcp import MCPError, types
from mcp.server.context import CallNext, HandlerResult, ServerRequestContext
from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import BaseModel

from . import __version__
from .config.models import Settings
from .errors import ErrorCode, ToolError, error_payload
from .llm_guidance import (
    LIST_FILES_DESCRIPTION,
    LIST_REPOSITORIES_DESCRIPTION,
    LIST_TREE_DESCRIPTION,
    READ_FILE_DESCRIPTION,
    SEARCH_CODE_DESCRIPTION,
    SERVER_INSTRUCTIONS,
)
from .logging import get_logger, log_event
from .repo.manager import RepositoryManager
from .resources import register_repository_resources, repository_catalog
from .tool_outputs import TOOL_OUTPUT_MODELS
from .tools.list_files import execute_list_files
from .tools.list_tree import execute_list_tree
from .tools.read_file import execute_read_file
from .tools.schemas import (
    ListFilesInput,
    ListRepositoriesInput,
    ListTreeInput,
    ReadFileInput,
    SearchCodeInput,
)
from .tools.search_code import execute_search_code

MAX_CONCURRENT_TOOL_CALLS = 16
QUEUE_TIMEOUT_SECONDS = 30.0
TOOL_TIMEOUT_SECONDS: dict[str, float] = {
    "list_repositories": 1.0,
    "search_code": 10.0,
    "list_files": 5.0,
    "list_tree": 5.0,
    "read_file": 3.0,
}


class ToolExecutionGuard:
    """Caps in-flight tool executions and enforces per-tool timeout."""

    def __init__(self, max_concurrent: int = MAX_CONCURRENT_TOOL_CALLS) -> None:
        self._sem = asyncio.Semaphore(max_concurrent)

    async def run(
        self,
        tool_name: str,
        fn: Callable[[], Awaitable[Any]],
        *,
        per_tool_timeout: float,
        queue_timeout: float = QUEUE_TIMEOUT_SECONDS,
    ) -> Any:
        start = time.monotonic()
        try:
            await asyncio.wait_for(self._sem.acquire(), timeout=queue_timeout)
        except TimeoutError as cause:
            raise ToolError(
                ErrorCode.TIMEOUT,
                "tool call exceeded the queue wait limit",
                {"tool": tool_name, "queue_timeout_seconds": queue_timeout},
            ) from cause
        try:
            elapsed = time.monotonic() - start
            remaining_tool = min(per_tool_timeout, queue_timeout - elapsed)
            if remaining_tool <= 0:
                raise ToolError(
                    ErrorCode.TIMEOUT,
                    "tool call exceeded the total time limit",
                    {"tool": tool_name},
                )
            try:
                return await asyncio.wait_for(fn(), timeout=remaining_tool)
            except TimeoutError as cause:
                raise ToolError(
                    ErrorCode.TIMEOUT,
                    "tool processing timed out",
                    {"tool": tool_name, "timeout_seconds": per_tool_timeout},
                ) from cause
        finally:
            self._sem.release()


async def _async_repository_catalog(mgr: RepositoryManager) -> dict[str, Any]:
    """Synchronous catalog wrapped as a coroutine for the dispatcher contract."""
    return {"repositories": repository_catalog(mgr)}


def _attach_output_schemas(mcp: MCPServer) -> None:
    """Advertise per-tool outputSchema via FuncMetadata.

    Error results (``is_error=True``, no structured content) skip output
    validation inside the SDK's ``convert_result``, so only the success path
    is checked against these models.
    """

    for tool_name, model in TOOL_OUTPUT_MODELS.items():
        tool = mcp._tool_manager.get_tool(tool_name)
        if tool is None:
            continue
        fm = tool.fn_metadata
        fm.output_schema = model.model_json_schema()
        fm.output_model = model
        # Our tool functions return a plain dict on success (not wrapped). The
        # default `wrap_output` for non-BaseModel return types is True, which
        # would wrap our dict as {"result": ...}.
        fm.wrap_output = False


def _to_is_error(err: ToolError) -> types.CallToolResult:
    return types.CallToolResult(
        is_error=True,
        content=[types.TextContent(type="text", text=error_payload(err))],
    )


async def _dispatch(
    guard: ToolExecutionGuard,
    tool_name: str,
    runner: Callable[[], Awaitable[Any]],
) -> Any:
    start = time.monotonic()
    try:
        result = await guard.run(
            tool_name,
            runner,
            per_tool_timeout=TOOL_TIMEOUT_SECONDS[tool_name],
        )
    except ToolError as err:
        log_event(
            "warning",
            "tool_call_error",
            tool=tool_name,
            code=err.code.value,
            message=err.message,
        )
        return _to_is_error(err)
    except Exception as cause:  # noqa: BLE001
        get_logger().exception("unhandled tool error")
        return _to_is_error(
            ToolError(
                ErrorCode.INTERNAL_ERROR,
                "unexpected internal error",
                {"tool": tool_name, "reason": type(cause).__name__},
            )
        )
    log_event(
        "info",
        "tool_call_end",
        tool=tool_name,
        duration_ms=int((time.monotonic() - start) * 1000),
    )
    return result


# --- JSON-RPC message debug logging (design §8) ----------------------------
#
# When the log level is DEBUG, every JSON-RPC exchange is logged in full. The
# SDK's ``ServerMiddleware`` chain wraps every inbound request and
# notification on every transport (stdio, Streamable HTTP in both the
# handshake and the per-request era, in-process), so it is the one common
# interception point. Teeing the ``Server.run`` streams no longer works:
# Streamable HTTP bypasses ``Server.run`` in mcp 2.x. ASGI middleware would
# only cover HTTP (not stdio). See design §8.1.


def _log_jsonrpc(direction: str, message: dict[str, Any]) -> None:
    """Log one JSON-RPC message at DEBUG, redacting secrets via the log layer.

    ``direction`` is ``"incoming"`` (client → server) or ``"outgoing"``
    (server → client).
    """
    log_event("debug", "jsonrpc_message", direction=direction, message=message)


def _dump_result(result: HandlerResult) -> dict[str, Any]:
    if isinstance(result, BaseModel):
        return result.model_dump(by_alias=True, mode="json", exclude_none=True)
    return result or {}


async def _jsonrpc_logging_middleware(
    ctx: ServerRequestContext[Any, Any],
    call_next: CallNext,
) -> HandlerResult:
    """Log the inbound message and its response, then pass the result through.

    Serialization is skipped entirely unless DEBUG is enabled so the default
    INFO operation pays no cost. Notifications (``request_id is None``) have no
    response, so only the inbound side is logged for them.
    """
    if not get_logger().isEnabledFor(logging.DEBUG):
        return await call_next(ctx)
    incoming: dict[str, Any] = {"jsonrpc": "2.0", "method": ctx.method}
    if ctx.request_id is not None:
        incoming["id"] = ctx.request_id
    if ctx.params is not None:
        incoming["params"] = dict(ctx.params)
    _log_jsonrpc("incoming", incoming)
    try:
        result = await call_next(ctx)
    except Exception as exc:
        _log_jsonrpc("outgoing", {"jsonrpc": "2.0", "id": ctx.request_id, "error": repr(exc)})
        raise
    if ctx.request_id is not None:
        _log_jsonrpc(
            "outgoing",
            {"jsonrpc": "2.0", "id": ctx.request_id, "result": _dump_result(result)},
        )
    return result


def build_transport_security(host: str) -> TransportSecuritySettings:
    """Build the DNS-rebinding protection settings for Streamable HTTP.

    Args:
        host: Bind host of the HTTP server; it is allowed (any port) alongside
            loopback in both the ``Host`` and ``Origin`` allow-lists.

    Returns:
        Settings with DNS-rebinding protection enabled.
    """
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[
            "127.0.0.1",
            "127.0.0.1:*",
            "localhost",
            "localhost:*",
            host,
            f"{host}:*",
        ],
        allowed_origins=[
            "http://127.0.0.1",
            "http://127.0.0.1:*",
            "http://localhost",
            "http://localhost:*",
            f"http://{host}",
            f"http://{host}:*",
        ],
    )


def build_server(
    settings: Settings,
    manager: RepositoryManager | None = None,
) -> MCPServer:
    """Create a configured MCPServer application that exposes the five tools.

    HTTP bind address and transport security are not part of the server in
    mcp 2.x; pass them to ``run_streamable_http_async`` /
    ``streamable_http_app`` (see ``build_transport_security``).
    """

    mgr = manager or RepositoryManager(settings)
    guard = ToolExecutionGuard()
    # `subscriptions=False`: no list-changed or resource-update events are ever
    # emitted, so `subscriptions/listen` must not be served — serving it makes
    # the SDK advertise `listChanged` / `resources.subscribe` as true.

    async def reject_unknown_tool(
        ctx: ServerRequestContext[Any, Any],
        call_next: CallNext,
    ) -> HandlerResult:
        # MCP spec (Tools > Error Handling) classifies an unknown tool as a
        # protocol error (JSON-RPC -32602). MCPServer instead reports it as a
        # tool execution error (`isError`), so reject it before dispatch.
        name = (ctx.params or {}).get("name") if ctx.method == "tools/call" else None
        if isinstance(name, str) and mcp._tool_manager.get_tool(name) is None:
            raise MCPError(code=types.INVALID_PARAMS, message=f"Unknown tool: {name}")
        return await call_next(ctx)

    mcp = MCPServer(
        "codesearch-mcp",
        instructions=SERVER_INSTRUCTIONS,
        version=__version__,
        subscriptions=False,
        # Logging is outermost so protocol errors raised by the inner
        # middleware are logged too (design §8).
        middleware=[_jsonrpc_logging_middleware, reject_unknown_tool],
    )

    # MCPServer unconditionally registers prompts handlers, which makes
    # `capabilities.prompts` get advertised in `initialize` even though we
    # expose none. Spec §2.2 requires that we do not advertise prompts —
    # remove the handlers so `get_capabilities()` does not include them. The
    # SDK has no public API to unregister a handler, hence the private access.
    mcp._lowlevel_server._request_handlers.pop("prompts/list", None)
    mcp._lowlevel_server._request_handlers.pop("prompts/get", None)

    # Repository catalog as Resources — the LLM-discoverable list of valid
    # `repository` argument values (see docs/distribution.md and spec §3.x).
    register_repository_resources(mcp, settings, mgr)

    @mcp.tool(name="search_code", description=SEARCH_CODE_DESCRIPTION)
    async def search_code(
        pattern: str,
        repository: str,
        path: str | None = None,
        glob: str | None = None,
        type: str | None = None,
        case_sensitive: bool = False,
        output_mode: str = "content",
        context_before: int = 0,
        context_after: int = 0,
        max_results: int = 50,
    ) -> Any:
        payload = SearchCodeInput(
            pattern=pattern,
            repository=repository,
            path=path,
            glob=glob,
            type=type,
            case_sensitive=case_sensitive,
            output_mode=output_mode,  # type: ignore[arg-type]
            context_before=context_before,
            context_after=context_after,
            max_results=max_results,
        )
        log_event("info", "tool_call_start", tool="search_code", repository=repository)
        return await _dispatch(guard, "search_code", lambda: execute_search_code(mgr, payload))

    @mcp.tool(name="list_files", description=LIST_FILES_DESCRIPTION)
    async def list_files(
        repository: str,
        pattern: str,
        path: str | None = None,
        max_results: int = 100,
    ) -> Any:
        payload = ListFilesInput(
            repository=repository,
            pattern=pattern,
            path=path,
            max_results=max_results,
        )
        log_event("info", "tool_call_start", tool="list_files", repository=repository)
        return await _dispatch(guard, "list_files", lambda: execute_list_files(mgr, payload))

    @mcp.tool(name="list_tree", description=LIST_TREE_DESCRIPTION)
    async def list_tree(
        repository: str,
        path: str | None = None,
        max_depth: int = 2,
        show_files: bool = True,
        max_entries: int = 200,
    ) -> Any:
        payload = ListTreeInput(
            repository=repository,
            path=path,
            max_depth=max_depth,
            show_files=show_files,
            max_entries=max_entries,
        )
        log_event("info", "tool_call_start", tool="list_tree", repository=repository)
        return await _dispatch(guard, "list_tree", lambda: execute_list_tree(mgr, payload))

    @mcp.tool(name="list_repositories", description=LIST_REPOSITORIES_DESCRIPTION)
    async def list_repositories() -> Any:
        ListRepositoriesInput()  # validate empty schema
        log_event("info", "tool_call_start", tool="list_repositories")
        return await _dispatch(
            guard,
            "list_repositories",
            lambda: _async_repository_catalog(mgr),
        )

    @mcp.tool(name="read_file", description=READ_FILE_DESCRIPTION)
    async def read_file(
        repository: str,
        file_path: str,
        start_line: int = 1,
        num_lines: int = 100,
    ) -> Any:
        payload = ReadFileInput(
            repository=repository,
            file_path=file_path,
            start_line=start_line,
            num_lines=num_lines,
        )
        log_event("info", "tool_call_start", tool="read_file", repository=repository)
        return await _dispatch(guard, "read_file", lambda: execute_read_file(mgr, payload))

    _attach_output_schemas(mcp)
    return mcp
