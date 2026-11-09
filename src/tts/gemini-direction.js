// Delivery directions sent to the Gemini voice model with each utterance.
// Model prompt text: it never reaches the interface and is not translated.
// Directions for the model, one per emotion of the role pass.
export const EMOTION_DIRECTION={joy:'радостно',sad:'грустно',angry:'сердито, с напором',fear:'испуганно, сбивчиво',surprise:'удивлённо',
 whisper:'шёпотом',shout:'громко, почти криком',tender:'нежно',sarcastic:'с сарказмом, насмешливо',tired:'устало',excited:'взволнованно, оживлённо',
 calm:'спокойно',cold:'холодно, отстранённо',pleading:'умоляюще',nervous:'нервно',determined:'решительно',proud:'гордо',menacing:'угрожающе, низко',
 crying:'сквозь слёзы',embarrassed:'смущённо',disgust:'с отвращением',confused:'растерянно',dreamy:'мечтательно'};
const AGE={child:'ребёнок',teen:'подросток',young:'молодой человек',adult:'взрослый',old:'пожилой человек'};
const AGE_F={child:'девочка',teen:'девушка-подросток',young:'молодая женщина',adult:'взрослая женщина',old:'пожилая женщина'};
// How the model should deliver one segment. Plain Russian directions.
export function styleFor(segment,character,{tone='',pace=1}={}){
 const parts=[];
 if(segment.kind==='narration')parts.push('авторский текст: ровно и выразительно, как в хорошей аудиокниге'+(tone?', тон книги — '+tone:''));
 else{
  const who=character?.gender==='f'?AGE_F[character.age]||'женщина':character?.gender==='m'?AGE[character.age]||'мужчина':'';
  parts.push((segment.kind==='thought'?'прочитать мысли героя, тише и задумчивее':'прочитать реплику героя')+(segment.speaker?' '+segment.speaker:'')+(who?' ('+who+')':''));
  if(character?.traits)parts.push('характер: '+character.traits);
  if(character?.speech)parts.push('манера речи: '+character.speech);
  const emotion=segment.emotion&&segment.emotion!=='neutral'?EMOTION_DIRECTION[segment.emotion]:'';
  if(emotion)parts.push('эмоция: '+emotion+((segment.intensity??.5)>=.75?', сильно':(segment.intensity??.5)<=.35?', слегка':''));
 }
 if(pace<.95)parts.push('темп медленнее обычного');else if(pace>1.05)parts.push('темп быстрее обычного');
 return parts.join('; ').slice(0,390);
}

