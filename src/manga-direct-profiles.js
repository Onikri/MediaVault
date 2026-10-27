export const DIRECT_DETECTORS=[
 {id:'en-fast',label:'Лёгкий EN · без весов, экспериментальный'},
 {id:'rtdetr',model:'comic-bubble',label:'RT-DETR Comic · INT8, 11 МБ'},
 {id:'ctd',model:'comic-text-detector',label:'CTD · медленный, текст и маски, 95 МБ'},
 {id:'yolo26n-manga',model:'yolo26n-manga',label:'YOLO26n Manga · текстовые блоки'},
 {id:'ppocrv6-det',model:'ppocrv6-det',label:'PP-OCRv6 Manga · строки текста'},
];
export const DIRECT_INPUTS=[
 {id:'annotated',label:'Рамки и метки · локальный детектор'},
 {id:'coordinates',label:'Чистая страница + координаты детектора'},
 {id:'vision',label:'Google сам находит текст и координаты'},
];
export const directInput=value=>DIRECT_INPUTS.some(v=>v.id===value)?value:'annotated';
export const directDetector=value=>DIRECT_DETECTORS.some(v=>v.id===value)?value:'en-fast';
