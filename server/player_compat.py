"""Compatibility fixes around the pinned public-player implementations."""
import base64
import re
from urllib.parse import urljoin,urlsplit
from bs4 import BeautifulSoup
from anime_dl_core import KodikPlayer as ReferenceKodikPlayer
from anime_dl_core.errors import ExtractionError


class KodikPlayer(ReferenceKodikPlayer):
    @staticmethod
    def _parse_post_path(script,script_url):
        # Parse the named URL field, never fixed byte offsets or arbitrary atob calls.
        candidates=[]
        for _ in range(3):
            for match in re.finditer(r'''(?:\burl|["']url["'])\s*:\s*(?:window\.)?atob\(\s*["']([A-Za-z0-9+/=]{4,100})["']\s*\)''',script):
                try:path=base64.b64decode(match[1],validate=True).decode('ascii')
                except (ValueError,UnicodeError):continue
                if re.fullmatch(r'/[a-zA-Z0-9_-]{1,40}',path):candidates.append(path)
            if candidates:break
            script=script.replace('\\"','"').replace("\\'", "'")
        paths=set(candidates)
        if len(paths)!=1:raise ExtractionError('Kodik: no unambiguous same-origin playback endpoint in the published player script.')
        return paths.pop()

    def _parse_page(self,text,url):
        info=ReferenceKodikPlayer._parse_page(text,url)
        paths=[]
        for tag in BeautifulSoup(text,'html.parser').select('script[src]'):
            target=urlsplit(urljoin(url,tag['src']))
            if target.hostname!=urlsplit(url).hostname or target.username or target.password:continue
            if not re.fullmatch(r'/assets/js/[a-zA-Z0-9._/-]+\.js',target.path) or '..' in target.path.split('/'):continue
            path=target.path+('?' + target.query if target.query else '')
            if path not in paths:paths.append(path)
        if info['script_path'] not in paths:paths.append(info['script_path'])
        # Modern embeds split the renderer and playback request into separate assets.
        for path in paths[:8]:
            script_url=self._absolute(url,path)
            if script_url not in self._post_path_cache:
                script=self.client.get(script_url,headers={'Referer':url}).raise_for_status().text
                try:self._post_path_cache[script_url]=self._parse_post_path(script,script_url)
                except ExtractionError:continue
            info['script_path']=path
            return info
        raise ExtractionError('Kodik: playback endpoint was not found in the published scripts; no video URL was fabricated.')
