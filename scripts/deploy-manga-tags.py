#!/usr/bin/env python3
"""Validate and send only the committed taxonomy to its scoped Oracle endpoint."""
from pathlib import Path
import hashlib,hmac,json,os,re,sys,time,urllib.request,urllib.error
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server'))
from manga_tag_policy import Policy,canonical_json

def main():
    policy=Policy(json.loads(Path('server/manga-tag-policy.json').read_text(encoding='utf-8')))
    if '--validate' in sys.argv:
        print('Validated',len(policy.rules),'canonical tags; revision',policy.revision);return
    address=os.environ['MANGA_ORACLE_URL'].rstrip('/')
    if not re.fullmatch(r'https://[a-zA-Z0-9.-]+',address):raise SystemExit('Expected an HTTPS Oracle origin')
    key=os.environ.get('MANGA_TAG_DEPLOY_KEY','').encode()
    if len(key)<32:raise SystemExit('Configure the scoped MANGA_TAG_DEPLOY_KEY repository secret')
    body={'commit':os.environ['GITHUB_SHA'],'policy':policy.data}
    timestamp=str(int(time.time()));raw=canonical_json(body)
    signature=hmac.new(key,timestamp.encode()+b'.'+raw,hashlib.sha256).hexdigest()
    request=urllib.request.Request(address+'/ops/manga-tags/update',data=raw,headers={
        'Content-Type':'application/json','X-MediaVault-Timestamp':timestamp,'X-MediaVault-Signature':signature},method='POST')
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request,timeout=120) as response:result=json.load(response)
            break
        except urllib.error.HTTPError as error:
            if error.code not in (409,502,503,504) or attempt==2:
                raise SystemExit('Oracle taxonomy update failed with HTTP '+str(error.code)) from None
        except urllib.error.URLError:
            if attempt==2:raise SystemExit('Oracle taxonomy update connection failed') from None
        time.sleep(5*(attempt+1))
    assert result.get('applied') and result.get('revision')==policy.revision,'Oracle did not confirm the expected policy'
    with urllib.request.urlopen(address+'/manga/tag-policy',timeout=20) as response:active=json.load(response)
    assert active.get('revision')==policy.revision,'Public Oracle policy revision mismatch'
    print(json.dumps({key:result[key] for key in ('applied','unchanged','revision','commit','reindexedTitles') if key in result}))

if __name__=='__main__':main()
