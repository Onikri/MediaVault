import {useEffect,useRef} from 'react';
import {buildTitles} from './library-model.js';
import {loadTitleProfile} from './title-metadata.js';
import {fetchArtwork} from './title-artwork.js';

// An imported first episode already carries its catalogue ID. Enrich one title
// at a time while the owner's library is open, then read only Drive snapshots.
export default function useLibraryProfiles(state,actions,server,importing){
  const attempted=useRef(new Set()),live=useRef(state);live.current=state;
  useEffect(()=>{
    if(!state.catalog||!state.admin||!state.driveWritable||importing)return;
    const title=buildTitles(state.catalog).find(t=>t.metadataId&&!state.catalog.titleProfiles?.[t.id]?.sourceId&&!attempted.current.has(t.id));
    if(!title)return;
    let closed=false,timer;const controller=new AbortController();
    const start=async()=>{
      if(closed)return;
      if(live.current.busy){timer=setTimeout(start,1500);return;}
      attempted.current.add(title.id);
      try{
        const profile=await loadTitleProfile(title.metadataId,title.section,{signal:controller.signal,server});
        const {images,failed}=await fetchArtwork(profile,{signal:controller.signal});
        if(!closed&&!live.current.busy)await actions.saveTitleProfile(title.id,{...profile,missingArtwork:failed},images);
      }catch(error){if(controller.signal.aborted)attempted.current.delete(title.id);}
    };
    timer=setTimeout(start,1500);
    return()=>{closed=true;clearTimeout(timer);controller.abort();};
  },[state.catalog,state.admin,state.driveWritable,server,importing]);
}
