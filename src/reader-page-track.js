export function pageTrackPoints(total,length){
 const count=Math.min(total,120,Math.max(2,Math.floor(Math.max(1,length)/10)));
 if(total<=1)return total?[1]:[];
 return [...new Set(Array.from({length:count},(_,i)=>1+Math.round(i*(total-1)/(count-1))))];
}
export function pageTrackPosition(page,total){return total<=1?0:Math.max(0,Math.min(1,(page-1)/(total-1)));}
export function pageAtPosition(fraction,total){return Math.max(1,Math.min(total,1+Math.round(Math.max(0,Math.min(1,fraction))*(total-1))));}
