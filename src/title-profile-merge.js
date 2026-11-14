// Background dossier refreshes can finish after a character dialog. Preserve
// already-fetched details for matching identities without keeping removed cast.
export function mergeCharacterDetails(previous=[],incoming=[]){
 const saved=new Map(previous.map(value=>[String(value.id),value]));
 return incoming.map(value=>{const old=saved.get(String(value.id));return old?{...old,...value,description:value.description||old.description||''}:value;});
}
