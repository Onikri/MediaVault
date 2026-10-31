/** Readable rewrite of common-DmQO_PZF.js: original source ID helpers. */
export function extractYouTubeId(source?: string | null): string | null {
  if (!source) return null;
  const clean = source.replace(/\\/g, '');
  const match = clean.match(/\/embed\/([^?&/]+)/) || clean.match(/[?&]v=([^&]+)/) || clean.match(/youtu\.be\/([^?&/]+)/);
  return match?.[1] ?? null;
}
export function buildTrailerUrl(id: string | null, options:{autoplay?:boolean;mute?:boolean;loop?:boolean;controls?:boolean;enablejsapi?:boolean}={}):string|null {
  if(!id) return null;
  const params = new URLSearchParams({
    autoplay: options.autoplay === false ? '0' : '1',
    mute: options.mute === false ? '0' : '1',
    loop: options.loop === false ? '0' : '1',
    controls: options.controls ? '1' : '0',
    modestbranding:'1', rel:'0', iv_load_policy:'3', playsinline:'1',
    enablejsapi: options.enablejsapi === false ? '0' : '1',
  });
  if(options.loop !== false) params.set('playlist',id);
  return `https://www.youtube.com/embed/${encodeURIComponent(id)}?${params.toString()}`;
}
export function issueYouTubeCommand(iframe:HTMLIFrameElement|null, command:'pauseVideo'|'playVideo'|'mute'|'unMute') {
  iframe?.contentWindow?.postMessage(JSON.stringify({event:'command',func:command,args:[]}), 'https://www.youtube.com');
}
