// Picking another voice while an episode plays.
//
// A voice from another balancer (Alloha, Kodik, Collaps…) is another stream:
// the viewer loads it and the player continues from the same second. Voices of
// one Collaps embed share one HLS that carries every dub as an audio rendition,
// so between them only the audio track changes and nothing is reloaded.
import {collapsSelection} from './collaps-direct.js';

// Entries with equal keys play one media stream and differ only by audio.
export function streamKey(url){
 const selection=collapsSelection(url);
 if(!selection)return String(url||'');
 return 'collaps:'+selection.embed+'|'+(selection.season??'')+'|'+(selection.episode??'');
}

// The audio rendition that plays `url` inside the already loaded stream, or ''
// when `url` needs its own stream.
export function inStreamAudio(media,url){
 if(!media?.direct||!media.audioNames?.length||streamKey(media.entry?.url)!==streamKey(url))return '';
 const index=collapsSelection(url)?.audio;
 return index!=null&&index>=0&&index<media.audioNames.length?media.audioNames[index]:'';
}

// The loaded media can stay: same request, or another dub of the same stream.
export function keepsLoadedMedia(media,request){
 const loaded=media?.request;
 if(!loaded||loaded.quality!==request.quality||loaded.retry!==request.retry||loaded.server!==request.server)return false;
 if(loaded.url===request.url)return loaded.sourceUrl===request.sourceUrl;
 return !!inStreamAudio(media,request.url);
}

// The page has a new voice, but the player still plays the previous voice's
// stream: show that it is loading, or why it failed. In the "best video from
// every voice" mode the video's voice differs on purpose and the chosen voice
// arrives as separate audio, so nothing is pending there.
export function voiceSwitchState({playing,bestVideo,voiceId,loadedVoiceId,busy,error}){
 if(!playing||bestVideo||!voiceId||!loadedVoiceId||voiceId===loadedVoiceId)return null;
 return error&&!busy?{phase:'failed',message:error}:{phase:'loading',message:''};
}
