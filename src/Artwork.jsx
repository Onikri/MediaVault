import anime from './blossom/placeholders/anime.svg';
import manga from './blossom/placeholders/manga.svg';
import book from './blossom/placeholders/book.svg';
import ranobe from './blossom/placeholders/ranobe.svg';
import music from './blossom/placeholders/music.svg';
import video from './blossom/placeholders/video.svg';
import photo from './blossom/placeholders/photo.svg';
const icons={anime,manga,book,ranobe,music,audio:music,video,movie:video,tv:video,photo,image:photo};
export default function Artwork({kind='manga',className='',ref}){
 return <img ref={ref} className={'artwork-placeholder '+className} src={icons[kind]||video} alt="" data-placeholder="true" loading="lazy" decoding="async"/>;
}
