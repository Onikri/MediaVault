import type { Anime } from '../types/anime';
export const coverOf = (anime:Anime) => anime.images?.webp?.large_image_url || anime.images?.webp?.image_url || '';
export const safeSynopsis = (anime:Anime) => anime.synopsis?.replace(/\s+/g,' ').trim() || '';
export const shortTitle = (title:string, limit = 30) => title.length <= limit ? title : `${title.slice(0,limit).trim()}...`;
export const subtitle = (anime:Anime) => [anime.year, anime.genres?.[0]?.name].filter(Boolean).join(' · ');
export const scoreLabel = (value:number | null | undefined) => typeof value === 'number' ? value.toFixed(2) : 'N/A';
