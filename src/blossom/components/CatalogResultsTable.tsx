import {CardRating} from './CardRating';
import {Poster} from '../../ImportParts.jsx';
export function CatalogResultsTable({items,onChoose}:{items:any[];onChoose:(value:any)=>void}){
 return <div className="library-table-scroll"><table className="library-table catalog-table"><thead><tr><th>Название</th><th>Год</th><th>Формат</th><th>Серии / главы</th><th>Оценка</th></tr></thead><tbody>{items.map(item=><tr key={item.id}><td><button onClick={()=>onChoose(item)}><Poster item={item}/><strong>{item.title}</strong></button></td><td>{item.year||'—'}</td><td>{item.format||'—'}</td><td>{item.episodes||item.chapters||'—'}</td><td><CardRating score={item.score} inline empty="—"/></td></tr>)}</tbody></table></div>;
}
