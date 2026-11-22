import React from 'react';
import {MotionIcon,glyph} from './motion-icons/MotionIcon.jsx';
import {House,LayoutGrid,History,UserRound,Search,ArrowRight,ArrowLeft,X,Plus,Bookmark,BookOpen,PanelsTopLeft,Play,Music2,Image,LockKeyhole,Check,CloudUpload,Share2,LogOut,Grid2X2,ChevronRight,RefreshCw,Copy,SlidersHorizontal} from 'lucide-react';
const icons={home:House,library:LayoutGrid,history:History,user:UserRound,search:Search,arrow:ArrowRight,back:ArrowLeft,close:X,plus:Plus,bookmark:Bookmark,book:BookOpen,manga:PanelsTopLeft,video:Play,audio:Music2,image:Image,lock:LockKeyhole,check:Check,cloud:CloudUpload,share:Share2,logout:LogOut,grid:Grid2X2,chevron:ChevronRight,refresh:RefreshCw,copy:Copy,filter:SlidersHorizontal};
export default function Icon({name,size=22,...props}){const Component=icons[name]||BookOpen;return <Component size={size} strokeWidth={1.7} aria-hidden="true" {...props}/>;}
// The site mark: the «сейф-сакура» blossom in its ring, drawn in on mount.
export function BrandMark(){return <MotionIcon glyph={glyph('site')} variant="a" size={32}/>;}
