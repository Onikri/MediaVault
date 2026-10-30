#!/usr/bin/env python3
"""Bound disposable online-page cache, without touching downloads or models."""
from pathlib import Path
import argparse,json,os,stat,time


def prune(root,*,now=None,max_bytes=512*1024*1024,max_age=3600,min_age=300):
    root=Path(root)
    if root.is_symlink() or root.name!='suwayomi-reader' or '.codex-local' not in root.parts:
        raise ValueError('Expected the dedicated project reader cache.')
    if root.resolve()!=root.absolute():raise ValueError('Cache path must not traverse symlinks.')
    now=time.time() if now is None else now
    files=[]
    for directory,dirs,names in os.walk(root,followlinks=False):
        dirs[:]=[name for name in dirs if not (Path(directory)/name).is_symlink()]
        for name in names:
            path=Path(directory)/name
            try:
                info=path.lstat()
                if stat.S_ISREG(info.st_mode):files.append((info.st_mtime,info.st_size,path))
            except FileNotFoundError:pass
    total=sum(size for _,size,_ in files);removed=0
    for modified,size,path in sorted(files):
        if now-modified<min_age:continue # do not interrupt current downloads
        if total<=max_bytes and now-modified<max_age:continue
        try:
            if path.is_symlink():continue
            path.unlink();total-=size;removed+=1
        except FileNotFoundError:pass
    # Only empty cache subdirectories; leave the mount point itself intact.
    for directory,_,_ in os.walk(root,topdown=False,followlinks=False):
        if Path(directory)==root:continue
        try:Path(directory).rmdir()
        except OSError:pass
    return {'removed':removed,'remainingBytes':total}


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('root')
    print(json.dumps(prune(parser.parse_args().root)))
