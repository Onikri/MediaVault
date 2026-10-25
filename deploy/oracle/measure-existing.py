"""Inspect and benchmark an existing VM through an authorized Oracle Cloud Shell.

No SSH/API key creation, VM provisioning or plan changes. The supplied script
runs through the VM's already-enabled Run Command agent.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import subprocess
import time


def oci(arguments, region):
    response=subprocess.run(['oci','--region',region,'--output','json','--query','@',*arguments],capture_output=True,text=True,timeout=100)
    if response.returncode:
        raise RuntimeError('OCI request failed: '+' '.join(arguments[:3]))
    return json.loads(response.stdout)['data']


def submit(script, region='eu-frankfurt-1'):
    resources=oci(['search','resource','structured-search','--query-text',"query instance resources where displayName = 'mediavault-import' && lifecycleState = 'RUNNING'"],region)
    instances=resources.get('items',[])
    if len(instances)!=1:
        raise RuntimeError('Expected one existing running mediavault-import instance')
    instance=oci(['compute','instance','get','--instance-id',instances[0]['identifier']],region)
    plugins=(instance.get('agent-config') or {}).get('plugins-config') or []
    if not any(p.get('name')=='Compute Instance Run Command' and p.get('desired-state')=='ENABLED' for p in plugins):
        raise RuntimeError('Existing Run Command agent is not enabled; no settings changed')
    print(json.dumps({'shape':instance['shape'],'shapeConfig':instance.get('shape-config'),'region':region}),flush=True)
    content={'source':{'sourceType':'TEXT','text':script},'output':{'outputType':'TEXT'}}
    created=oci(['instance-agent','command','create','--compartment-id',instance['compartment-id'],
                 '--target',json.dumps({'instanceId':instance['id']}),'--content',json.dumps(content),
                 '--timeout-in-seconds','1200','--display-name','MediaVault reader measurements'],region)
    state={'commandId':created['id'],'instanceId':instance['id'],'region':region}
    return state


def inspect(state):
    response=oci(['instance-agent','command-execution','get','--command-id',state['commandId'],'--instance-id',state['instanceId']],state['region'])
    result={'state':response['lifecycle-state']}
    content=response.get('content') or {}
    if isinstance(content,dict):
        result['output']=content.get('text','')
        result['exitCode']=content.get('exit-code',content.get('exitCode'))
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--script',type=Path)
    parser.add_argument('--state',type=Path,default=Path('mediavault-measurement.json'))
    parser.add_argument('--poll',action='store_true')
    args=parser.parse_args()
    if args.poll:
        print(json.dumps(inspect(json.loads(args.state.read_text())),ensure_ascii=False),flush=True)
    else:
        if not args.script:parser.error('--script is required')
        state=submit(args.script.read_text())
        args.state.write_text(json.dumps(state))
        print(json.dumps(state),flush=True)


if __name__=='__main__':main()
