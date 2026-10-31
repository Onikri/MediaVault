import type {ReactNode} from 'react';
/** Grid shell shared by remote catalog, private collection, and entity pages. */
export function AnimeGrid({children,className='',id}:{children:ReactNode;className?:string;id?:string}){
 return <div id={id} className={'anime-grid '+className}>{children}</div>;
}
