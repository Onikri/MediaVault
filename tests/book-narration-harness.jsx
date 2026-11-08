// TXT book narration: real BookReader and real Supertonic inference; no server.
import React from 'react';
import {createRoot} from 'react-dom/client';
import '/src/styles.css';
import BookReader from '/src/BookReader.jsx';
const text=['Розділ перший','Вітер приніс запах дощу, а десь удалині глухо прогримів грім.','— Ти знову запізнився, — невдоволено сказала Оксана.','— Пробач, я заблукав, — винувато відповів Тарас.'].join('\n\n');
localStorage.setItem('mediavault_tts_consent_v1','yes');
localStorage.setItem('mediavault_tts_prefs_v1',JSON.stringify({roles:false,pace:1,narrator:'M2'}));
createRoot(document.getElementById('root')).render(<BookReader item={{id:'book-test',name:'Оповідання.txt'}} userId="fixture" libraryId="local" onClose={()=>{}} readWhole={async()=>new Blob([text],{type:'text/plain'})}/>);
