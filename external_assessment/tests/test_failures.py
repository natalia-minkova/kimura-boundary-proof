import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
from external_assessment.droneserver import main
from external_assessment.http_sse import parse_result
from external_assessment.core import verdict

class FailureTests(unittest.TestCase):
    def test_mcp_error_not_treated_as_denial(self):
        with self.assertRaises(RuntimeError):
            parse_result(SimpleNamespace(isError=True))

    def test_missing_response_not_evidence(self):
        with self.assertRaises(ValueError):
            parse_result(SimpleNamespace(isError=False, structuredContent=None, content=[]))

    def test_non_object_response_rejected(self):
        with self.assertRaises(ValueError):
            parse_result(SimpleNamespace(isError=False, structuredContent={'result': []}))

    def test_contradictory_positive_response_is_inconclusive(self):
        rows=[dict(role='control', before=False, after=True, status='success', rule='authz.insufficient_scope'),
              dict(role='telemetry', before=False, after=False, status='rejected', rule='authz.insufficient_scope')]
        self.assertEqual(verdict(rows), 'INCONCLUSIVE')

    def test_transport_failures_create_no_evidence_or_verdict(self):
        for error in (TimeoutError(), ConnectionError(), RuntimeError()):
            with self.subTest(error=type(error).__name__), tempfile.TemporaryDirectory() as tmp:
                output=Path(tmp)/'evidence.json'
                with patch('sys.argv',['assessment','--target-checkout',tmp,'--output',str(output)]), \
                     patch('external_assessment.droneserver.assess',new=AsyncMock(side_effect=error)), \
                     patch('sys.stdout',new_callable=io.StringIO) as stream:
                    self.assertEqual(main(),2)
                result=json.loads(stream.getvalue())
                self.assertFalse(result['assessment_completed'])
                self.assertIsNone(result['boundary_verdict'])
                self.assertFalse(output.exists())

    def test_existing_evidence_not_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            output=Path(tmp)/'evidence.json';output.write_text('keep')
            with patch('sys.argv',['assessment','--target-checkout',tmp,'--output',str(output)]), \
                 patch('external_assessment.droneserver.assess',new=AsyncMock()) as assess, \
                 patch('sys.stdout',new_callable=io.StringIO):
                self.assertEqual(main(),2)
                assess.assert_not_called()
            self.assertEqual(output.read_text(),'keep')

class LifecycleTests(unittest.IsolatedAsyncioTestCase):
    def modules(self, server):
        return {'httpx': SimpleNamespace(),
                'uvicorn': SimpleNamespace(Config=lambda *a, **k: None, Server=lambda config: server),
                'mcp': SimpleNamespace(ClientSession=None),
                'mcp.client': SimpleNamespace(),
                'mcp.client.sse': SimpleNamespace(sse_client=None)}

    async def test_socket_failure_restores_aircraft_lifespan(self):
        from external_assessment.http_sse import observe
        original=object()
        mcp=SimpleNamespace(_mcp_server=SimpleNamespace(lifespan=original))
        with patch.dict('sys.modules',self.modules(None)), \
             patch('external_assessment.http_sse.socket.socket',side_effect=OSError('socket failed')):
            with self.assertRaises(OSError): await observe(mcp,None)
        self.assertIs(mcp._mcp_server.lifespan,original)

    async def test_startup_timeout_stops_server_closes_socket_restores_lifespan(self):
        import asyncio
        from unittest.mock import MagicMock
        from external_assessment.http_sse import observe
        original=object()
        mcp=SimpleNamespace(_mcp_server=SimpleNamespace(lifespan=original),sse_app=lambda:None)
        class Server:
            started=False
            should_exit=False
            stopped=False
            async def serve(self, sockets):
                try:
                    while not self.should_exit: await asyncio.sleep(.001)
                finally: self.stopped=True
        server=Server();sock=MagicMock();sock.getsockname.return_value=('127.0.0.1',1234)
        with patch.dict('sys.modules',self.modules(server)), \
             patch('external_assessment.http_sse.socket.socket',return_value=sock), \
             patch('external_assessment.http_sse.ASSESSMENT_TIMEOUT_S',.02):
            with self.assertRaises(TimeoutError): await observe(mcp,None)
        self.assertTrue(server.stopped)
        sock.close.assert_called_once()
        self.assertIs(mcp._mcp_server.lifespan,original)
