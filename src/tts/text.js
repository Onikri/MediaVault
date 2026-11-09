// Text front-end for Supertonic 3: the model reads characters (no phonemizer),
// so the text is normalised the way the official helper does, quotes and
// dialogue dashes are made speakable and numbers are spelled out in ru/uk.

const UNITS={
 ru:[['','один','два','три','четыре','пять','шесть','семь','восемь','девять'],['десять','одиннадцать','двенадцать','тринадцать','четырнадцать','пятнадцать','шестнадцать','семнадцать','восемнадцать','девятнадцать'],['','','двадцать','тридцать','сорок','пятьдесят','шестьдесят','семьдесят','восемьдесят','девяносто'],['','сто','двести','триста','четыреста','пятьсот','шестьсот','семьсот','восемьсот','девятьсот'],['одна','две'],[['тысяча','тысячи','тысяч'],['миллион','миллиона','миллионов'],['миллиард','миллиарда','миллиардов']],'ноль'],
 uk:[['','один','два','три','чотири','п’ять','шість','сім','вісім','дев’ять'],['десять','одинадцять','дванадцять','тринадцять','чотирнадцять','п’ятнадцять','шістнадцять','сімнадцять','вісімнадцять','дев’ятнадцять'],['','','двадцять','тридцять','сорок','п’ятдесят','шістдесят','сімдесят','вісімдесят','дев’яносто'],['','сто','двісті','триста','чотириста','п’ятсот','шістсот','сімсот','вісімсот','дев’ятсот'],['одна','дві'],[['тисяча','тисячі','тисяч'],['мільйон','мільйони','мільйонів'],['мільярд','мільярди','мільярдів']],'нуль'],
};
const plural=(n,[one,few,many])=>{const a=n%10,b=n%100;return a===1&&b!==11?one:a>=2&&a<=4&&(b<12||b>14)?few:many;};
function triple(n,lang,feminine){
 const [ones,teens,tens,hundreds,female]=UNITS[lang],words=[];
 if(n>=100)words.push(hundreds[Math.floor(n/100)]);
 const rest=n%100;
 if(rest>=10&&rest<20)words.push(teens[rest-10]);
 else{if(rest>=20)words.push(tens[Math.floor(rest/10)]);const unit=rest%10;if(unit)words.push(feminine&&unit<=2?female[unit-1]:ones[unit]);}
 return words;
}
export function numberWords(value,lang='ru'){
 lang=UNITS[lang]?lang:'ru';
 let n=Math.floor(Math.abs(Number(value)));
 if(!Number.isFinite(n)||n>=1e12)return String(value);
 if(n===0)return UNITS[lang][6];
 const scales=UNITS[lang][5],groups=[];
 for(let i=0;n>0;i++,n=Math.floor(n/1000))groups.push([n%1000,i]);
 const words=[];
 for(const [group,scale] of groups.reverse()){
  if(!group)continue;
  words.push(...triple(group,lang,scale===1));
  if(scale)words.push(plural(group,scales[scale-1]));
 }
 return words.join(' ');
}

export function speakable(text,lang='ru'){
 let value=String(text||'').normalize('NFC');
 value=value.replace(/[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}]/gu,'');
 value=value.replace(/[«»„“”]/g,'"').replace(/[‘’ʼ`´]/g,'’').replace(/[–‑—―]/g,'-');
 // A dialogue dash at the start of a line is layout, not speech.
 value=value.replace(/^\s*-\s+/,'');
 value=value.replace(/(\d+)[.,](\d+)/g,(m,a,b)=>numberWords(a,lang)+(lang==='uk'?' кома ':' запятая ')+numberWords(b,lang));
 value=value.replace(/\d+/g,m=>numberWords(m,lang));
 value=value.replace(/[_\[\]|/#→←♥☆♡©\\*~<>]/g,' ').replace(/\s+/g,' ').trim();
 value=value.replace(/ ([,.!?;:])/g,'$1');
 if(value&&!/[.!?;:,'")\]}…]$/.test(value))value+='.';
 return value;
}

// Model input exactly as the official helper builds it (NFKD + language tag).
// Supertonic 3 expression tags are kept only from this allowlist.
export const EXPRESSION_TAGS=['laugh','sigh','breath'];
export function modelText(text,lang,tags=[]){
 const safe=['ru','uk','en'].includes(lang)?lang:'ru';
 const prefix=tags.filter(t=>EXPRESSION_TAGS.includes(t)).slice(0,1).map(t=>'<'+t+'> ').join('');
 return '<'+safe+'>'+prefix+speakable(text,safe).normalize('NFKD').replace(/’/g,"'")+'</'+safe+'>';
}

// Sentences up to `limit` characters; very long sentences are cut at commas.
export function sentences(text,limit=260){
 const parts=String(text||'').replace(/\s+/g,' ').trim().match(/[^.!?…]+(?:[.!?…]+["»”)]*|$)/g)||[];
 const result=[];
 for(let part of parts.map(p=>p.trim()).filter(Boolean)){
  while(part.length>limit){
   const cut=Math.max(part.lastIndexOf(', ',limit),part.lastIndexOf(' - ',limit),part.lastIndexOf(' ',limit));
   const at=cut>limit*.4?cut+1:limit;result.push(part.slice(0,at).trim());part=part.slice(at).trim();
  }
  if(part)result.push(part);
 }
 return result;
}
