import {imageURL,russianText,hasRussian} from './title-metadata.js';
const roles={director:'Режиссёр',originalcreator:'Автор первоисточника',originalcharacterdesign:'Оригинальный дизайн персонажей',characterdesign:'Дизайн персонажей',artdirector:'Художественный руководитель',music:'Музыка',seriescomposition:'Композиция сериала',screenplay:'Сценарий',animationdirector:'Режиссёр анимации',chiefanimationdirector:'Главный режиссёр анимации',sounddirector:'Звукорежиссёр',producer:'Продюсер',executiveproducer:'Исполнительный продюсер',creator:'Автор',story:'Сюжет',art:'Рисунок'};
export function creditsFromRoles(values=[]){
  const result=[];
  for(const row of values){
    const person=row.person;if(!person?.id)continue;
    const labels=[...(row.roles_russian||[]).filter(hasRussian),...(row.roles||[]).map(r=>roles[String(r).toLowerCase().replace(/[^a-z]/g,'')]).filter(Boolean)];
    if(!labels.length||!russianText(person.russian))continue;
    result.push({id:String(person.id),name:russianText(person.russian),role:[...new Set(labels)].join(' · '),image:imageURL(person.image?.original||person.image?.preview)});
  }
  return result.slice(0,24);
}
