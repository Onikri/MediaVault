"""Rolling-window reservations. Unknown/shared quotas never become extra pools."""
from __future__ import annotations
import asyncio
from collections import defaultdict,deque
from dataclasses import dataclass
import time

class Deferred(Exception):
    def __init__(self, seconds):self.seconds=max(.05,float(seconds))

@dataclass
class Reservation:
    model:str
    group:str
    at:float
    tokens:int

class QuotaPacer:
    def __init__(self, *, tpm=13000, rpm=14, independent=False, clock=time.monotonic):
        self.tpm=tpm;self.rpm=rpm;self.independent=independent;self.clock=clock
        self.windows=defaultdict(deque);self.cooldowns={};self.lock=asyncio.Lock()

    def group(self, model):return model if self.independent else 'google-project'

    async def reserve(self, models, tokens):
        if not 0<tokens<=self.tpm:raise ValueError('Batch exceeds the configured token window; split it')
        async with self.lock:
            now=self.clock();waits=[]
            for model in models:
                group=self.group(model);window=self.windows[group]
                while window and now-window[0].at>=60:window.popleft()
                cooldown=max(self.cooldowns.get(model,0),self.cooldowns.get(group,0))-now
                if cooldown>0:waits.append(cooldown);continue
                if sum(r.tokens for r in window)+tokens<=self.tpm and len(window)<self.rpm:
                    lease=Reservation(model,group,now,tokens);window.append(lease);return lease
                waits.append(max(.05,60-(now-window[0].at)))
            raise Deferred(min(waits) if waits else 1)

    async def account(self, lease, actual_tokens):
        async with self.lock:lease.tokens=max(0,int(actual_tokens))

    async def limited(self, model, seconds, *, project_wide):
        async with self.lock:
            key=self.group(model) if project_wide else model
            self.cooldowns[key]=max(self.cooldowns.get(key,0),self.clock()+max(1,seconds))

    def snapshot(self):
        now=self.clock()
        return {'independentPools':self.independent,'tpmBudget':self.tpm,'rpmBudget':self.rpm,'groups':{name:{'reservedInputTokens':sum(r.tokens for r in q if now-r.at<60),'requests':sum(now-r.at<60 for r in q)} for name,q in self.windows.items()}}
