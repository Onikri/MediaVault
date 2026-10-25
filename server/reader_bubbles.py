"""Find closed speech interiors and group OCR rows by their actual bubble.

OpenCV runs on CPU, bounded to the already resized OCR image. Uncertain text
stays a note instead of painting an arbitrary rectangle over the artwork.
"""
import re

def join_rows(rows):
    result=''
    for r in sorted(rows,key=lambda v:(round(v['y']*400),v['x'])):
        text=r['original'].strip()
        result=result[:-1]+text if re.search(r'[A-Za-z]-$',result) and re.match('[A-Za-z]',text) else (result+' '+text).strip()
    return result

def speech_regions(image,regions):
    import cv2,numpy as np
    cv2.setNumThreads(1)
    width,height=image.size;gray=cv2.cvtColor(np.asarray(image),cv2.COLOR_RGB2GRAY)
    ink=cv2.threshold(gray,200,255,cv2.THRESH_BINARY_INV)[1]
    closed=cv2.morphologyEx(ink,cv2.MORPH_CLOSE,np.ones((3,3),np.uint8))
    count,labels,stats,_=cv2.connectedComponentsWithStats(255-closed,8)
    groups={};notes=[]
    for r in regions:
        x=max(0,int(r['x']*width));y=max(0,int(r['y']*height));right=min(width,int((r['x']+r['w'])*width));bottom=min(height,int((r['y']+r['h'])*height))
        if right<=x or bottom<=y:continue
        ids,numbers=np.unique(labels[y:bottom,x:right],return_counts=True)
        choices=sorted(zip(ids,numbers),key=lambda p:p[1],reverse=True);chosen=None
        for identity,n in choices:
            if not identity:continue
            bx,by,bw,bh,area=map(int,stats[identity]);overlap=max(0,min(right,bx+bw)-max(x,bx))*max(0,min(bottom,by+bh)-max(y,by))
            if bx<=2 or by<=2 or bx+bw>=width-2 or by+bh>=height-2:continue
            if not (.018*width<=bw<=.46*width and .012*height<=bh<=.48*height and area>60 and area/(bw*bh)>.28):continue
            if overlap/((right-x)*(bottom-y))<.85:continue
            chosen=int(identity);break
        if chosen is None:notes.append(r)
        else:groups.setdefault(chosen,[]).append(r)
    from reader_translation import merge_bubbles
    split=[]
    for identity,rows in groups.items():
        blocks=merge_bubbles(rows)
        for block in blocks:
            attached=[r for r in rows if r['x']>=block['x']-.001 and r['y']>=block['y']-.001 and r['x']+r['w']<=block['x']+block['w']+.001 and r['y']+r['h']<=block['y']+block['h']+.001]
            if attached:split.append((identity,attached))
    output=[]
    for identity,rows in split:
        bx,by,bw,bh,area=map(int,stats[identity]);text=join_rows(rows)
        confidence=sum(r.get('confidence',70) for r in rows)/len(rows)
        letters=len(re.findall('[A-Za-z]',text))
        short=text.strip(' .?!').casefold()
        if confidence<44 or letters<5 and not (confidence>=80 and short in {'no','yes','nah','oh','hey','ok','okay','huh','what','hi','bye','wow','ah'}):continue
        # A tiny stray OCR word in a large region is usually part of the drawing.
        occupied=sum(r['w']*width*r['h']*height for r in rows)/(bw*bh)
        if occupied<.025 or occupied<.06 and len(text)<10:continue
        # A connected tail can join separate balloons. Bound each text block
        # before extracting its shape so neighbouring dialogue cannot mix.
        tx=min(r['x'] for r in rows)*width;ty=min(r['y'] for r in rows)*height
        tr=max(r['x']+r['w'] for r in rows)*width;tb=max(r['y']+r['h'] for r in rows)*height
        glyph=max(6,min(r['h']*height for r in rows));pad=min(30,max(8,glyph*.9))
        nx=max(bx,int(tx-pad));ny=max(by,int(ty-pad));nr=min(bx+bw,int(tr+pad));nb=min(by+bh,int(tb+pad))
        bx,by,bw,bh=nx,ny,nr-nx,nb-ny
        if bw<8 or bh<8:continue
        mask=(labels[by:by+bh,bx:bx+bw]==identity).astype('uint8')*255
        contours,_=cv2.findContours(mask,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
        if not contours:continue
        contour=max(contours,key=cv2.contourArea);poly=cv2.approxPolyDP(contour,max(1,.008*cv2.arcLength(contour,True)),True)
        shape=[[round(int(p[0][0])/bw,4),round(int(p[0][1])/bh,4)] for p in poly[:80]]
        # Retain the source paper color; white text boxes should not turn yellow
        # paper into dozens of bright patches.
        pixels=np.asarray(image)[by:by+bh,bx:bx+bw][mask>0]
        color=[int(v) for v in np.median(pixels,axis=0)]
        left=min(r['x'] for r in rows);top=min(r['y'] for r in rows);right=max(r['x']+r['w'] for r in rows);bottom=max(r['y']+r['h'] for r in rows)
        output.append({'x':bx/width,'y':by/height,'w':bw/width,'h':bh/height,'original':text,'confidence':round(confidence),'placement':'bubble','shape':shape,'color':color,'ocrBox':{'x':left,'y':top,'w':right-left,'h':bottom-top}})
    from reader_translation import merge_bubbles
    for r in merge_bubbles(notes):
        text=r['original'];letters=re.findall('[A-Za-z]',text)
        # Isolated tiny artifacts and a chain of single letters are not dialogue.
        if len(letters)<9 or len(text.split())<2 or len(re.findall(r'\b[A-Za-z]\b',text))>max(2,len(text.split())//2):continue
        output.append({**r,'placement':'note','confidence':0})
    return sorted(output,key=lambda r:(r['y'],r['x']))[:60]
