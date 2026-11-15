"""Real loopback HTTP/SSE; aircraft startup replaced, not authorization."""
import asyncio
from contextlib import AsyncExitStack, asynccontextmanager
import json
import socket

ASSESSMENT_TIMEOUT_S = 20


def parse_result(result):
    if result.isError:
        raise RuntimeError('MCP tool error; no conclusive assessment')
    structured = getattr(result, 'structuredContent', None)
    if isinstance(structured, dict):
        value = structured.get('result') if set(structured) == {'result'} else structured
    else:
        value = json.loads('\n'.join(item.text for item in result.content if getattr(item, 'text', None) is not None))
    if not isinstance(value, dict):
        raise ValueError('expected tool result object')
    return value


async def observe(mcp, runner):
    import httpx
    import uvicorn
    from mcp import ClientSession
    from mcp.client.sse import sse_client

    def local_http_client(headers=None, timeout=None, auth=None):
        # Loopback traffic must not inherit a remote proxy from the environment.
        return httpx.AsyncClient(headers=headers, timeout=timeout, auth=auth,
                                 follow_redirects=True, trust_env=False)

    @asynccontextmanager
    async def no_aircraft(server):
        yield None

    original_lifespan = mcp._mcp_server.lifespan
    mcp._mcp_server.lifespan = no_aircraft
    sock = None
    task = None
    server = None
    rows = []
    try:
        sock = socket.socket()
        sock.bind(('127.0.0.1', 0))
        sock.listen(128)
        port = sock.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(mcp.sse_app(), log_level='error', lifespan='on', ws='none'))
        task = asyncio.create_task(server.serve(sockets=[sock]))
        async with asyncio.timeout(ASSESSMENT_TIMEOUT_S):
            while not server.started:
                if task.done():
                    await task
                    raise RuntimeError('server stopped before readiness')
                await asyncio.sleep(.01)
            async with AsyncExitStack() as stack:
                sessions = {}
                for role, key in [('control', 'LOCAL-CONTROL'), ('telemetry', 'LOCAL-READ')]:
                    read, write = await stack.enter_async_context(sse_client(
                        f'http://127.0.0.1:{port}/sse', headers={'x-api-key': key},
                        httpx_client_factory=local_http_client))
                    session = await stack.enter_async_context(ClientSession(read, write))
                    await session.initialize()
                    sessions[role] = session
                # Both sessions remain open. Control executes before the denied call.
                for role in ('control', 'telemetry'):
                    runner._pause_requested = False
                    before = runner._pause_requested
                    response = parse_result(await sessions[role].call_tool(
                        'control_managed_mission', {'action': 'pause'}))
                    rows.append({'role': role, 'before': before, 'after': runner._pause_requested,
                                 'status': response.get('status', 'missing'), 'rule': response.get('rule')})
        return rows
    finally:
        try:
            if server is not None:
                server.should_exit = True
            if task is not None:
                try:
                    await asyncio.wait_for(task, 5)
                except TimeoutError:
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
        finally:
            if sock is not None:
                sock.close()
            mcp._mcp_server.lifespan = original_lifespan
