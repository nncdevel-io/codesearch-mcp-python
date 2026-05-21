"""FastMCP server wiring with concurrency guard, per-tool timeouts, error handling."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any

from mcp import types
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.utilities.func_metadata import FuncMetadata
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import CallToolResult, GetPromptRequest, ListPromptsRequest

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

# --- FastMCP convert_result patch (TASK-066) --------------------------------
#
# FastMCP's `FuncMetadata.convert_result` validates `structuredContent`
# against `output_model` unconditionally when `output_schema` is set. Our
# error envelope (spec §5.1) returns CallToolResult with structuredContent=None
# (the JSON `{code,message,details}` lives in content[0].text instead), and
# validating None against the output model fails. We patch the method at the
# class level once at import time so the None-structuredContent error path
# bypasses validation while every other code path is untouched. Scope is
# narrow: the patch only adds an early-return branch; CallToolResults with
# real structuredContent and dict returns are validated exactly as before.

_original_convert_result = FuncMetadata.convert_result


def _convert_result_lenient_on_error(self: FuncMetadata, result: Any) -> Any:
    if isinstance(result, CallToolResult) and result.structuredContent is None:
        return result
    return _original_convert_result(self, result)


FuncMetadata.convert_result = _convert_result_lenient_on_error  # type: ignore[assignment,method-assign]

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


def _attach_output_schemas(mcp: FastMCP) -> None:
    """Advertise per-tool outputSchema via FuncMetadata.

    The class-level patch above (``_convert_result_lenient_on_error``) handles
    the error CallToolResult path; here we just point each tool's metadata at
    the corresponding Pydantic output model.
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
        isError=True,
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


def build_server(
    settings: Settings,
    manager: RepositoryManager | None = None,
    *,
    host: str = "127.0.0.1",
    port: int = 8000,
    allowed_hosts: list[str] | None = None,
    allowed_origins: list[str] | None = None,
) -> FastMCP:
    """Create a configured FastMCP application that exposes the four tools."""

    mgr = manager or RepositoryManager(settings)
    guard = ToolExecutionGuard()
    default_hosts = [
        "127.0.0.1",
        "127.0.0.1:*",
        "localhost",
        "localhost:*",
        host,
        f"{host}:*",
    ]
    default_origins = [
        "http://127.0.0.1",
        "http://127.0.0.1:*",
        "http://localhost",
        "http://localhost:*",
        f"http://{host}",
        f"http://{host}:*",
    ]
    security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=allowed_hosts or default_hosts,
        allowed_origins=allowed_origins or default_origins,
    )
    mcp = FastMCP(
        "codesearch-mcp",
        instructions=SERVER_INSTRUCTIONS,
        host=host,
        port=port,
        transport_security=security,
    )
    # FastMCP does not expose the underlying server's `version` as a kwarg, so
    # we set it directly. Without this, `initialize` reports the MCP SDK's
    # version instead of this project's, which misleads clients.
    mcp._mcp_server.version = __version__

    # FastMCP unconditionally registers prompts handlers, which makes
    # `capabilities.prompts` get advertised in `initialize` even though we
    # expose none. Spec §2.2 requires that we do not advertise prompts —
    # remove the handlers so `get_capabilities()` does not include them.
    mcp._mcp_server.request_handlers.pop(ListPromptsRequest, None)
    mcp._mcp_server.request_handlers.pop(GetPromptRequest, None)

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
