// The panel always opens from its own trigger, independent of navbar width/scroll.
export function musicIslandLayout(anchor,viewport,contentHeight,placement='nav',desiredWidth=356){
 const margin=12,width=Math.min(desiredWidth,Math.max(1,viewport.width-2*margin)),r=anchor||{left:viewport.width-46,right:viewport.width-12,top:12,bottom:46,width:34,height:34};
 const below=Math.max(0,viewport.height-r.bottom-22),above=Math.max(0,r.top-22),up=placement!=='nav'&&above>below,maxHeight=Math.max(1,Math.min(480,viewport.height-24,up?above:below)),height=Math.min(Math.max(80,contentHeight||180),maxHeight);
 const left=Math.max(margin,Math.min(r.right-width,viewport.width-width-margin)),top=Math.max(margin,Math.min(up?r.top-height-10:r.bottom+10,viewport.height-height-margin));
 return {left,top,width,height,maxHeight,closedLeft:r.left,closedTop:r.top,closedWidth:r.width||34,closedHeight:r.height||34};
}
