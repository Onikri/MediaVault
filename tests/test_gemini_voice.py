"""Fixture contract for the Gemini Live narration relay: no real Google calls."""
import base64,json,sys,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server'))
import websockets
from fastapi import FastAPI
from fastapi.testclient import TestClient
import gemini_voice as voice

class FakeSocket:
 def __init__(self,key,script):self.key=key;self.script=list(script);self.sent=[]
 async def __aenter__(self):return self
 async def __aexit__(self,*exc):return False
 async def send(self,text):self.sent.append(json.loads(text))
 async def recv(self):
  item=self.script.pop(0)
  if isinstance(item,Exception):raise item
  return json.dumps(item)

def audio(data):return {'serverContent':{'modelTurn':{'parts':[{'inlineData':{'mimeType':'audio/pcm;rate=24000','data':base64.b64encode(data).decode()}}]}}}
LINE=bytes(range(256))*120  # 30720 bytes: 0.64 s of 24 kHz PCM
SPOKEN=[{'setupComplete':{}},audio(LINE[:20000]),audio(LINE[20000:]),{'serverContent':{'turnComplete':True}}]
SILENT=[{'setupComplete':{}},{'serverContent':{'turnComplete':True}}]
SPEECH=b'\x07\x00'*9000
def wav(pcm):
 fmt=(1).to_bytes(2,'little')+(1).to_bytes(2,'little')+(24000).to_bytes(4,'little')+(48000).to_bytes(4,'little')+(2).to_bytes(2,'little')+(16).to_bytes(2,'little')
 return b'RIFF'+(36+len(pcm)).to_bytes(4,'little')+b'WAVEfmt '+(16).to_bytes(4,'little')+fmt+b'data'+len(pcm).to_bytes(4,'little')+pcm
def spoken(pcm):return 200,{'candidates':[{'content':{'parts':[{'inlineData':{'mimeType':'audio/wav','data':base64.b64encode(pcm).decode()}}]}}]}

