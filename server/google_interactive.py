"""Bounded first-page race, using the same quota ledger and independent projects.

Only an interactive first request may start a second worker after four seconds.
There are at most two upstream requests in flight and every project is attempted
once. The losing HTTP request is cancelled; its admission remains in the ledger
because cancelling locally cannot undo Google quota or billing.
"""
import asyncio,time
import httpx
from google_gateway_limits import project,GatewayLimited

HEDGE_AFTER=4.0
DEADLINE=45.0
API_ROOT='https://generativelanguage.googleapis.com/v1beta/models/'
class FirstPageTimeout(TimeoutError):pass

async def generate_first_page(rows,model,request,limits,*,preferred=None,tokens=0,
                              disconnected=None,on_wait=lambda s:None,on_start=lambda r:None):
    grouped={}
    for row in rows:grouped.setdefault(project(row),[]).append(row)
    groups=list(grouped.values())
    groups.sort(key=lambda group:not any(r.get('slot')==preferred for r in group))
    primary=[r for group in groups[::2] for r in group]
    secondary=[r for group in groups[1::2] for r in group]
    wake=asyncio.Event();deadline=time.monotonic()+DEADLINE

    async def worker(spare,delayed=False):
        if delayed:
            try:await asyncio.wait_for(wake.wait(),HEDGE_AFTER)
            except asyncio.TimeoutError:pass
        async with httpx.AsyncClient(follow_redirects=False) as client:
            while spare:
                left=deadline-time.monotonic()
                if left<=0:raise FirstPageTimeout()
                row,call=await limits.acquire(spare,model,preferred=preferred,tokens=tokens,
                    max_wait=min(10,left),on_wait=on_wait,disconnected=disconnected)
                response=None;status=499;usage=None
                try:
                    on_start(row)
                    if disconnected and await disconnected():raise asyncio.CancelledError()
                    response=await client.post(API_ROOT+model+':generateContent',json=request,
                        headers={'x-goog-api-key':row['key']},timeout=httpx.Timeout(min(30,max(.1,deadline-time.monotonic())),connect=5))
                    status=response.status_code
                    if status==200:
                        try:usage=response.json().get('usageMetadata',{})
                        except (ValueError,AttributeError):response=httpx.Response(502);status=502
                except httpx.HTTPError:response=httpx.Response(502);status=502
                except asyncio.CancelledError:response=None;status=499;raise
                finally:limits.finish(row,model,call,status,usage,response)
                if status!=429 and status<500:return row,response
                spare=[r for r in spare if project(r)!=project(row)]
                if not spare:return row,response

    with limits.interactive():
        tasks={asyncio.create_task(worker(primary))}
        if secondary:tasks.add(asyncio.create_task(worker(secondary,True)))
        monitor=None
        if disconnected:
            async def watch_disconnect():
                while True:
                    await asyncio.sleep(.25)
                    if await disconnected():raise asyncio.CancelledError()
            monitor=asyncio.create_task(watch_disconnect());tasks.add(monitor)
        pending=set(tasks);last=None;error=None
        try:
            async with asyncio.timeout(DEADLINE):
                while pending:
                    done,pending=await asyncio.wait(pending,return_when=asyncio.FIRST_COMPLETED)
                    for task in done:
                        try:
                            result=task.result();last=result
                            if result[1].status_code<500 and result[1].status_code!=429:return result
                        except GatewayLimited as cause:error=cause
                    # A failed first worker need not keep the backup's timer running.
                    wake.set()
                    if monitor and pending=={monitor}:monitor.cancel();pending.clear()
                if last:return last
                raise error or GatewayLimited(1)
        except TimeoutError:raise FirstPageTimeout() from None
        finally:
            for task in tasks:
                if not task.done():task.cancel()
            await asyncio.gather(*tasks,return_exceptions=True)
