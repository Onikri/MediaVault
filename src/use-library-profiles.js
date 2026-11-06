import {useEffect,useRef} from 'react';
import {buildTitles} from './library-model.js';
import {loadTitleProfile,profileNeedsRefresh,scheduleProfileRetry} from './title-metadata.js';
import {fetchArtwork} from './title-artwork.js';

// An imported first episode already carries its catalogue ID. Enrich one title
// at a time while the owner's library is open, then read only Drive snapshots.
// When the import server enriches the library itself, the browser stays out of
// it so the same title is not fetched and written twice. Retries follow the
// shared back-off in title-metadata.js and save quietly in the background.
export default function useLibraryProfiles(state,actions,server,importing,serverEnriches=false){
  const attempted=useRef(new Set()),live=useRef(state);live.current=state;
  useEffect(()=>{
    if(!state.catalog||!state.admin||!state.driveWritable||importing||serverEnriches)return;
    const title=buildTitles(state.catalog).find(t=>t.metadataId&&profileNeedsRefresh(state.catalog.titleProfiles?.[t.id])&&!attempted.current.has(t.id));
    if(!title)return;
    let closed=false,timer;const controller=new AbortController();
    const start=async()=>{
      if(closed)return;
      if(live.current.busy){timer=setTimeout(start,1500);return;}
      attempted.current.add(title.id);
      try{
        const previous=live.current.catalog?.titleProfiles?.[title.id];
        const profile=scheduleProfileRetry(await loadTitleProfile(title.metadataId,title.section,{signal:controller.signal,server}),previous);
        const {images,failed}=await fetchArtwork(profile,{signal:controller.signal});
        if(!closed)await actions.saveTitleProfile(title.id,{...profile,missingArtwork:failed},images,{background:true});
      }catch(error){if(controller.signal.aborted)attempted.current.delete(title.id);}
    };
    timer=setTimeout(start,1500);
    return()=>{closed=true;clearTimeout(timer);controller.abort();};
  },[state.catalog,state.admin,state.driveWritable,server,importing,serverEnriches]);
}
