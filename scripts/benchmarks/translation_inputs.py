"""Token protocol shared by real probes and offline regression checks."""
def inputs_for(model,cases,tokenizer):
 languages={'en':'eng_Latn','ja':'jpn_Jpan','ko':'kor_Hang'}
 tokens=[]
 for case in cases:
  value=tokenizer.encode(case['source'],out_type=str)
  if model=='nllb':value=[languages[case['language']]]+value
  if model in ['nllb','opus']:value=value+['</s>']
  tokens.append(value)
 kwargs={'target_prefix':[['rus_Cyrl'] for _ in cases]} if model=='nllb' else {}
 return tokens,kwargs
