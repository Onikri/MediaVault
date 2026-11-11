"""Observed Google usage and durable cooldowns. Never stores raw credentials.

RPM is a local admission budget, not a claim about the project's Google balance.
Only Google-reported quota dimensions and retry delays are provider facts.
"""
import asyncio,hashlib,json,math,random,sqlite3,time
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

# Admission budgets per project and model (free tier): requests per minute,
# input tokens per minute, requests per Pacific day. This is server policy;
# when Google answers 429 with a QuotaFailure quotaValue, that number replaces
# the matching budget for the project and model (stored, survives restarts).
BUDGETS={'gemini-3.5-flash-lite':(15,250000,1000),'gemini-3.1-flash-lite':(15,250000,1000),'gemini-2.5-flash-lite':(15,250000,1000),
         'gemma-4-26b-a4b-it':(30,15000,14400),'gemma-4-31b-it':(30,15000,14400)}
DEFAULT_BUDGET=(10,100000,500)
GAP=1.0        # seconds between two admissions for one project and model
PER_KEY=2      # requests in flight on one key; a pinned (manga) slot keeps one
MAX_FLIGHT=6   # requests in flight through the whole gateway

def estimate(request):
    """Input tokens of a request body before sending (Cyrillic JSON is about 3.8 characters per token)."""
    return int(len(json.dumps(request,ensure_ascii=False))/3.5)+1

def pacific_day(now):
    try:
        day=datetime.fromtimestamp(now,ZoneInfo('America/Los_Angeles')).replace(hour=0,minute=0,second=0,microsecond=0)
        return day.timestamp(),(day+timedelta(days=1)).timestamp()
    except (ValueError,KeyError):
        return now-now%86400,now-now%86400+86400

def learned_limit(quota):
    """('rpm'|'tpm'|'rpd', value) from one QuotaFailure violation, or None."""
    name=(quota.get('quotaId','')+' '+quota.get('quotaMetric','')).lower()
    try:value=int(float(quota.get('quotaValue','')))
    except ValueError:return None
    if value<=0:return None
    if 'token' in name and 'minute' in name:return 'tpm',value
    if 'request' in name and 'minute' in name:return 'rpm',value
    if 'request' in name and 'day' in name:return 'rpd',value
    return None

class GatewayLimited(Exception):
    def __init__(self,seconds):self.seconds=max(1,math.ceil(seconds))

