"""Queue/API contracts and tiling correctness. These are not ML quality tests."""
import asyncio
import base64
import io
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server'))
from fastapi import FastAPI, HTTPException
import httpx
from PIL import Image
from manga_upscale import Upscaler, ProcessingCancelled, model_catalog, read_image, select_model
from reader_processing import Processor, ProcessOptions, install, TTL


def page_bytes(fmt='PNG'):
    stream=io.BytesIO();Image.new('RGB',(91,73),'white').save(stream,format=fmt)
    return stream.getvalue()


class ImageTests(unittest.TestCase):
    def test_real_jpeg_png_webp_decoding_and_rejecting_invalid_image(self):
        for fmt in ['JPEG','PNG','WEBP']:
            self.assertEqual(read_image(page_bytes(fmt)).size,(91,73))
        with self.assertRaises(ValueError):read_image(b'not an image')
        with self.assertRaises(ValueError):read_image(page_bytes('TIFF'))

    def test_auto_model_uses_color_and_nearest_height_and_never_silently_switches_scale(self):
        def model(name,scale,height,color):return {'id':name,'name':name,'scale':scale,'height':height,'color':color,'format':'pth'}
        models=[model('2x_1200p',2,1200,False),model('2x_1600p',2,1600,False),model('2x_V3_FDAT_M',2,None,True)]
        self.assertEqual(select_model(models,Image.new('RGB',(900,1530),'gray'))['id'],'2x_1600p')
        self.assertEqual(select_model(models,Image.new('RGB',(900,1530),'red'))['id'],'2x_V3_FDAT_M')
        with self.assertRaises(ValueError):select_model(models,Image.new('RGB',(900,1530)),4)
        with self.assertRaises(ValueError):select_model(models,Image.new('RGB',(9,9)),model='../arbitrary.pth')

    def test_overlap_tiling_keeps_exact_edges_and_odd_dimensions(self):
        import numpy as np
        values=np.random.default_rng(42).integers(0,255,(73,91,3),dtype=np.uint8)
        image=Image.fromarray(values)
        model={'id':'2x_MangaJaNai_fixture.pth','name':'MangaJaNai fixture','scale':2,'color':False,'height':None,'format':'pth'}
        upscaler=Upscaler('/unused')
        # Nearest replication verifies the tile assembler, not neural inference.
        fake=lambda array:np.repeat(np.repeat(array,2,axis=2),2,axis=3)
        with patch('manga_upscale.model_catalog',return_value=[model]),patch.object(upscaler,'_load',return_value=(fake,'fixture',16)):
            result,info=upscaler.run(image,{'model':model['id'],'tile':64})
            np.testing.assert_array_equal(np.asarray(result),np.repeat(np.repeat(values,2,axis=0),2,axis=1))
            self.assertEqual(info['width'],182)
            with self.assertRaises(ProcessingCancelled):upscaler.run(image,{'model':model['id']},cancelled=lambda:True)


class QueueTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory=tempfile.TemporaryDirectory();self.processor=Processor(self.directory.name)
    async def asyncTearDown(self):
        await self.processor.close();self.directory.cleanup()

    async def test_queued_cancellation_never_calls_processor_and_foreign_owner_sees_404(self):
        self.processor._process=AsyncMock(return_value={'regions':[]})
        job_id=self.processor.submit(page_bytes(),ProcessOptions(upscale=True).model_dump(),'first')
        with self.assertRaises(HTTPException) as error:self.processor.get(job_id,'second')
        self.assertEqual(error.exception.status_code,404)
        self.processor.cancel(self.processor.get(job_id,'first'))
        await self.processor.worker
        self.processor._process.assert_not_awaited()
        self.assertEqual(self.processor.get(job_id,'first')['state'],'cancelled')
        self.assertEqual(self.processor.get(job_id,'first')['data'],b'')

    async def test_failed_job_does_not_block_next_and_results_expire(self):
        self.processor._process=AsyncMock(side_effect=[ValueError('missing model'),{'regions':[]}])
        options=ProcessOptions(upscale=True).model_dump()
        first=self.processor.submit(page_bytes(),options,'owner');second=self.processor.submit(page_bytes(),options,'owner')
        await self.processor.worker
        self.assertEqual(self.processor.get(first,'owner')['state'],'error')
        self.assertEqual(self.processor.get(second,'owner')['state'],'done')
        self.assertTrue(all(not j['data'] for j in self.processor.jobs.values()))
        self.processor.jobs[second]['updated']=time.monotonic()-TTL-1
        with self.assertRaises(HTTPException):self.processor.get(second,'owner')

    async def test_active_translation_cancels_and_next_job_runs(self):
        started=asyncio.Event();calls=[]
        async def work(job):
            calls.append(job)
            if len(calls)==1:
                started.set();await asyncio.sleep(60)
            return {'regions':[]}
        self.processor._process=work
        options=ProcessOptions(translate=True).model_dump()
        first=self.processor.submit(page_bytes(),options,'owner')
        await started.wait()
        second=self.processor.submit(page_bytes(),options,'owner')
        self.processor.cancel(self.processor.get(first,'owner'))
        await asyncio.wait_for(self.processor.worker,3)
        self.assertEqual(self.processor.get(first,'owner')['state'],'cancelled')
        self.assertEqual(self.processor.get(second,'owner')['state'],'done')


class ApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_detection_does_not_require_llm_and_inpaint_result_is_retained(self):
        app=FastAPI()
        with tempfile.TemporaryDirectory() as directory:
            processor=install(app,directory,lambda:'owner')
            processor.lmt.status=lambda:{'ready':False,'assetsReady':True}
            processor._process=AsyncMock(return_value={'regions':[],'cleanedImage':'AQID'})
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
                payload={'image':base64.b64encode(page_bytes()).decode(),'options':{'translate':True,'operation':'detect','allowDownloads':True}}
                response=await client.post('/reader/jobs',json=payload)
                self.assertEqual(response.status_code,202)
                await processor.worker
                result=await client.get('/reader/jobs/'+response.json()['id'])
                self.assertEqual(result.json()['result']['cleanedImage'],'AQID')
                payload['options']['operation']='translate'
                self.assertEqual((await client.post('/reader/jobs',json=payload)).status_code,503)
            await processor.close()

    async def test_authentication_guards_submission_poll_and_cancel(self):
        def denied():raise HTTPException(401,'Login')
        app=FastAPI();processor=install(app,'/unused',denied)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
            self.assertEqual((await client.get('/reader/processing')).status_code,200)
            payload={'image':base64.b64encode(page_bytes()).decode(),'options':{'upscale':True}}
            self.assertEqual((await client.post('/reader/jobs',json=payload)).status_code,401)
            self.assertEqual((await client.get('/reader/jobs/id')).status_code,401)
            self.assertEqual((await client.post('/reader/jobs/id/cancel')).status_code,401)
        await processor.close()

    async def test_untrusted_fields_are_rejected_and_job_status_does_not_echo_pixels(self):
        app=FastAPI()
        with tempfile.TemporaryDirectory() as directory:
            processor=install(app,directory,lambda:'owner')
            processor._process=AsyncMock(return_value={'regions':[]})
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
                payload={'image':base64.b64encode(page_bytes()).decode(),'options':{'upscale':True,'host':'http://metadata.internal'}}
                self.assertEqual((await client.post('/reader/jobs',json=payload)).status_code,422)
                payload['options'].pop('host')
                with patch('reader_processing.model_catalog',return_value=[{'id':'installed'}]):
                    response=await client.post('/reader/jobs',json=payload)
                self.assertEqual(response.status_code,202)
                result=await client.get('/reader/jobs/'+response.json()['id'])
                self.assertNotIn('image',result.json());self.assertNotIn('subject',result.json())
            await processor.close()


if __name__=='__main__':unittest.main()
