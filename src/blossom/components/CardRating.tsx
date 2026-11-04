import type {ReactNode} from 'react';
import {Star} from 'lucide-react';
import {scoreLabel} from '../utils/display';
import './card-rating.css';

/** Shared rating: a cover-edge ribbon, or an in-flow table cell. */
export function CardRating({score,inline=false,empty=null}:{score?:number|null;inline?:boolean;empty?:ReactNode}){
 if(typeof score!=='number'||!Number.isFinite(score))return <>{empty}</>;
 return <span className={'card-score title-rating-badge'+(inline?' is-inline':'')} aria-label={'Оценка '+scoreLabel(score)}><Star size={12} fill="currentColor"/>{scoreLabel(score)}</span>;
}
