/** Jikan-compatible subset. All optional fields explicitly marked. */
export interface AnimeGenre { mal_id?: number; name: string }
export interface AnimeImage { webp?: { image_url?: string; large_image_url?: string; small_image_url?: string } }
export interface AnimeTrailer { embed_url?: string | null; youtube_id?: string | null }
export interface Anime {
  mal_id: number | string;
  title: string;
  title_english?: string | null;
  title_japanese?: string | null;
  synopsis?: string | null;
  score?: number | null;
  episodes?: number | null;
  year?: number | null;
  type?: string | null;
  rating?: string | null;
  status?: string | null;
  popularity?: number | null;
  genres: AnimeGenre[];
  aired?: { string?: string };
  images?: AnimeImage;
  trailer?: AnimeTrailer;
  studios?: { name: string }[];
}
export interface Studio { id: number; name: string; subtitle: string; works: string[]; };
export type SortKey = 'popularity' | 'score' | 'title' | 'year' | 'episodes' | 'mal_id';
export interface AnimeFilters { q: string; startDate:string; endDate:string; genre: string; rating:string; status: string; type: string; minScore: number; maxScore:number; order: SortKey; sort:'asc'|'desc' }
