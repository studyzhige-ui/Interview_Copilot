const orbitGroup=document.createElement('div');orbitGroup.className='ct-orbits';orbitGroup.setAttribute('aria-hidden','true');
for(let i=0;i<8;i++){const item=document.createElement('span');item.className=i<3?'ct-orbit':'ct-orbit-dot';orbitGroup.append(item)}
q('.ct-hero').prepend(orbitGroup);
