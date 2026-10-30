"""Observed Google usage and durable cooldowns. Never stores raw credentials.

RPM is a local admission budget, not a claim about the project's Google balance.
Only Google-reported quota dimensions and retry delays are provider facts.
"""
import asyncio,hashlib,json,math,sqlite3,time
from contextlib import closing
from datetime import datetime,timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from zoneinfo import ZoneInfo

def identity(key):return hashlib.sha256(key.encode()).hexdigest()
def project(row):return identity(row.get('project') or 'unknown-shared-project')

def provider_limit(response,now):
    delay=0;dimensions=[]
    try:
        value=response.headers.get('retry-after','')
        delay=float(value) if value else 0
    except ValueError:
        try:delay=max(0,parsedate_to_datetime(value).timestamp()-now)
        except (ValueError,TypeError):pass
    try:error=response.json().get('error',{})
    except (ValueError,AttributeError):error={}
    details=error.get('details',[]) if isinstance(error,dict) else []
    for row in details if isinstance(details,list) else []:
        if not isinstance(row,dict):continue
        if row.get('@type','').endswith('RetryInfo'):
            try:delay=max(delay,float(str(row.get('retryDelay','')).removesuffix('s')))
            except ValueError:pass
        if row.get('@type','').endswith('QuotaFailure'):
            violations=row.get('violations',[])
            for violation in violations if isinstance(violations,list) else []:
                if not isinstance(violation,dict):continue
                # Whitelist schema fields, not provider messages or request data.
                dimensions.append({k:str(violation[k])[:180] for k in ('quotaMetric','quotaId','quotaValue') if k in violation})
    if response.status_code==429 and not delay:
        if any('day' in r.get('quotaId','').lower() for r in dimensions):
            try:
                pacific=datetime.fromtimestamp(now,ZoneInfo('America/Los_Angeles'))
                delay=(pacific+timedelta(days=1)).replace(hour=0,minute=0,second=1,microsecond=0).timestamp()-now
            except (ValueError,KeyError):delay=86400
        else:delay=60
    if response.status_code in (401,403):delay=max(delay,900)
    elif response.status_code>=500:delay=max(delay,5)
    return min(7*86400,max(0,delay if math.isfinite(delay) else 60)),dimensions

class GatewayLimited(Exception):
    def __init__(self,seconds):self.seconds=max(1,math.ceil(seconds))

