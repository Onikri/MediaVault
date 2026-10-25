// Cover stands alone; spreads then keep the same pair in either direction.
export function spreadPages(page,total,cover=true){
 if(total<1)return [];page=Math.max(0,Math.min(total-1,page));
 if(cover&&page===0)return [0];const first=cover?1+Math.floor((page-1)/2)*2:Math.floor(page/2)*2;
 return [first,first+1].filter(n=>n<total);
}
export function turnPage(page,delta,total,spread=false,cover=true){
 if(!total)return 0;if(!spread)return Math.max(0,Math.min(total-1,page+delta));
 const pair=spreadPages(page,total,cover),first=pair[0];return Math.max(0,Math.min(total-1,delta>0?pair.at(-1)+1:first-(cover&&first===1?1:2)));
}
