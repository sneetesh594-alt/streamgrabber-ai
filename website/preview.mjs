import http from 'node:http';
import worker from '../dist/server/index.js';
const flag = process.argv.indexOf('--port');
const port = Number(flag >= 0 ? process.argv[flag+1] : process.env.PORT || 5173);
const server=http.createServer(async(req,res)=>{
  try{
    const args={method:req.method,headers:req.headers};
    if(req.method==='POST'){args.body=req;args.duplex='half';}
    const result=await worker.fetch(new Request('http://localhost'+req.url,args),{});
    res.writeHead(result.status,Object.fromEntries(result.headers));
    res.end(Buffer.from(await result.arrayBuffer()));
  }catch{res.writeHead(502);res.end();}
});
server.listen(port,'0.0.0.0');