class GoogleGatewayLimits:
    def __init__(self,path,clock=time.time):
        self.path=str(path);self.clock=clock;self.lock=asyncio.Lock();self.busy={};self.changed=asyncio.Event();self.cursor=0
        Path(path).parent.mkdir(parents=True,exist_ok=True)
        with closing(sqlite3.connect(self.path)) as db,db:
            db.executescript('''CREATE TABLE IF NOT EXISTS calls(id INTEGER PRIMARY KEY,credential TEXT,project TEXT,model TEXT,at REAL,status INTEGER,input_tokens INTEGER,output_tokens INTEGER);
            CREATE INDEX IF NOT EXISTS calls_window ON calls(project,model,at);
            CREATE TABLE IF NOT EXISTS health(scope TEXT,model TEXT,until REAL,status INTEGER,at REAL,quotas TEXT,PRIMARY KEY(scope,model));
            CREATE TABLE IF NOT EXISTS learned(project TEXT,model TEXT,kind TEXT,value INTEGER,at REAL,PRIMARY KEY(project,model,kind));
            CREATE TABLE IF NOT EXISTS admissions(project TEXT,model TEXT,next_at REAL,PRIMARY KEY(project,model));''')
        Path(path).chmod(0o600)

    def budget(self,db,group,model):
        rpm,tpm,rpd=BUDGETS.get(model,DEFAULT_BUDGET);values={'rpm':rpm,'tpm':tpm,'rpd':rpd}
        for kind,value in db.execute('SELECT kind,value FROM learned WHERE project=? AND model=?',(group,model)):values[kind]=value
        return values

    def delay(self,row,model,tokens=0):
        now=self.clock();group=project(row);credential=identity(row['key'])
        with closing(sqlite3.connect(self.path)) as db:
            window=db.execute('SELECT at,COALESCE(input_tokens,0) FROM calls WHERE project=? AND model=? AND at>? ORDER BY at',(group,model,now-60)).fetchall()
            limited=db.execute('SELECT MAX(until) FROM health WHERE scope IN (?,?) AND model=?',(group,credential,model)).fetchone()[0] or 0
            budget=self.budget(db,group,model);day_start,day_end=pacific_day(now)
            admission=db.execute('SELECT next_at FROM admissions WHERE project=? AND model=?',(group,model)).fetchone()
            today=db.execute('SELECT COUNT(*) FROM calls WHERE project=? AND model=? AND at>=?',(group,model,day_start)).fetchone()[0]
        waits=[limited-now]
        if admission:waits.append(admission[0]-now)
        if window:waits.append(window[-1][0]+GAP-now)
        if len(window)>=budget['rpm']:waits.append(window[-budget['rpm']][0]+60-now)
        used=sum(t for _,t in window)
        # A request larger than the whole budget still goes once the minute is empty.
        if tokens and window and used+tokens>budget['tpm']:
            need=used+tokens-budget['tpm'];freed=0
            for at,t in window:
                freed+=t
                if freed>=need:waits.append(at+60-now);break
            else:waits.append(window[-1][0]+60-now)
        if today>=budget['rpd']:waits.append(day_end-now)
        return max(0,*waits)

    async def acquire(self,rows,model,preferred=None,on_wait=lambda seconds:None,disconnected=None,max_wait=90,tokens=0):
        start=time.monotonic();per_key=1 if preferred is not None else PER_KEY
        while True:
            if disconnected and await disconnected():raise asyncio.CancelledError()
            async with self.lock:
                self.changed.clear();ordered=rows[self.cursor%len(rows):]+rows[:self.cursor%len(rows)]
                # The pinned slot first; otherwise the least busy key, then rotation.
                ordered.sort(key=lambda r:(r.get('slot')!=preferred if preferred is not None else False,self.busy.get(identity(r['key']),0)))
                waits=[]
                for row in ordered:
                    delay=self.delay(row,model,tokens);waits.append(delay)
                    credential=identity(row['key'])
                    if delay>0 or self.busy.get(credential,0)>=per_key or sum(self.busy.values())>=MAX_FLIGHT:continue
                    self.busy[credential]=self.busy.get(credential,0)+1;self.cursor=(rows.index(row)+1)%len(rows)
                    with closing(sqlite3.connect(self.path)) as db,db:
                        db.execute('DELETE FROM calls WHERE at<?',(self.clock()-86400*2,))
                        call=db.execute('INSERT INTO calls(credential,project,model,at,input_tokens) VALUES(?,?,?,?,?)',(credential,project(row),model,self.clock(),tokens or None)).lastrowid
                        # Stagger starts within a project while its RPM/TPM budget
                        # and Google Retry-After remain the admission constraints.
                        if row.get('subscription'):
                            next_at=self.clock()+GAP+random.uniform(0,.5)
                            db.execute('INSERT OR REPLACE INTO admissions VALUES(?,?,?)',(project(row),model,next_at))
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
                db.execute('UPDATE calls SET status=?,input_tokens=COALESCE(?,input_tokens),output_tokens=? WHERE id=?',(status,usage.get('promptTokenCount'),usage.get('candidatesTokenCount'),call))
                scope=project(row) if status==429 else credential
                previous=db.execute('SELECT until FROM health WHERE scope=? AND model=?',(scope,model)).fetchone()
                until=max(now+delay,previous[0] if previous and previous[0]>now else 0)
                db.execute('INSERT OR REPLACE INTO health VALUES(?,?,?,?,?,?)',(scope,model,until,status,now,json.dumps(quotas)))
                for quota in quotas if status==429 else []:
                    limit=learned_limit(quota)
                    if limit:db.execute('INSERT OR REPLACE INTO learned VALUES(?,?,?,?,?)',(project(row),model,limit[0],limit[1],now))
        finally:
            left=self.busy.get(credential,0)-1
            if left>0:self.busy[credential]=left
            else:self.busy.pop(credential,None)
            self.changed.set()

    def snapshot(self,row):
        now=self.clock();credential=identity(row['key']);group=project(row);models={}
        with closing(sqlite3.connect(self.path)) as db:
            names={r[0] for r in db.execute('SELECT DISTINCT model FROM calls WHERE credential=? AND at>?',(credential,now-86400))}
            names.update(r[0] for r in db.execute('SELECT model FROM health WHERE scope IN (?,?)',(credential,group)))
            for model in sorted(names):
                n,tokens,out=db.execute('SELECT COUNT(*),SUM(input_tokens),SUM(output_tokens) FROM calls WHERE project=? AND model=? AND at>?',(group,model,now-60)).fetchone()
                health=db.execute('SELECT until,status,at,quotas FROM health WHERE scope IN (?,?) AND model=? ORDER BY at DESC',(credential,group,model)).fetchall()
                budget=self.budget(db,group,model);today=db.execute('SELECT COUNT(*) FROM calls WHERE project=? AND model=? AND at>=?',(group,model,pacific_day(now)[0])).fetchone()[0]
                models[model]={'requestsLastMinute':n,'rpmBudget':budget['rpm'],'tpmBudget':budget['tpm'],'rpdBudget':budget['rpd'],'requestsToday':today,'remainingRequestsEstimate':max(0,budget['rpm']-n),'inputTokensLastMinute':tokens or 0,'outputTokensLastMinute':out or 0,'cooldownSeconds':max(0,math.ceil(max((r[0] for r in health),default=0)-now)),'nextRequestSeconds':math.ceil(self.delay(row,model)),'lastHttpStatus':health[0][1] if health else None,'lastResponseAt':health[0][2] if health else None,'providerQuotas':[q for r in health for q in json.loads(r[3])],'budgetSource':'server-policy','providerRemaining':None}
        return {'inFlight':credential in self.busy,'models':models}
