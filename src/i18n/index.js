// Interface language for this device. Russian is the source language of the
// code; Ukrainian is applied by translating rendered interface text in place.
// Content (book prose, titles, synopses, chat, lyrics, manga dialogue) sits under
// translate="no" and is never touched.
import {createTranslator} from './translate.js';

export const UI_LANGUAGES=[['ru','Русский','ru-RU'],['uk','Українська','uk-UA']];
const KEY='mediavault_ui_language_v1';
const ATTRIBUTES=['aria-label','title','placeholder','alt','aria-description','aria-roledescription','aria-valuetext'];
const SKIP=new Set(['SCRIPT','STYLE','NOSCRIPT','TEXTAREA','CODE','PRE','svg','math']);
const listeners=new Set();
let language=readLanguage(),translator=null,observer=null,loading=null;
const texts=new WeakMap(),attributes=new WeakMap();

function readLanguage(){try{const value=localStorage.getItem(KEY);return UI_LANGUAGES.some(([id])=>id===value)?value:'ru';}catch{return 'ru';}}
export const uiLanguage=()=>language;
export const uiLocale=()=>UI_LANGUAGES.find(([id])=>id===language)?.[2]||'ru-RU';
export function onUiLanguage(listener){listeners.add(listener);return()=>listeners.delete(listener);}

// Text produced outside React's tree (toasts, canvas labels, document.title,
// confirm() prompts) can call this directly.
export function t(text){return language==='uk'&&translator?translator(text):text;}

function skipped(element){
 for(let node=element;node&&node.nodeType===1;node=node.parentElement){
  if(SKIP.has(node.nodeName)||node.isContentEditable)return true;
  if(node.getAttribute('translate')==='no')return true;
 }
 return false;
}

function translateText(node,trusted=false){
 const value=node.nodeValue,record=texts.get(node);
 if(record&&value===record.out)return;
 if(!node.parentElement||!trusted&&skipped(node.parentElement))return;
 const out=translator(value);
 texts.set(node,{src:value,out});
 if(out!==value)node.nodeValue=out;
}

function translateAttributes(element,trusted=false){
 if(!trusted&&skipped(element))return;
 let saved=attributes.get(element);
 for(const name of ATTRIBUTES){
  const value=element.getAttribute(name);if(value==null)continue;
  const record=saved?.get(name);if(record&&value===record.out)continue;
  const out=translator(value);
  if(!saved){saved=new Map();attributes.set(element,saved);}
  saved.set(name,{src:value,out});
  if(out!==value)element.setAttribute(name,out);
 }
}

function translateTree(root){
 if(!root)return;
 if(root.nodeType===3){translateText(root);return;}
 if(root.nodeType!==1&&root.nodeType!==9&&root.nodeType!==11)return;
 if(root.nodeType===1){if(skipped(root))return;translateAttributes(root,true);}
 const walker=document.createTreeWalker(root,NodeFilter.SHOW_ELEMENT|NodeFilter.SHOW_TEXT,{acceptNode(node){
  if(node.nodeType===1&&(SKIP.has(node.nodeName)||node.getAttribute('translate')==='no'||node.isContentEditable))return NodeFilter.FILTER_REJECT;
  return NodeFilter.FILTER_ACCEPT;
 }});
 for(let node=walker.nextNode();node;node=walker.nextNode()){
  if(node.nodeType===3)translateText(node,true);else translateAttributes(node,true);
 }
}

function restoreTree(root){
 const walker=document.createTreeWalker(root,NodeFilter.SHOW_ELEMENT|NodeFilter.SHOW_TEXT);
 for(let node=walker.currentNode;node;node=walker.nextNode()){
  if(node.nodeType===3){const record=texts.get(node);if(record&&node.nodeValue===record.out&&record.out!==record.src)node.nodeValue=record.src;texts.delete(node);}
  else if(node.nodeType===1){const saved=attributes.get(node);if(saved){for(const [name,record] of saved)if(node.getAttribute(name)===record.out&&record.out!==record.src)node.setAttribute(name,record.src);attributes.delete(node);}}
 }
}

function observe(){
 observer?.disconnect();
 observer=new MutationObserver(records=>{
  if(language!=='uk'||!translator)return;
  for(const record of records){
   if(record.type==='characterData')translateText(record.target);
   else if(record.type==='attributes')translateAttributes(record.target);
   else for(const node of record.addedNodes)translateTree(node);
  }
 });
 observer.observe(document.documentElement,{subtree:true,childList:true,characterData:true,attributes:true,attributeFilter:ATTRIBUTES});
}

async function loadDictionary(){
 loading||=import('./uk.json').then(module=>createTranslator(module.default||module));
 return loading;
}

function announce(){
 document.documentElement.lang=language;
 for(const listener of listeners){try{listener(language);}catch{}}
 try{window.dispatchEvent(new CustomEvent('mediavault-ui-language',{detail:language}));}catch{}
}

export async function setUiLanguage(next){
 if(!UI_LANGUAGES.some(([id])=>id===next))return;
 try{localStorage.setItem(KEY,next);}catch{}
 if(next===language&&(next==='ru'||translator))return;
 language=next;
 if(next==='uk'){
  translator=await loadDictionary();
  if(language!=='uk')return;
  observe();translateTree(document.documentElement);
 }else{
  observer?.disconnect();observer=null;
  restoreTree(document.documentElement);
 }
 announce();
}

// Called once before React renders, so a Ukrainian device never flashes Russian.
export async function installI18n(){
 document.documentElement.lang=language;
 if(language!=='uk')return;
 try{translator=await loadDictionary();observe();translateTree(document.documentElement);}
 catch(error){console.warn('Ukrainian dictionary failed to load; the interface stays Russian.',error);language='ru';document.documentElement.lang='ru';}
}
