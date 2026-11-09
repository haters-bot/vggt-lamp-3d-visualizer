export function validateCache(cache) {
  if(!cache||!Array.isArray(cache.images)||cache.images.length<2)throw new Error('缓存 images 必须含至少两张图片');
  if(new Set(cache.images).size!==cache.images.length||cache.images.some(x=>typeof x!=='string'||!x||/[\\/]/.test(x)))throw new Error('缓存图片名重复或含路径');
  if(cache.index_base!==undefined&&cache.index_base!==0)throw new Error('缓存必须使用从 0 开始的输入序号');
  if(!cache.pairs||typeof cache.pairs!=='object'||Array.isArray(cache.pairs))throw new Error('缓存缺少 pairs 对象');
  const entries=Object.entries(cache.pairs);if(!entries.length)throw new Error('缓存 pairs 为空');
  for(const [key,value] of entries){
    if(!/^(0|[1-9]\d*)->(0|[1-9]\d*)$/.test(key))throw new Error(`无效 pair 键：${key}`);
    const [a,b]=key.split('->').map(Number);
    if(a===b||a>=cache.images.length||b>=cache.images.length)throw new Error(`pair 超出图片范围或为自身：${key}`);
    for(const name of ['range_m','seconds'])if(!Number.isFinite(value?.[name]))throw new Error(`${key}.${name} 必须是有限数值`);
    if(value.seconds<0)throw new Error(`无效推理耗时：${key}`);
    if(!value.decoded||!Number.isFinite(value.decoded.heading_deg)||!Number.isFinite(value.decoded.range_m)||!Number.isInteger(value.decoded.label_index)||value.decoded.label_index<0)throw new Error(`无效 decoded：${key}`);
  }
  return cache;
}
