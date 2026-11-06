// Every picture-enhancement engine the player offers, grouped for the menu.
// kind: which runtime starts it (see player-controller).
export const UPSCALERS=[
  {id:'auto',label:'Автоматически',group:'Рекомендуемые',kind:'auto'},
  {id:'artcnn-c4f16',label:'ArtCNN C4F16',hint:'Чёткость HD и WEB-релизов, лёгкий',group:'Рекомендуемые',kind:'webgpu'},
  {id:'artcnn-c4f32',label:'ArtCNN C4F32',hint:'То же, качественнее, нужна мощная видеокарта',group:'Рекомендуемые',kind:'webgpu'},
  {id:'mpv-ani4kv2',label:'Ani4K v2',hint:'Современное аниме в 2K и 4K',group:'Рекомендуемые',kind:'mpv'},
  {id:'mpv-anisd',label:'AniSD',hint:'Старое аниме и SD-источники',group:'Рекомендуемые',kind:'mpv'},
  {id:'realesrgan',label:'Real-ESRGAN AnimeVideo v3',hint:'Нейросеть ×4, самая тяжёлая',group:'Рекомендуемые',kind:'realesrgan'},
  {id:'artcnn-c4f16-ds',label:'ArtCNN C4F16 DS',hint:'Убирает шум и добавляет резкость',group:'ArtCNN',kind:'webgpu'},
  {id:'artcnn-c4f16-dn',label:'ArtCNN C4F16 DN',hint:'Убирает шум и смягчает',group:'ArtCNN',kind:'webgpu'},
  {id:'artcnn-c4f32-ds',label:'ArtCNN C4F32 DS',hint:'Шумоподавление и резкость, тяжелее',group:'ArtCNN',kind:'webgpu'},
  {id:'artcnn-c4f32-dn',label:'ArtCNN C4F32 DN',hint:'Шумоподавление и мягкость, тяжелее',group:'ArtCNN',kind:'webgpu'},
  {id:'cunny-veryfast',label:'CuNNy Veryfast',hint:'Самый быстрый, для встроенной графики',group:'CuNNy',kind:'webgpu'},
  {id:'cunny-faster',label:'CuNNy Faster',hint:'Быстрый',group:'CuNNy',kind:'webgpu'},
  {id:'cunny-fast',label:'CuNNy Fast',hint:'Баланс скорости и качества',group:'CuNNy',kind:'webgpu'},
  {id:'cunny-4x16',label:'CuNNy 4x16',hint:'Качественнее',group:'CuNNy',kind:'webgpu'},
  {id:'cunny-4x32',label:'CuNNy 4x32',hint:'Высокое качество',group:'CuNNy',kind:'webgpu'},
  {id:'cunny-fast-ds',label:'CuNNy Fast DS',hint:'С шумоподавлением и резкостью',group:'CuNNy',kind:'webgpu'},
  {id:'cunny-8x32-ds',label:'CuNNy 8x32 DS',hint:'Максимум CuNNy, очень тяжёлый',group:'CuNNy',kind:'webgpu'},
  {id:'a4k-a',label:'Anime4K, режим A',hint:'Восстановление размытых линий, 1080p источники',group:'Anime4K',kind:'webgpu'},
  {id:'a4k-b',label:'Anime4K, режим B',hint:'Мягче A, для чистых источников',group:'Anime4K',kind:'webgpu'},
  {id:'a4k-c',label:'Anime4K, режим C',hint:'Шумоподавление, для сильно сжатых источников',group:'Anime4K',kind:'webgpu'},
  {id:'a4k-aa',label:'Anime4K, режим A+A',hint:'Двойной проход A',group:'Anime4K',kind:'webgpu'},
  {id:'a4k-bb',label:'Anime4K, режим B+B',hint:'Двойной проход B',group:'Anime4K',kind:'webgpu'},
  {id:'a4k-ca',label:'Anime4K, режим C+A',hint:'Шумоподавление, затем восстановление',group:'Anime4K',kind:'webgpu'},
  {id:'acnet-f8b8',label:'ACNet F8B8',hint:'Сеть из Anime4KCPP, лёгкая',group:'ACNet',kind:'webgpu'},
  {id:'acnet-f8b18',label:'ACNet F8B18',hint:'Сеть из Anime4KCPP, качественнее',group:'ACNet',kind:'webgpu'},
  {id:'acnet-f8b18-hdn',label:'ACNet F8B18 HDN',hint:'С шумоподавлением',group:'ACNet',kind:'webgpu'},
  {id:'anime4k',label:'Anime4K, WebGL',hint:'Для браузеров без WebGPU',group:'Без WebGPU',kind:'anime4k-webgl'},
  {id:'anime4k-l',label:'Anime4K L, WebGL',hint:'Для браузеров без WebGPU',group:'Без WebGPU',kind:'anime4k-webgl'}
];
export const upscalerById=id=>UPSCALERS.find(u=>u.id===id);
// Auto: ArtCNN where WebGPU exists (CuNNy Veryfast on phones), Anime4K WebGL otherwise.
export function autoUpscaler(deviceProfile){
  if(typeof navigator!=='undefined'&&navigator.gpu)return deviceProfile==='desktop'?'artcnn-c4f16':'cunny-veryfast';
  return 'anime4k';
}
// Older saved choices that no longer exist map to their closest replacement.
export function migrateUpscaler(id){
  return {mobile:'cunny-veryfast',lanczos:'cunny-veryfast',fsr:'artcnn-c4f16','fsr-soft':'artcnn-c4f16-dn',fsrcnn:'artcnn-c4f16','anime4k-vl':'a4k-a','anime4k-ul':'a4k-aa'}[id]||id;
}
