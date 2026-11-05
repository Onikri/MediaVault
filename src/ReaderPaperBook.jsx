import {createContext,forwardRef,useContext,useEffect,useLayoutEffect,useMemo,useRef,useState} from 'react';
import HTMLFlipBook from 'react-pageflip';
import {useReducedMotion} from 'motion/react';
const Pages=createContext(null);
const Paper=forwardRef(function Paper({index},ref){const value=useContext(Pages),near=Math.abs(index-value.page)<=4;return <div ref={ref} className="reader-paper-leaf" data-density="soft">{near?value.renderPage(index):<div className="reader-page-placeholder">{index+1}</div>}</div>;});
// MIT react-pageflip / StPageFlip. Page pixels and translated overlays remain
// owned by React; only the sheet geometry is controlled by the flip engine.
export default function ReaderPaperBook({total,page,spread,direction,onPage,renderPage}){
 const host=useRef(null),[size,setSize]=useState(null);
 useLayoutEffect(()=>{let frame=0;const update=()=>{cancelAnimationFrame(frame);frame=requestAnimationFrame(()=>{const r=host.current?.getBoundingClientRect();if(r?.width>20&&r.height>20){const next={width:Math.floor(r.width),height:Math.floor(r.height)};setSize(old=>old?.width===next.width&&old?.height===next.height?old:next);}});};update();const observer=new ResizeObserver(update);observer.observe(host.current);return()=>{observer.disconnect();cancelAnimationFrame(frame);};},[]);
 return <div className={'reader-paper-book'+(spread?' is-spread':'')} ref={host} data-reader-interactive>{size&&<BookEngine key={[size.width,size.height,spread,direction,total].join(':')} {...{total,page,spread,direction,onPage,renderPage,size}}/>}</div>;
}
function BookEngine({total,page,spread,direction,onPage,renderPage,size}){
 const engine=useRef(null),book=useRef(null),live=useRef({onPage}),[ready,setReady]=useState(false),reduced=useReducedMotion();live.current={onPage};
 const reverse=direction==='rtl',pad=reverse&&total%2?1:0,toBook=n=>reverse?total-1-n+pad:n,fromBook=n=>Math.max(0,Math.min(total-1,reverse?total-1-n+pad:n));
 const leaves=useMemo(()=>Array.from({length:total+pad},(_,i)=>pad&&i===0?<div key="blank" className="reader-paper-leaf"/>:<Paper key={i} index={reverse?total-1-i+pad:i}/>),[total,reverse]);
 useEffect(()=>{if(!ready)return;const flip=book.current?.pageFlip();if(!flip)return;const target=toBook(page),current=flip.getCurrentPageIndex();if(current===target)return;if(reduced||Math.abs(current-target)>2)flip.turnToPage(target);else flip.flip(target);},[page,ready,spread,reverse,reduced]);
 useEffect(()=>()=>{const flip=engine.current;try{flip?.destroy();}catch{}},[]);
 return <Pages.Provider value={{page,renderPage}}><HTMLFlipBook ref={book} width={Math.floor(size.width/(spread?2:1))} height={size.height} size="fixed" startPage={toBook(page)} drawShadow={!reduced} maxShadowOpacity={.28} flippingTime={reduced?1:650} usePortrait={!spread} autoSize={false} showCover showPageCorners={false} useMouseEvents={false} mobileScrollSupport clickEventForward disableFlipByClick={false} swipeDistance={10000} renderOnlyPageLengthChange onInit={()=>{engine.current=book.current?.pageFlip();setReady(true);}} onFlip={event=>live.current.onPage(fromBook(event.data))}>{leaves}</HTMLFlipBook></Pages.Provider>;
}
