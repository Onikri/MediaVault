// Before playback the online season and episode browser sits on the page; while a
// video plays it moves into the player's episode panel ("Выбрать серию"), where the
// page's season select is hidden and seasons are tabs of the player.
async function showEpisodes(page){
 if(await page.getByLabel('Сезон просмотра').isVisible().catch(()=>false))return;
 if(!await page.locator('.mvx-episodes').count())await page.getByRole('button',{name:'Выбрать серию',exact:true}).click();
 await page.locator('.mvx-episodes').waitFor();
}
async function chooseSeason(page,value){
 await showEpisodes(page);
 const select=page.getByLabel('Сезон просмотра');
 if(await select.isVisible())return select.selectOption(value);
 const name=(await page.locator('[aria-label="Сезон просмотра"] option[value="'+value+'"]').textContent()).trim();
 await page.getByRole('tablist',{name:'Сезон плеера'}).getByRole('tab',{name,exact:true}).click();
}
module.exports=showEpisodes;module.exports.showEpisodes=showEpisodes;module.exports.chooseSeason=chooseSeason;
