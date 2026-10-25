"""Network boundary tests; no neural inference is mocked or claimed here."""
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
from lmt_runtime import LmtRuntime


def response(status=200, headers=None):
    return SimpleNamespace(status=status, headers=headers or {}, dispose=AsyncMock())


class WeightRoutingTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.runtime = LmtRuntime('.', '.')
        self.runtime.allow_downloads = True
        self.fetch = AsyncMock()
        self.runtime.browser = SimpleNamespace(request=SimpleNamespace(fetch=self.fetch))

    async def route(self, url, method='GET'):
        route = SimpleNamespace(request=SimpleNamespace(url=url, method=method), fulfill=AsyncMock(), abort=AsyncMock())
        await self.runtime._route(route)
        return route

    async def test_allowed_redirect_is_fetched_and_given_cors(self):
        redirect = 'https://release-assets.githubusercontent.com/model.onnx'
        final = response(headers={'access-control-allow-origin': 'https://other.example'})
        self.fetch.side_effect = [response(302, {'location': redirect}), final]
        route = await self.route('https://github.com/vendor/models/releases/download/v1/model.onnx')
        self.assertEqual([c.args[0] for c in self.fetch.call_args_list],
                         ['https://github.com/vendor/models/releases/download/v1/model.onnx', redirect])
        self.assertEqual(route.fulfill.call_args.kwargs['headers']['access-control-allow-origin'], '*')
        route.abort.assert_not_called()
        final.dispose.assert_awaited_once()

    async def test_redirect_to_metadata_is_never_requested(self):
        self.fetch.return_value = response(302, {'location': 'http://169.254.169.254/opc/v2/'})
        route = await self.route('https://github.com/vendor/model.onnx')
        self.fetch.assert_awaited_once()
        route.abort.assert_awaited_once()
        route.fulfill.assert_not_called()

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
