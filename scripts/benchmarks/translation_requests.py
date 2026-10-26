"""Explicit provider prompt contracts; model results record the chosen profile."""
def segment_request(source,model,profile='standard'):
 if profile=='index':
  return {'model':model,'messages':[{'role':'user','content':'请将以下文本翻译为俄语，直接输出翻译结果，不要进行任何解释。\n\n'+source}], 'temperature':0,'max_tokens':512,'chat_template_kwargs':{'enable_thinking':False}}
 if profile=='hymt2':
  # Official model card: no system prompt, full target language name.
  return {'model':model,'messages':[{'role':'user','content':'Translate the following text into Russian. Note that you should only output the translated result without any additional explanation:\n\n'+source}], 'temperature':.7,'top_p':.6,'top_k':20,'repeat_penalty':1.05,'seed':42,'max_tokens':512}
 return {'model':model,'temperature':0,'seed':42,'max_tokens':512,'chat_template_kwargs':{'enable_thinking':False},'messages':[{'role':'system','content':'Translate manga dialogue into natural Russian. Preserve names, negation and meaning. Return only the translated dialogue, no explanations.'},{'role':'user','content':source}]}