class GeminiVoiceTests(unittest.TestCase):
 def setUp(self):
  self.keys=[{'slot':i,'key':'fixture-key-'+str(i)} for i in range(3)];self.sockets=[];self.scripts={}
  app=FastAPI();voice.install(app,lambda:'owner',lambda:self.keys);self.client=TestClient(app)
  def connect(url,additional_headers=None,**kw):
   key=additional_headers['x-goog-api-key'];socket=FakeSocket(key,self.scripts.get(key,SPOKEN));self.sockets.append(socket);return socket
  self.patch=patch.object(voice.websockets,'connect',connect);self.patch.start();self.addCleanup(self.patch.stop)
  # The Lite speech model (HTTP): records every request; answers with WAV by default.
  self.posts=[];self.tts=lambda key:spoken(wav(SPEECH))
  async def post(url,key,payload):self.posts.append((url,key,payload));return self.tts(key)
  speech=patch.object(voice,'_post',post);speech.start();self.addCleanup(speech.stop)
 def speak(self,**extra):return self.client.post('/reader/google/speak',json={'text':'— Ты опоздал, — сказала она.','voice':'Kore','style':'эмоция: сердито','language':'ru',**extra})
 def test_streams_pcm_and_asks_for_a_verbatim_reading_in_the_chosen_voice(self):
  response=self.speak()
  self.assertEqual(response.status_code,200,response.text);self.assertEqual(response.content,LINE)
  setup=self.sockets[0].sent[0]['setup']
  self.assertEqual(setup['model'],'models/'+voice.MODEL)
  self.assertEqual(setup['generationConfig']['speechConfig']['voiceConfig']['prebuiltVoiceConfig']['voiceName'],'Kore')
  prompt=setup['systemInstruction']['parts'][0]['text'];self.assertIn('ДОСЛОВНО',prompt);self.assertIn('эмоция: сердито',prompt)
  self.assertEqual(self.sockets[0].sent[1],{'realtimeInput':{'text':'Прочитай вслух дословно фрагмент книги:\n— Ты опоздал, — сказала она.'}})
  self.assertEqual(setup['generationConfig']['thinkingConfig'],{'thinkingBudget':0},'thinking ate the audio of short lines')
  self.assertIn('никогда не отвечай',prompt)
  self.assertEqual(self.posts,[],'spoken lines never reach the speech model')
 def test_quota_refusal_moves_to_the_next_server_key(self):
  closed=websockets.ConnectionClosedError(websockets.frames.Close(1011,'RESOURCE_EXHAUSTED: quota exceeded'),None)
  first=self.speak().status_code;used=self.sockets[0].key
  self.scripts={used:[closed]};self.sockets.clear()
  # The rotation starts on the next slot, so make every slot but one refuse.
  for row in self.keys:
   if row['key']!=used:self.scripts[row['key']]=[closed]
  self.scripts[used]=SPOKEN
  response=self.speak()
  self.assertEqual(first,200);self.assertEqual(response.status_code,200,response.text);self.assertEqual(response.content,LINE)
  self.assertGreaterEqual(len(self.sockets),2);self.assertEqual(self.sockets[-1].key,used)
 def test_all_keys_spent_is_a_429_without_secrets(self):
  closed=websockets.ConnectionClosedError(websockets.frames.Close(1011,'RESOURCE_EXHAUSTED'),None)
  self.scripts={r['key']:[closed] for r in self.keys}
  response=self.speak();self.assertEqual(response.status_code,429);self.assertNotIn('fixture-key',response.text);self.assertEqual(len(self.sockets),3)
 def test_personal_key_is_used_alone(self):
  response=self.speak(key='personal-fixture-key-123456789');self.assertEqual(response.status_code,200)
  self.assertEqual([s.key for s in self.sockets],['personal-fixture-key-123456789'])
 def test_unknown_voice_and_language_are_refused(self):
  self.assertEqual(self.speak(voice='Alice').status_code,422);self.assertEqual(self.speak(language='en').status_code,422);self.assertEqual(self.sockets,[])
 def test_a_silent_line_is_read_by_the_lite_speech_model_in_the_same_voice(self):
  self.scripts={r['key']:SILENT for r in self.keys}
  response=self.client.post('/reader/google/speak',json={'text':'Да.','voice':'Charon','style':'эмоция: устало','language':'ru'})
  self.assertEqual(response.status_code,200,response.text);self.assertEqual(response.content,SPEECH,'WAV header removed')
  self.assertEqual(response.headers['x-audio-model'],'gemini-3.8-flash-lite-tts')
  self.assertEqual(len(self.sockets),1,'silence is not asked again on other Live keys')
  url,key,payload=self.posts[0]
  self.assertIn('gemini-3.8-flash-lite-tts:generateContent',url);self.assertEqual(key,self.sockets[0].key)
  self.assertEqual(payload['contents'],[{'parts':[{'text':'Да.'}]}],'plain text only: this model reads instructions aloud')
  self.assertEqual(payload['generationConfig']['speechConfig']['voiceConfig']['prebuiltVoiceConfig']['voiceName'],'Charon')
 def test_a_breath_counts_as_silence(self):
  self.scripts={r['key']:[{'setupComplete':{}},audio(b'\x01\x00'*2000),{'serverContent':{'turnComplete':True}}] for r in self.keys}
  response=self.speak();self.assertEqual(response.status_code,200);self.assertEqual(response.content,SPEECH);self.assertEqual(len(self.posts),1)
 def test_speech_model_quota_moves_to_the_next_key_and_failure_is_reported(self):
  self.scripts={r['key']:SILENT for r in self.keys}
  self.tts=lambda key:(429,{}) if len(self.posts)<3 else spoken(b'\x01\x00'*4)
  response=self.speak();self.assertEqual(response.status_code,200);self.assertEqual(len(self.posts),3);self.assertEqual(response.content,b'\x01\x00'*4)
  self.posts.clear();self.tts=lambda key:(200,{'candidates':[]})
  response=self.speak();self.assertEqual(response.status_code,502);self.assertNotIn('fixture-key',response.text)

if __name__=='__main__':unittest.main()
