import { readFile, writeFile, mkdir, readdir, copyFile } from 'node:fs/promises';
import { extname, join, relative, resolve } from 'node:path';

const base = resolve('ai_clipper/studio');
const types = {'.css':'text/css; charset=utf-8','.html':'text/html; charset=utf-8','.js':'text/javascript; charset=utf-8',
  '.webmanifest':'application/manifest+json','.webp':'image/webp','.svg':'image/svg+xml','.woff2':'font/woff2',
  '.mp4':'video/mp4','.json':'application/json','.txt':'text/plain; charset=utf-8'};
const assets={};
async function walk(folder){
  for(const entry of await readdir(folder,{withFileTypes:true})){
    const file=join(folder,entry.name);
    if(entry.isDirectory()){await walk(file);continue;}
    const type=types[extname(file)];
    if(!type) throw new Error('Unsupported studio asset '+entry.name);
    const bin=['.mp4','.webp','.woff2'].includes(extname(file));
    const body=(await readFile(file)).toString(bin?'base64':'utf8');
    const key=relative(base,file).split('\\').join('/');
    assets[key==='index.html'?'/':'/studio-assets/'+key]=[type,bin?'binary':'text',body];
  }
}
await walk(base);
await mkdir('dist/server',{recursive:true});
await mkdir('dist/.openai',{recursive:true});
await writeFile('dist/server/index.js','const assets = '+JSON.stringify(assets)+';\n'+await readFile('website/worker.js','utf8'));
await copyFile('.openai/hosting.json','dist/.openai/hosting.json');
