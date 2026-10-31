import {ArrowUpRight} from 'lucide-react';
import type {ReactNode} from 'react';
// ProducerCard's supplied editorial anatomy, adapted to an existing media section.
export function ProducerCard({name,subtitle,index=0,children,onOpen}:{name:string;subtitle:string;index?:number;children?:ReactNode;onOpen:()=>void}){
 return <button type="button" className="producer-card category-card" onClick={onOpen} style={{animationDelay:index*45+'ms'}}><div className="studio-shape">{children||<span>{name.slice(0,2)}</span>}<div className="studio-orbit"/></div><div className="producer-content"><div className="producer-top"><span>{String(index+1).padStart(2,'0')} / MEDIA</span></div><h3>{name}</h3><p>{subtitle}</p><div className="producer-bottom">Открыть<ArrowUpRight size={17}/></div></div></button>;
}