class GoogleGatewayLimits:
    def __init__(self,path,clock=time.time):
        self.path=str(path);self.clock=clock;self.lock=asyncio.Lock();self.busy=set();self.changed=asyncio.Event();self.cursor=0
        Path(path).parent.mkdir(parents=True,exist_ok=True)
        with closing(sqlite3.connect(self.path)) as db,db:
            db.executescript('''CREATE TABLE IF NOT EXISTS calls(id INTEGER PRIMARY KEY,credential TEXT,project TEXT,model TEXT,at REAL,status INTEGER,input_tokens INTEGER,output_tokens INTEGER);
            CREATE INDEX IF NOT EXISTS calls_window ON calls(project,model,at);
            CREATE TABLE IF NOT EXISTS health(scope TEXT,model TEXT,until REAL,status INTEGER,at REAL,quotas TEXT,PRIMARY KEY(scope,model));''')
        Path(path).chmod(0o600)

    def delay(self,row,model):
        now=self.clock();group=project(row);credential=identity(row['key'])
        with closing(sqlite3.connect(self.path)) as db:
            times=[r[0] for r in db.execute('SELECT at FROM calls WHERE project=? AND model=? AND at>? ORDER BY at',(group,model,now-60))]
            limited=db.execute('SELECT MAX(until) FROM health WHERE scope IN (?,?) AND model=?',(group,credential,model)).fetchone()[0] or 0
        return max(0,limited-now,times[-1]+4-now if times else 0,times[-15]+60-now if len(times)>=15 else 0)

    async def acquire(self,rows,model,preferred=None,on_wait=lambda seconds:None,disconnected=None,max_wait=90):
        start=time.monotonic()
        while True:
            if disconnected and await disconnected():raise asyncio.CancelledError()
            async with self.lock:
                self.changed.clear();ordered=rows[self.cursor%len(rows):]+rows[:self.cursor%len(rows)]
                ordered.sort(key=lambda r:r.get('slot')!=preferred if preferred is not None else False)
                waits=[]
                for row in ordered:
                    delay=self.delay(row,model);waits.append(delay)
                    credential=identity(row['key'])
                    if delay>0 or credential in self.busy or len(self.busy)>=3:continue
                    self.busy.add(credential);self.cursor=(rows.index(row)+1)%len(rows)
                    with closing(sqlite3.connect(self.path)) as db,db:
                        db.execute('DELETE FROM calls WHERE at<?',(self.clock()-86400,))
                        call=db.execute('INSERT INTO calls(credential,project,model,at) VALUES(?,?,?,?)',(credential,project(row),model,self.clock())).lastrowid
                    return row,call
            seconds=min(waits) if waits else 1
            if seconds>max_wait or time.monotonic()-start>=max_wait:raise GatewayLimited(seconds)
            on_wait(max(1,math.ceil(seconds)))
            try:await asyncio.wait_for(self.changed.wait(),timeout=min(1,max(.05,seconds)))
            except asyncio.TimeoutError:pass

    def finish(self,row,model,call,status,usage=None,response=None):
        now=self.clock();credential=identity(row['key']);usage=usage or {};delay,quotas=provider_limit(response,now) if response is not None else (0,[])
        try:
            with closing(sqlite3.connect(self.path)) as db,db:
                db.execute('UPDATE calls SET status=?,input_tokens=?,output_tokens=? WHERE id=?',(status,usage.get('promptTokenCount'),usage.get('candidatesTokenCount'),call))
                scope=project(row) if status==429 else credential
                previous=db.execute('SELECT until FROM health WHERE scope=? AND model=?',(scope,model)).fetchone()
                until=max(now+delay,previous[0] if previous and previous[0]>now else 0)
                db.execute('INSERT OR REPLACE INTO health VALUES(?,?,?,?,?,?)',(scope,model,until,status,now,json.dumps(quotas)))
        finally:
            self.busy.discard(credential);self.changed.set()

    def snapshot(self,row):
        now=self.clock();credential=identity(row['key']);group=project(row);models={}
        with closing(sqlite3.connect(self.path)) as db:
            names={r[0] for r in db.execute('SELECT DISTINCT model FROM calls WHERE credential=? AND at>?',(credential,now-86400))}
            names.update(r[0] for r in db.execute('SELECT model FROM health WHERE scope IN (?,?)',(credential,group)))
            for model in sorted(names):
                n,tokens,out=db.execute('SELECT COUNT(*),SUM(input_tokens),SUM(output_tokens) FROM calls WHERE project=? AND model=? AND at>?',(group,model,now-60)).fetchone()
                health=db.execute('SELECT until,status,at,quotas FROM health WHERE scope IN (?,?) AND model=? ORDER BY at DESC',(credential,group,model)).fetchall()
                models[model]={'requestsLastMinute':n,'rpmBudget':15,'remainingRequestsEstimate':max(0,15-n),'inputTokensLastMinute':tokens or 0,'outputTokensLastMinute':out or 0,'cooldownSeconds':max(0,math.ceil(max((r[0] for r in health),default=0)-now)),'nextRequestSeconds':math.ceil(self.delay(row,model)),'lastHttpStatus':health[0][1] if health else None,'lastResponseAt':health[0][2] if health else None,'providerQuotas':[q for r in health for q in json.loads(r[3])],'budgetSource':'server-policy','providerRemaining':None}
        return {'inFlight':credential in self.busy,'models':models}
