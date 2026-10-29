// IDs and thinking controls verified against Google AI for Developers docs.
export const GOOGLE_TRANSLATION_MODELS=[
 {id:'gemini-3.5-flash-lite',label:'Gemini 3.5 Flash Lite · минимум',thinking:{thinkingLevel:'MINIMAL'},inputLimit:1048576,outputLimit:65536},
 {id:'gemma-4-26b-a4b-it',label:'Gemma 4 · 26B A4B',thinking:{thinkingLevel:'MINIMAL'}},
 {id:'gemma-4-31b-it',label:'Gemma 4 · 31B',thinking:{thinkingLevel:'MINIMAL'}},
 {id:'gemini-3.1-flash-lite',label:'Gemini 3.1 Flash Lite · минимум',thinking:{thinkingLevel:'MINIMAL'}},
 {id:'gemini-2.5-flash-lite',label:'Gemini 2.5 Flash Lite · без размышлений',thinking:{thinkingBudget:0}},
];
export const DIRECT_MODELS=GOOGLE_TRANSLATION_MODELS.map(m=>m.id);
export const googleModel=id=>GOOGLE_TRANSLATION_MODELS.find(m=>m.id===id);
