const path=require('node:path');
function webURL(value){
  if(typeof value!=='string'||value.length>8192)throw Error('请输入有效网页地址');
  const url=new URL(value.includes('://')?value:'https://'+value);
  if(!['https:','http:'].includes(url.protocol)||url.username||url.password)throw Error('仅支持 HTTP 或 HTTPS 网页地址');
  return url.href;
}
function safePath(base,relative){
  const target=path.resolve(base,relative),rel=path.relative(base,target);
  if(rel==='..'||rel.startsWith('..'+path.sep)||path.isAbsolute(rel))throw Error('无效文件路径');
  return target;
}
module.exports={webURL,safePath};
