/* Extra pilot assertions on already-created disposable journey records. */
const assert=require('node:assert/strict');
const pairs=[['Тбилиси','Батуми'],['Tbilisi','Batumi'],['თბილისი','ბათუმი']];
async function searchAliases(page,{kind,label,id}){
 assert.equal(new URL(page.url()).origin,'http://127.0.0.1:8765');
 const transport=kind==='transport',from=transport?'tFilterFrom':'fFrom',to=transport?'tFilterTo':'fTo';
 const submit=transport?'btnFindTransport':'loadSearchBtn',list=transport?'transportList':'cargoList';
 let expected;
 const results=[];
 for(const [origin,destination]of pairs){
  await page.locator('#'+from).click();await page.locator('#'+from).fill(origin);
  await page.locator('#'+to).click();await page.locator('#'+to).fill(destination);
  await page.locator('#'+submit).click();
  await page.waitForLoadState('networkidle');
  const target=transport?page.locator('#'+list+' .card-load').filter({hasText:label}).first()
   :page.locator('#'+list+' button[onclick*="x=>x.id=='+Number(id)+')"]:visible').first();
  await target.waitFor({state:'visible'});
  const identities=await page.locator('#'+list+' .card-load').evaluateAll(nodes=>nodes.map(node=>
   node.getAttribute('onclick')||node.querySelector('button.card-btn-resp')?.getAttribute('onclick')).sort());
  assert.ok(identities.length>0,'Created listing must be found');
  if(expected)assert.deepEqual(identities,expected,'RU/EN/KA filters must return the same listing identities');
  else expected=identities;
  results.push({from:origin,to:destination,matches:identities.length});
 }
 if(transport){
  const card=page.locator('#transportList .card-load').filter({hasText:label}).first();
  await card.locator('.transport-confirmation:visible').filter({hasText:'Доступность подтверждена'}).first().waitFor({state:'visible'});
  assert.match(await card.textContent(),/Новый перевозчик/);
  assert.doesNotMatch(await card.textContent(),/⭐\s*5(?:\.0)?/);
 }
 console.log('pilot '+kind+': RU/EN/KA aliases find identical real fixture listings');
 return results;
}
module.exports={searchAliases};
