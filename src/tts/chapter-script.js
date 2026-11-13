// The narration script of one chapter, exactly as the reader voices it: the
// title bible (studyBook), the director's role pass (analyseChapter, Lite or
// Gemma through the server pool), the cast and the listener's own voice
// choices (castVoices → geminiCast) and the Gemini rows (geminiRows). The
// reader's Narration panel, the save window's device audiobook and the VM's
// Drive audiobook (narration-export.html in headless Chromium) all call this,
// so a chapter has the same voices and segmentation wherever it is saved.
import {heuristicRoles,ROLE_MODEL} from './roles.js';
import {analyseChapter,studyBook,adoptBible,latestBible} from './director.js';
import {castVoices,savedCast} from './voices.js';
import {savedBible,applyLexicon} from './bible.js';
import {ROLE_MODELS,BIBLE_MODELS} from './google.js';
import {geminiCast,geminiNarrator,geminiRows,savedGeminiCast} from './gemini-voice.js';

export const PREFS='mediavault_tts_prefs_v2';
export const DEFAULTS={engine:'gemini',geminiNarrator:'auto',pace:1,narrator:'auto',roles:true,rolesModel:ROLE_MODEL,bibleModel:'gemini-3.5-flash-lite'};
// Only models offered in the panel are kept (non-Lite Flash is never used).
export function cleanPrefs(value){
 const prefs={...DEFAULTS,...(value&&typeof value==='object'?value:{})};
 if(!BIBLE_MODELS.some(([id])=>id===prefs.bibleModel))prefs.bibleModel=DEFAULTS.bibleModel;
 if(!ROLE_MODELS.some(([id])=>id===prefs.rolesModel))prefs.rolesModel=DEFAULTS.rolesModel;
 return prefs;
}
export function readPrefs(){try{return cleanPrefs(JSON.parse(localStorage.getItem(PREFS)||'{}'));}catch{return {...DEFAULTS};}}

// What the reader on this device knows about a book's voices: sent with a
// Drive job so the VM voices it the same way.
export function bookDirection(bookKey){
 const prefs=readPrefs();
 return {prefs:{geminiNarrator:prefs.geminiNarrator,narrator:prefs.narrator,pace:prefs.pace,roles:prefs.roles,rolesModel:prefs.rolesModel,bibleModel:prefs.bibleModel},
  saved:savedGeminiCast(bookKey),cast:savedCast(bookKey),bible:latestBible(bookKey)||savedBible(bookKey)};
}

// → {rows, bible, analysis: 'model'|'partial'|'heuristic'|'failed', stats}.
// meta: {title, aliases, authors, description, year, kind, language}.
export async function chapterScript({paragraphs,bookKey,chapterKey,meta,service,userId,direction=null}){
 const own=direction||bookDirection(bookKey),prefs=cleanPrefs(own.prefs);
 let bible=latestBible(bookKey)||savedBible(bookKey)||own.bible||null;
 if(bible)adoptBible(bookKey,bible);
 if(prefs.roles&&service&&!bible&&paragraphs.length){
  bible=await studyBook({bookKey,meta,sample:paragraphs.join('\n'),service,userId,model:prefs.bibleModel}).catch(()=>null);
 }
 let segments=heuristicRoles(paragraphs),characters=[],analysis='heuristic',stats=null;
 if(prefs.roles&&service&&paragraphs.length){
  const value=await analyseChapter({paragraphs,bookKey,chapterKey,bible,meta,service,userId,model:prefs.rolesModel,start:0,onUpdate:null,onBible:next=>{bible=next;}});
  segments=value.segments;characters=value.characters||[];stats=value.stats||null;
  analysis=!stats?.failed?'model':stats.failed>=stats.parts?'failed':'partial';
  bible=latestBible(bookKey)||bible;
 }
 const spoken=segments.map(s=>({...s,spoken:applyLexicon(s.text,bible)}));
 const cast=castVoices(segments,characters,{narrator:prefs.narrator,saved:own.cast||{},bible});
 const narrator=geminiNarrator(bible,prefs.geminiNarrator),saved=own.saved||{};
 const voices=geminiCast(cast,{narrator,saved,self:bible?.narratorName});
 const rows=geminiRows(spoken,{cast,voices,narrator,bible,pace:prefs.pace,saved});
 return {rows,bible,analysis,stats};
}
