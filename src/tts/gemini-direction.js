// Delivery directions sent to the Gemini voice model with each utterance.
// Model prompt text: it never reaches the interface and is not translated.
// Directions for the model, one per emotion of the role pass.
export const EMOTION_DIRECTION={joy:'радостно',sad:'грустно',angry:'сердито, с напором',fear:'испуганно, сбивчиво',surprise:'удивлённо',
 whisper:'шёпотом',shout:'громко, почти криком',tender:'нежно',sarcastic:'с сарказмом, насмешливо',tired:'устало',excited:'взволнованно, оживлённо',
 calm:'спокойно',cold:'холодно, отстранённо',pleading:'умоляюще',nervous:'нервно',determined:'решительно',proud:'гордо',menacing:'угрожающе, низко',
 crying:'сквозь слёзы',embarrassed:'смущённо',disgust:'с отвращением',confused:'растерянно',dreamy:'мечтательно'};
const AGE={child:'ребёнок',teen:'подросток',young:'молодой человек',adult:'взрослый',old:'пожилой человек'};
const AGE_F={child:'девочка',teen:'девушка-подросток',young:'молодая женщина',adult:'взрослая женщина',old:'пожилая женщина'};
// The timbre itself is directed in words: measured live on 2026-11-09, the
// same prebuilt voice moved from 127 Hz to 233 Hz («девочка») or 97 Hz
// («старик») by this description alone.
const TIMBRE={warm:'тёплый',bright:'звонкий',dark:'низкий, глухой',breathy:'с придыханием',rough:'хрипловатый',nasal:'с носовым оттенком',soft:'мягкий'};
const AGE_VOICE={child:'детский голос',teen:'юношеский голос',young:'молодой голос',adult:'',old:'голос пожилого человека, старческий'};
export function describeVoice(character={},{narrator=false}={}){
 const parts=[];
 if(AGE_VOICE[character.age])parts.push(character.gender==='f'&&character.age==='old'?'голос пожилой женщины':AGE_VOICE[character.age]);
 if(TIMBRE[character.timbre])parts.push(TIMBRE[character.timbre]);
 const pitch=Number(character.pitch)||0;if(pitch<=-1)parts.push(pitch<=-2?'очень низкий':'ниже обычного');else if(pitch>=1)parts.push(pitch>=2?'очень высокий':'выше обычного');
 const energy=Number(character.energy)||0;if(energy<=-1)parts.push('тихий, сдержанный');else if(energy>=1)parts.push('энергичный');
 const pace=Number(character.pace)||1;if(pace<.95)parts.push('говорит медленно');else if(pace>1.05)parts.push('говорит быстро');
 if(narrator&&character.style)parts.push(character.style);
 return parts.join(', ');
}
// How the model should deliver one segment. Plain Russian directions.
// note: the listener's own description of this voice (wins over the bible's).
export function styleFor(segment,character,{tone='',pace=1,note='',narratorNote=''}={}){
 const parts=[];
 if(segment.kind==='narration'){parts.push('авторский текст: ровно и выразительно, как в хорошей аудиокниге'+(tone?', тон книги — '+tone:''));if(narratorNote)parts.push('голос рассказчика: '+narratorNote);}
 else{
  const who=character?.gender==='f'?AGE_F[character.age]||'женщина':character?.gender==='m'?AGE[character.age]||'мужчина':'';
  parts.push((segment.kind==='thought'?'прочитать мысли героя, тише и задумчивее':'прочитать реплику героя')+(segment.speaker?' '+segment.speaker:'')+(who?' ('+who+')':''));
  if(character?.traits)parts.push('характер: '+character.traits);
  if(character?.speech)parts.push('манера речи: '+character.speech);
  const voice=note||character?.description||describeVoice(character||{});if(voice)parts.push('голос героя: '+voice);
  const emotion=segment.emotion&&segment.emotion!=='neutral'?EMOTION_DIRECTION[segment.emotion]:'';
  if(emotion)parts.push('эмоция: '+emotion+((segment.intensity??.5)>=.75?', сильно':(segment.intensity??.5)<=.35?', слегка':''));
 }
 if(pace<.95)parts.push('темп медленнее обычного');else if(pace>1.05)parts.push('темп быстрее обычного');
 return parts.join('; ').slice(0,390);
}

