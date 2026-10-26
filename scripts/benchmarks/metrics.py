"""Small explicit quality metrics; labels/references are never model output."""
import re,unicodedata

def iou(a,b):
 x=max(0,min(a[2],b[2])-max(a[0],b[0]));y=max(0,min(a[3],b[3])-max(a[1],b[1]));intersection=x*y
 union=max(0,a[2]-a[0])*max(0,a[3]-a[1])+max(0,b[2]-b[0])*max(0,b[3]-b[1])-intersection
 return intersection/union if union else 0

def match_boxes(expected,predicted,threshold=.3):
 # Maximum-cardinality bipartite matching avoids counting one box twice.
 edges={i:sorted([j for j,p in enumerate(predicted) if iou(e,p)>=threshold],key=lambda j:iou(e,predicted[j]),reverse=True) for i,e in enumerate(expected)}
 assigned={}
 def visit(i,seen):
  for j in edges[i]:
   if j in seen:continue
   seen.add(j)
   if j not in assigned or visit(assigned[j],seen):assigned[j]=i;return True
  return False
 for i in edges:visit(i,set())
 tp=len(assigned);precision=tp/len(predicted) if predicted else 0;recall=tp/len(expected) if expected else 0
 return {'tp':tp,'fp':len(predicted)-tp,'fn':len(expected)-tp,'precision':precision,'recall':recall,'f1':2*precision*recall/(precision+recall) if precision+recall else 0,'iouThreshold':threshold}

def normalize_text(text):return re.sub(r'\s+',' ',unicodedata.normalize('NFKC',text).casefold()).strip()
def edit_distance(a,b):
 row=list(range(len(b)+1))
 for i,x in enumerate(a,1):
  nxt=[i]
  for j,y in enumerate(b,1):nxt.append(min(nxt[-1]+1,row[j]+1,row[j-1]+(x!=y)))
  row=nxt
 return row[-1]
def cer(reference,hypothesis):
 a,b=normalize_text(reference),normalize_text(hypothesis);return edit_distance(a,b)/max(1,len(a))
