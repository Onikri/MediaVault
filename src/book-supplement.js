// Books: Fantlab's extended work record (open to the browser, no key) gives
// the full Russian description, authors, the cycle the work belongs to and its
// other parts, adaptations, awards, editions with covers and the reader score.
// Only the exact Fantlab work ID is used.
const FANTLAB='https://api.fantlab.ru';
const image=path=>path?(/^https?:/.test(path)?path:'https://fantlab.ru'+path):'';
const text=value=>String(value||'').replace(/\[(?:\/?[a-z]+(?:=[^\]]*)?)\]/gi,'').replace(/\s+\n/g,'\n').replace(/[ \t]+/g,' ').trim();
const workType=value=>String(value||'').replace(/^./,c=>c.toLocaleUpperCase('ru'));

export async function bookSupplement(item,{signal}={}){
 const id=String(item?.ids?.fantlab||'');
 if(item?.kind!=='book'||!/^\d{1,9}$/.test(id))return {};
 const response=await fetch(FANTLAB+'/work/'+id+'/extended',{signal:AbortSignal.any([signal,AbortSignal.timeout(12000)].filter(Boolean))});
 if(!response.ok)return {};
 const data=await response.json();
 if(String(data.work_id)!==id)return {};
 // The nearest cycle (a series of novels) is the last one of the first chain.
 const cycle=(data.parents?.cycles?.[0]||[]).filter(c=>c?.work_id&&/цикл|серия/i.test(c.work_type||'')).at(-1)||null;
 const cycleData=cycle?await fetch(FANTLAB+'/work/'+Number(cycle.work_id)+'/extended',{signal:AbortSignal.any([signal,AbortSignal.timeout(10000)].filter(Boolean))}).then(r=>r.ok?r.json():null).catch(()=>null):null;
 const siblings=(cycleData?.children||[]).filter(c=>c.work_id&&c.deep===1&&String(c.work_id)!==id&&!/рассказ|статья|эссе/i.test(c.work_type||'')).slice(0,24);
 const genres=[];(function walk(rows,depth){for(const row of rows||[]){if(row.label&&Number(row.percent)>=.5&&depth<3)genres.push(row.label);walk(row.genre,depth+1);}})(data.classificatory?.genre_group?.[0]?.genre,0);
 const authors=(data.authors||[]).filter(a=>a.type==='autor'||a.role==='autor');
 const editions=Object.values(data.editions_blocks||{}).flatMap(block=>block.list||[]);
 const children=(data.children||[]).filter(c=>c.work_id&&c.deep===1);
 const awards=[...(data.awards?.win||[]),...(data.awards?.nom||[])].slice(0,10).map(a=>({name:text(a.award_rusname||a.award_name),year:a.contest_year,won:!!Number(a.cw_is_winner),category:text(a.nomination_rusname||a.nomination_name||'')})).filter(a=>a.name);
 const films=data.films?.screen_version||[];
 return {
  description:text(data.work_description),
  authors:authors.map(a=>a.name).filter(Boolean),
  staff:authors.map(a=>({id:'fantlab-author:'+a.id,name:a.name,role:'Автор',image:'',url:'https://fantlab.ru/autor'+a.id})),
  format:workType(data.work_type),year:Number(data.work_year)||null,
  originalTitle:data.work_name_orig||'',originalLanguage:data.lang||'',
  cycle:cycle?{id:String(cycle.work_id),title:text(cycle.work_name),parts:(cycleData?.children||[]).filter(c=>c.deep===1).length||null}:null,
  genres:[...new Set(genres)].slice(0,6),
  finished:data.work_notfinished?false:true,
  score:Number(data.rating?.rating)||null,votes:Number(data.rating?.voters)||null,
  editionsCount:Number(data.editions_info?.all)||editions.length||null,
  screenshots:editions.map(e=>e.edition_id&&'https://fantlab.ru/images/editions/big/'+e.edition_id).filter(Boolean).slice(0,12),
  related:[
   ...children.map(c=>({id:'fantlab:'+c.work_id,kind:'book',title:text(c.work_name||c.work_name_orig),relation:c.work_year?String(c.work_year):'Часть цикла',format:workType(c.work_type),cover:'',fantlab:String(c.work_id)})),
   ...siblings.map(c=>({id:'fantlab:'+c.work_id,kind:'book',title:text(c.work_name||c.work_name_orig),relation:cycle?text(cycle.work_name):'Цикл',format:[workType(c.work_type),c.work_year].filter(Boolean).join(', '),cover:'',fantlab:String(c.work_id),year:c.work_year})),
   ...films.slice(0,8).map(f=>({id:'film:'+f.film_id,kind:Number(f.type)===20?'tv':'movie',title:text(f.rusname||f.name),originalTitle:f.name||'',year:f.year,relation:'Экранизация',format:[Number(f.type)===20?'Сериал':'Фильм',f.year,f.director].filter(Boolean).join(', '),cover:''})),
  ].filter(r=>r.title),
  awards,cover:image(data.image),
 };
}
