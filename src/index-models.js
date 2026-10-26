// Official IndexTeam GGUF, Apache-2.0; immutable revision and LFS SHA-256.
export const INDEX_REVISION='3a0eca6ce931d88d00614d427ab3ed8ff0743902';
export const INDEX_MODELS={
 q8:{id:'q8',file:'Index-Translate-2B.Q8_0.gguf',bytes:2076674560,sha:'a09d287f41d297206947a2e51acc29dd03c8b22356111fdb1e289c0c97c173f3',label:'Q8 · качество · 2,08 ГБ'},
 q6:{id:'q6',file:'Index-Translate-2B.Q6_K.gguf',bytes:1606323712,sha:'3ec6fa4e5a5efa25620f17ecfce8daec1ec8fb35a53c82b419a6707581a505b9',label:'Q6 · меньше памяти · 1,61 ГБ'},
 q4:{id:'q4',file:'Index-Translate-2B.Q4_K_M.gguf',bytes:1312164352,sha:'044b313d29342bd3b2c77cbb64023ca0d209bd9b3247763f9d162767ef2d746a',label:'Q4 · экономно · 1,31 ГБ'},
};
export function indexModel(id='q8'){return INDEX_MODELS[id]||INDEX_MODELS.q8;}
export function indexUrl(model){return 'https://huggingface.co/IndexTeam/Index-Translate-2B-GGUF/resolve/'+INDEX_REVISION+'/'+model.file;}
export function indexPrompt(text){return '请将以下文本翻译为俄语，直接输出翻译结果，不要进行任何解释。\n\n'+text;}
