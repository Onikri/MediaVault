#!/usr/bin/env python3
"""Run manually in the owner's Cloud Shell to enable narrow, expiring SSH.

Preserves existing keys and network rules. Installs no software, copies no cloud
credentials and creates no cloud resource. Uses the existing Instance Agent helper.
"""
import argparse,base64,datetime,ipaddress,json,os,re,shlex,subprocess,sys,time
from pathlib import Path

def main():
 parser=argparse.ArgumentParser(description=__doc__)
 parser.add_argument('--public-key',required=True);parser.add_argument('--client-ip',required=True)
 parser.add_argument('--server',default='141.144.225.42')
 args=parser.parse_args();client=str(ipaddress.IPv4Address(args.client_ip));server=str(ipaddress.IPv4Address(args.server))
 assert re.fullmatch(r'ssh-ed25519 [A-Za-z0-9+/=]+(?: [A-Za-z0-9_.-]+)?',args.public_key),'Invalid public key'
 helper=Path.home()/'mediavault-suwayomi-agent.py';assert helper.is_file(),'Existing MediaVault Cloud Shell agent helper not found'
 private=Path.home()/'.mediavault-ssh';private.mkdir(mode=0o700,exist_ok=True);os.chmod(private,0o700)
 def cli(*values):return json.loads(subprocess.check_output(['oci',*values,'--output','json'],text=True))
 public=cli('network','public-ip','get','--public-ip-address',server)['data']
 address=cli('network','private-ip','get','--private-ip-id',public['private-ip-id'])['data']
 vnic=cli('network','vnic','get','--vnic-id',address['vnic-id'])['data']
 subnet=cli('network','subnet','get','--subnet-id',vnic['subnet-id'])['data']
 # Add one /32 SSH rule, retaining every existing ingress and egress rule.
 identity=subnet['security-list-ids'][0]
 response=cli('network','security-list','get','--security-list-id',identity)
 old=response['data']['ingress-security-rules'];description='MediaVault device SSH '+client
 def camel(value):
  if isinstance(value,list):return [camel(v) for v in value]
  if isinstance(value,dict):return {re.sub(r'-([a-z])',lambda m:m[1].upper(),k):camel(v) for k,v in value.items() if v is not None}
  return value
 if not any(r.get('description')==description for r in old):
  backup=private/('security-list-'+time.strftime('%Y%m%dT%H%M%SZ',time.gmtime())+'.json');backup.write_text(json.dumps(response));backup.chmod(0o600)
  rule={'source':client+'/32','sourceType':'CIDR_BLOCK','protocol':'6','isStateless':False,'description':description,'tcpOptions':{'destinationPortRange':{'min':22,'max':22}}}
  options=['network','security-list','update','--security-list-id',identity,'--ingress-security-rules',json.dumps([*camel(old),rule]),'--force']
  if response.get('etag'):options+=['--if-match',response['etag']]
  cli(*options)
 print('SSH ingress limited to '+client+'/32; existing network rules retained.',flush=True)
 expires=(datetime.datetime.now(datetime.timezone.utc)+datetime.timedelta(days=7)).strftime('%Y%m%d%H%M%SZ')
 authorized='from="'+client+'",restrict,pty,expiry-time="'+expires+'" '+args.public_key
 code='''from pathlib import Path
import os,pwd,subprocess
owner=pwd.getpwnam('ubuntu');directory=Path(owner.pw_dir)/'.ssh';directory.mkdir(mode=0o700,exist_ok=True);os.chown(directory,owner.pw_uid,owner.pw_gid);directory.chmod(0o700)
target=directory/'authorized_keys';before=target.read_text() if target.exists() else ''
line=AUTHORIZED_LINE
if line not in before.splitlines():
 with target.open('a') as output:output.write(('' if not before or before.endswith('\\n') else '\\n')+line+'\\n')
os.chown(target,owner.pw_uid,owner.pw_gid);target.chmod(0o600)
subprocess.run(['/usr/sbin/sshd','-t'],check=True)
subprocess.run(['systemctl','start','ssh'],check=True)
rule=['-p','tcp','-s',CLIENT_CIDR,'--dport','22','-j','ACCEPT']
if subprocess.run(['iptables','-C','INPUT',*rule],capture_output=True).returncode:subprocess.run(['iptables','-I','INPUT','1',*rule],check=True)
print('SSH_READY ubuntu@SERVER_ADDRESS; device key expires EXPIRES')
print('HOST_KEY '+Path('/etc/ssh/ssh_host_ed25519_key.pub').read_text().strip())
'''.replace('AUTHORIZED_LINE',repr(authorized)).replace('CLIENT_CIDR',repr(client+'/32')).replace('SERVER_ADDRESS',server).replace('EXPIRES',expires)
 shell='sudo -n python3 -c '+shlex.quote(code)
 job='device-ssh-'+str(int(time.time()))
 subprocess.run([sys.executable,str(helper),'submit',job,base64.b64encode(shell.encode()).decode()],check=True)
 print('Waiting for the existing VM agent. This can take several minutes.',flush=True)
 for _ in range(45):
  time.sleep(15)
  result=subprocess.run([sys.executable,str(helper),'poll',job],capture_output=True,text=True)
  try:value=json.loads(result.stdout)
  except ValueError:continue
  if value.get('state') in ['SUCCEEDED','FAILED','TIMED_OUT','CANCELED']:
   content=value.get('content') or {};print(content.get('text') or json.dumps(value),flush=True)
   if value['state']!='SUCCEEDED':raise SystemExit('SSH bootstrap did not finish; send the output for diagnosis')
   return
 print('Still queued. To retrieve the result: python3 '+str(helper)+' poll '+job)

if __name__=='__main__':main()
