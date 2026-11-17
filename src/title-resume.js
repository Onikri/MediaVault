// Where the viewer stopped in an online title, read from the viewing history
// the workspace keeps (labels like «…, глава 12» or «… · 1 сезон · 5 серия»).
// The history route carries the title's watch key, so a title page finds its
// own last place without a separate store.
const watchKey=route=>{try{return new URLSearchParams(String(route||'').replace(/^#/,'')).get('watch')||'';}catch{return '';}};
export function titleResume(history,key){
 if(!key)return null;
 const row=(history||[]).filter(v=>watchKey(v.route)===key).sort((a,b)=>b.at-a.at)[0];
 if(!row)return null;
 const label=String(row.label||'');
 const episode=/(\d+)\s*сезон\s*·\s*(\d+)\s*серия/i.exec(label),chapter=/глава\s*([\d.]+)/i.exec(label);
 const place=episode?(Number(episode[1])>1?episode[1]+' сезон · ':'')+'серия '+episode[2]:chapter?'глава '+chapter[1]:'';
 return place?{place,at:row.at,kind:row.kind}:null;
}
