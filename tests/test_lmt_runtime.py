"""Network boundary tests; no neural inference is mocked or claimed here."""
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
from lmt_runtime import LmtRuntime


class WeightRoutingTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.runtime = LmtRuntime('.', '.')
        self.runtime.allow_downloads = True
        self.fetch = AsyncMock()
        self.runtime.browser = SimpleNamespace(request=SimpleNamespace(fetch=self.fetch))

    async def route(self, url, method='GET'):
        route = SimpleNamespace(request=SimpleNamespace(url=url, method=method), fulfill=AsyncMock(), abort=AsyncMock(), continue_=AsyncMock())
        await self.runtime._route(route)
        return route

    async def test_hf_weights_use_native_streaming(self):
        route = await self.route('https://huggingface.co/vendor/resolve/main/model.onnx')
        route.continue_.assert_awaited_once()
        self.fetch.assert_not_called()
        route.abort.assert_not_called()

    async def test_metadata_host_is_denied(self):
        route = await self.route('http://169.254.169.254/opc/v2/')
        self.fetch.assert_not_called()
        route.abort.assert_awaited_once_with('blockedbyclient')
        route.continue_.assert_not_called()

    async def test_model_host_upload_is_denied(self):
        route = await self.route('https://huggingface.co/vendor/model', 'POST')
        self.fetch.assert_not_called()
        route.abort.assert_awaited_once_with('blockedbyclient')

    async def test_download_opt_out_is_enforced(self):
        self.runtime.allow_downloads = False
        route = await self.route('https://huggingface.co/vendor/model')
        self.fetch.assert_not_called()
        route.abort.assert_awaited_once_with('blockedbyclient')

    async def test_fake_host_and_credentials_are_rejected(self):
        for url in ['https://huggingface.co.evil.example/model', 'https://user:secret@huggingface.co/model']:
            self.assertFalse(self.runtime._weight_url_allowed(url))
