#!/usr/bin/env python3
"""Permit owner-authenticated vision requests without widening other routes."""
from pathlib import Path
import json,os,subprocess,time

def configuration(original):
 if 'handle /reader/google/generate' in original or '@readerGoogle path /reader/google/generate' in original:return original
 if '    handle /reader/lmt/* {' in original:
  route='''    handle /reader/google/generate {
        request_body {
            max_size 20MB
        }
        reverse_proxy importer:7860
    }
'''
  return original.replace('    handle /reader/lmt/* {',route+'    handle /reader/lmt/* {',1)
 if '    @lmt path /reader/lmt/*' in original:
  route='''    @readerGoogle path /reader/google/generate
    request_body @readerGoogle {
        max_size 20MB
    }
    reverse_proxy @readerGoogle importer:7860
'''
  return original.replace('    @lmt path /reader/lmt/*',route+'    @lmt path /reader/lmt/*',1)
 raise RuntimeError('Unknown Caddy layout; existing configuration untouched')

def main():
 inspect=json.loads(subprocess.check_output(['docker','inspect','oracle-https-1']))[0]
 path=Path(next(m['Source'] for m in inspect['Mounts'] if m['Destination']=='/etc/caddy/Caddyfile'))
 original=path.read_text();updated=configuration(original)
 if updated==original:print('Google route already configured');return
 backup=path.with_name('Caddyfile-before-google-'+time.strftime('%Y%m%dT%H%M%SZ',time.gmtime()));backup.write_text(original);backup.chmod(0o600)
 try:
  path.write_text(updated)
  for command in ['validate','reload']:subprocess.run(['docker','exec','oracle-https-1','caddy',command,'--config','/etc/caddy/Caddyfile'],check=True,capture_output=True)
 except BaseException:
  path.write_text(original);subprocess.run(['docker','exec','oracle-https-1','caddy','reload','--config','/etc/caddy/Caddyfile'],capture_output=True);raise
 print('Reader Google route configured; other request limits retained')

if __name__=='__main__':main()
