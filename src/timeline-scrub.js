// A drag previews continuously but commits exactly one network seek. Keyboard
// changes still seek immediately; cancelling a gesture keeps the current video.
export function createTimelineScrub(seek){
 let active=false,point=0;
 return {
  get active(){return active;},
  begin(value){active=true;point=value;return point;},
  move(value){if(active)point=value;return point;},
  end(value=point){if(!active)return;active=false;point=value;seek(point);},
  cancel(){active=false;},
  change(value){if(!active)seek(value);}
 };
}
