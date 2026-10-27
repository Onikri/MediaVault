// Google uses normalized [ymin,xmin,ymax,xmax], independent of sent image size.
// No unvalidated model rectangle is ever handed to the eraser.
function rectangle(value,width,height){
 if(!Array.isArray(value)||value.length!==4||!value.every(n=>Number.isFinite(n)&&n>=0&&n<=1000))throw Error('Google вернул координаты вне диапазона 0–1000. Оригинал сохранён.');
 const [y,x,b,r]=value;
 if(r<=x||b<=y)throw Error('Google вернул перевёрнутую или пустую область. Оригинал сохранён.');
 return [x*width/1000,y*height/1000,r*width/1000,b*height/1000].map(n=>Math.round(n*100)/100);
}
export function boxIou(a,b){
 const area=v=>Math.max(0,v[2]-v[0])*Math.max(0,v[3]-v[1]),intersection=area([Math.max(a[0],b[0]),Math.max(a[1],b[1]),Math.min(a[2],b[2]),Math.min(a[3],b[3])]);
 return intersection/Math.max(1,area(a)+area(b)-intersection);
}
export function visionRegions(rows,page,fonts,kinds){
 if(!Array.isArray(rows)||rows.length>100)throw Error('Google вернул слишком много областей или некорректный список.');
 const result=[];
 for(const [i,row] of rows.entries()){
  if(!row||typeof row.ru!=='string'||row.ru.length>4000)throw Error('Google вернул некорректный текст области.');
  if(/\p{L}/u.test(row.ru)&&!/[А-Яа-яЁё]/.test(row.ru))throw Error('В ответе есть непереведённая реплика. Оригинал сохранён.');
  const bbox=rectangle(row.box,page.width,page.height),layout=row.layout?rectangle(row.layout,page.width,page.height):bbox;
  if(bbox[2]-bbox[0]<4||bbox[3]-bbox[1]<4||(bbox[2]-bbox[0])*(bbox[3]-bbox[1])>page.width*page.height*.3)throw Error('Область Google слишком мала или велика для безопасной очистки. Оригинал сохранён.');
  if(layout[0]>bbox[0]+1||layout[1]>bbox[1]+1||layout[2]<bbox[2]-1||layout[3]<bbox[3]-1)throw Error('Рамка набора Google не вмещает исходный текст. Оригинал сохранён.');
  if(result.some(r=>boxIou(r.text_bbox,bbox)>.85))throw Error('Google продублировал текстовую область. Оригинал сохранён.');
  result.push({uid:page.id+'_B'+(i+1),text_bbox:bbox,layout_bbox:layout,ru_translation:row.ru.trim(),source_text:'',font_style:fonts[row.f]||fonts[0],text_category:kinds[row.k]||kinds[0]});
 }
 return result;
}
export function geometryAgreement(reference,candidate,threshold=.3){
 const pairs=[];for(let i=0;i<reference.length;i++)for(let j=0;j<candidate.length;j++)pairs.push({i,j,iou:boxIou(reference[i],candidate[j])});
 const usedA=new Set(),usedB=new Set(),matches=[];
 for(const p of pairs.sort((a,b)=>b.iou-a.iou))if(p.iou>=threshold&&!usedA.has(p.i)&&!usedB.has(p.j)){usedA.add(p.i);usedB.add(p.j);matches.push(p.iou);}
 return {matched:matches.length,reference:reference.length,candidate:candidate.length,meanIou:matches.length?matches.reduce((a,b)=>a+b,0)/matches.length:0,threshold};
}
