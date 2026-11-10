// Player subtitles in Chromium: an HLS episode (hls.js) with an external VTT
// track, like Alloha/Kodik captions relayed by the server, and an in-stream
// HLS subtitle group. Checks that the chosen external track stays visible
// after the stream reloads (hls.js disables every labelled text track when its
// own subtitles are switched off) and that «Скачать» saves each kind of track.
// Fixture media made by ffmpeg; no network.
const assert=require('node:assert/strict'),fs=require('node:fs/promises'),path=require('node:path'),{execFileSync}=require('node:child_process'),{chromium}=require('playwright');
let browser,vite;
(async()=>{
 const root=path.resolve(__dirname,'..'),dir=path.join(root,'test-output','subtitles');await fs.mkdir(dir,{recursive:true});
 execFileSync('ffmpeg',['-v','error','-f','lavfi','-i','testsrc2=size=320x180:rate=12','-t','12','-c:v','libx264','-preset','ultrafast','-g','24','-pix_fmt','yuv420p','-f','hls','-hls_time','2','-hls_playlist_type','vod','-hls_segment_filename',path.join(dir,'video-%02d.seg'),'-y',path.join(dir,'video.m3u8')]);
 // External track: the server relays it as a plain VTT file.
 const external='WEBVTT\n\n00:00:00.000 --> 00:00:30.000\nВнешняя дорожка Crunchyroll\n';
 await fs.writeFile(path.join(dir,'crunchyroll.vtt'),'﻿'+external);
 // In-stream subtitles: two VTT segments with the HLS timestamp map.
 await fs.writeFile(path.join(dir,'subs-0.vtt'),'WEBVTT\nX-TIMESTAMP-MAP=MPEGTS:900000,LOCAL:00:00:00.000\n\n00:00:00.500 --> 00:00:05.000\nПервая реплика\n');
 await fs.writeFile(path.join(dir,'subs-1.vtt'),'WEBVTT\nX-TIMESTAMP-MAP=MPEGTS:900000,LOCAL:00:00:00.000\n\n00:00:06.000 --> 00:00:11.000\nВторая реплика\n');
 await fs.writeFile(path.join(dir,'subs.m3u8'),'#EXTM3U\n#EXT-X-TARGETDURATION:6\n#EXT-X-PLAYLIST-TYPE:VOD\n#EXTINF:6,\nsubs-0.vtt\n#EXTINF:6,\nsubs-1.vtt\n#EXT-X-ENDLIST\n');
 for(const n of [1,2])await fs.writeFile(path.join(dir,'episode-'+n+'.m3u8'),'#EXTM3U\n#EXT-X-MEDIA:TYPE=SUBTITLES,GROUP-ID="subs",NAME="Встроенные",LANGUAGE="ru",DEFAULT=NO,AUTOSELECT=NO,URI="subs.m3u8"\n#EXT-X-STREAM-INF:BANDWIDTH=400000,RESOLUTION=320x180,SUBTITLES="subs"\nvideo.m3u8\n');
 await fs.writeFile(path.join(dir,'index.html'),'<meta name="viewport" content="width=device-width"><div id="root"></div><script type="module" src="/test-output/subtitles/harness.jsx"></script>');
 await fs.writeFile(path.join(dir,'harness.jsx'),`import React,{useState} from 'react';import {createRoot} from 'react-dom/client';import '/src/styles.css';import VideoPlayer from '/src/VideoPlayer.jsx';
const items=[1,2].map(n=>({id:'ep'+n,category:'video',section:'video',name:'Свадьба светлячков · серия '+n,onlineType:'hls'}));
function Demo(){const [n,setN]=useState(1),item=items[n-1];return <><button type="button" onClick={()=>setN(v=>v===1?2:1)}>Другая серия фикстуры</button>
 <VideoPlayer item={item} source={'/test-output/subtitles/episode-'+n+'.m3u8'} catalog={{items}} onlineControls={{externalCaptions:[{url:'/test-output/subtitles/crunchyroll.vtt',name:'Crunchyroll',language:'ru'}]}}/></>;}
createRoot(document.getElementById('root')).render(<Demo/>);`);
 const {createServer}=await import('vite');vite=await createServer({root,logLevel:'error',server:{watch:null,host:'127.0.0.1',port:0}});await vite.listen();
 browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH,args:['--no-sandbox','--autoplay-policy=no-user-gesture-required']});
 const page=await browser.newPage({viewport:{width:1100,height:800},acceptDownloads:true}),errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto('http://127.0.0.1:'+vite.httpServer.address().port+'/test-output/subtitles/index.html');
 const video=page.locator('.mv-player-stage>video');
 await page.waitForFunction(()=>document.querySelector('.mv-player-stage>video')?.readyState>=2,null,{timeout:60000});
 const sheet=page.getByRole('dialog',{name:'Настройки просмотра'});
 async function openCaptions(){await page.getByRole('button',{name:'Настройки плеера',exact:true}).click();await sheet.waitFor();await sheet.locator('.mvx-row').filter({hasText:/^Субтитры/}).click();await sheet.getByRole('radiogroup',{name:'Субтитры',exact:true}).waitFor();}
 async function close(){await sheet.focus();await page.keyboard.press('Escape');await page.keyboard.press('Escape');await sheet.waitFor({state:'detached'}).catch(()=>{});}
 await openCaptions();
 const group=sheet.getByRole('radiogroup',{name:'Субтитры',exact:true});
 await group.getByRole('radio',{name:'Встроенные'}).waitFor();
 // Each track row carries its own «Скачать»; «Выключены» does not.
 assert.equal(await group.getByRole('button',{name:/^Скачать субтитры: /}).count(),await group.getByRole('radio').count()-1);
 await group.getByRole('radio',{name:'Crunchyroll'}).click();
 await close();
 await video.evaluate(v=>{v.currentTime=1;return v.play();});
 await page.waitForFunction(()=>document.querySelector('.mvx-captions')?.textContent.includes('Внешняя дорожка'),null,{timeout:15000});
 // Next episode: hls.js reloads its subtitle list; the chosen track must stay on.
 await page.getByRole('button',{name:'Другая серия фикстуры'}).click();
 await page.waitForFunction(()=>document.querySelector('.mv-player-stage>video')?.readyState>=2,null,{timeout:60000});
 await video.evaluate(v=>{v.currentTime=2;return v.play();});
 await page.waitForFunction(()=>document.querySelector('.mvx-captions')?.textContent.includes('Внешняя дорожка'),null,{timeout:15000}).catch(async error=>{
  console.error('text tracks',await video.evaluate(v=>[...v.textTracks].map(t=>[t.label,t.mode,t.cues?.length])));throw error;});
 // Downloads: external file as it is (BOM dropped), HLS group assembled into VTT, own SRT as SRT.
 await video.evaluate(v=>v.pause());
 await openCaptions();
 const save=async name=>{const [download]=await Promise.all([page.waitForEvent('download'),group.getByRole('button',{name:'Скачать субтитры: '+name}).click()]);return {name:download.suggestedFilename(),text:await fs.readFile(await download.path(),'utf8')};};
 const crunchyroll=await save('Crunchyroll');
 assert.equal(crunchyroll.text,external);
 assert.match(crunchyroll.name,/Эпизод 2 · Crunchyroll\.vtt$/);
 const stream=await save('Встроенные');
 assert.match(stream.name,/Встроенные\.vtt$/);
 assert.match(stream.text,/^WEBVTT\n\n00:00:00\.500 --> 00:00:05\.000\nПервая реплика\n\n00:00:06\.000 --> 00:00:11\.000\nВторая реплика\n$/);
 await page.locator('input[type=file][accept*=".srt"]').setInputFiles({name:'свои.srt',mimeType:'text/plain',buffer:Buffer.from('1\r\n00:00:00,000 --> 00:00:01,500\r\nСвои субтитры\r\n')});
 await group.getByRole('radio',{name:'Загруженные субтитры'}).waitFor();
 const own=await save('Загруженные субтитры');
 assert.match(own.name,/Загруженные субтитры\.srt$/);
 assert.equal(own.text,'1\r\n00:00:00,000 --> 00:00:01,500\r\nСвои субтитры\r\n');
 await page.screenshot({path:path.join(dir,'subtitle-menu.png')});
 assert.deepEqual(errors,[]);
 console.log('Player subtitles: OK (ffmpeg fixture HLS, external VTT, in-stream HLS subtitles, uploaded SRT).');
})().catch(e=>{console.error(e);process.exitCode=1;}).finally(async()=>{await browser?.close();await vite?.close();});
