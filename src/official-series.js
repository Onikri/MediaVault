// Episode and video identifiers published by GMMTV.
const episodes=[
 ['Zoag6', ['VcLBOlLUlTk', '6N0RaRwK2pQ', 'DGQNLl8UdfI', 'K_wwE7yYMLE']],
 ['ZyaeZ', ['TKNKEsWApiA', 'VaVqwGAOx7Q', '1Wx_ZDjQY7g', '5_Olb78rSaU']],
 ['20Ox6', ['g192l5BxlmI', 'bBb8xXU6GLo', '0C9pK2FI170', 'UVQgHMvSoSo']],
 ['6ndeZ', ['CTMhzzpG4PQ', '6fxCgxJdZ2k', 'oxgIRs8NiI0', 'z_5nmvjsCwg']],
 ['6j1xQ', ['2aYEyjXT5y0', 'ng4CqnG-u6M', 'VgPc_UKm-ZQ', 'hyfAMpKZvKk']],
 ['6zzx6', ['fVFODLCt_hc', 'TQMYFoplL40', 'z-9D973pP7g', 'L22TpHE_dpo']],
 ['Z7Nv2', ['SZfemENPYDc', '3xnyTiEJ2zk', 'V8t7iHGeVyQ', 'RAInSa1s_Yo']],
 ['2v04Q', ['Ec6UT2qsrgw', 'pq9rVt7Jp48', 'aRzUZPW86sI', 'F8m8US0l0e8']],
 ['6Azv2', ['s5LAR4GTDW0', 'pxrZ1BGI0wc', 'kEzO3qTX2k0', 'a7BrkCaMT-Q']],
 ['ZKgwZ', ['K6sn1MfK1rQ', '4deR42jrS9A', 'aL-QnTJ3ovw', 'kHXlnupiBf4']],
 ['QxG1Z', ['K5zLQ9Psuzw', 'nFayn0JBrZA', 'XZZfDwzfqGc', 'TdqxuCniGKk']],
 ['ZdlEZ', ['2W0WyE2ukhU', '5M_Z9p9q1WQ', 'cPHSbEYpJtE', '0pzmHc3QRpU']],
];
const publisher='https://www.gmm-tv.com/contents/episode/';

const blacklist={
 publisher:'GMMTV',
 audio:'Тайский оригинал',
 subtitles:'Английские субтитры',
 episodes:episodes.map(([id,parts],index)=>({
  number:index+1,
  url:publisher+id+'/',
  parts,
 })),
};

export function officialSeries(item){
 if(item?.kind!=='tv')return null;
 const imdb=String(item.ids?.imdb||(item.provider==='imdb'?item.providerId:'')||'');
 const kp=String(item.ids?.kinopoisk||(item.provider==='kinobox'?item.providerId:'')||'');
 if((imdb&&imdb!=='tt9892494')||(kp&&kp!=='1247522'))return null;
 return imdb==='tt9892494'||kp==='1247522'||(item.provider==='tvmaze'&&String(item.providerId)==='44220')?blacklist:null;
}
