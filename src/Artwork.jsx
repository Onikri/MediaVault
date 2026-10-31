import screen from './blossom/placeholders/screen.webp';
import print from './blossom/placeholders/print.webp';
// Original generic anime artwork, never a claim about a catalogue title.
export default function Artwork({kind='manga',className='',ref}){
 return <img ref={ref} className={'artwork-placeholder '+className} src={['manga','book','ranobe'].includes(kind)?print:screen} alt="" data-placeholder="true" loading="lazy"/>;
}
